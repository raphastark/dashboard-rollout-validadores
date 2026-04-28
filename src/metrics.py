from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import List, Tuple

import pandas as pd

VERSION_REGEX = re.compile(r"^V\.(\d+)\.(\d+)\.(\d+)$", re.IGNORECASE)

ACTIVITY_DOTS = ["🟢", "🔵", "🟡", "🟣", "🔴", "🟠", "🟤"]
NO_ACTIVITY_DOT = "⚪"


@dataclass
class KPIs:
    frota_operante: int
    adocao_alvo_pct: float
    variedade: int
    meta_atingida: int
    target_build: str
    reference_date: date


def _version_key(v: str) -> Tuple[int, int, int, str]:
    m = VERSION_REGEX.match(v.strip())
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), v)
    return (-1, -1, -1, v)


def latest_date(df: pd.DataFrame) -> date:
    return df["data"].max()


def detect_target_build(df: pd.DataFrame) -> str:
    most_recent = df[df["data"] == latest_date(df)]
    versions = most_recent["versao_app"].dropna().unique().tolist()
    if not versions:
        return ""
    return max(versions, key=_version_key)


def compute_kpis(df: pd.DataFrame, target_build: str) -> KPIs:
    ref = latest_date(df)
    today_df = df[df["data"] == ref]
    on_target = today_df[today_df["versao_app"] == target_build]

    total_validadores = today_df["id_validador"].nunique()
    on_target_validadores = on_target["id_validador"].nunique()
    pct = (on_target_validadores / total_validadores * 100.0) if total_validadores else 0.0

    return KPIs(
        frota_operante=int(today_df["id_veiculo"].nunique()),
        adocao_alvo_pct=pct,
        variedade=int(today_df["versao_app"].nunique()),
        meta_atingida=int(on_target_validadores),
        target_build=target_build,
        reference_date=ref,
    )


def build_history_series(df: pd.DataFrame) -> pd.DataFrame:
    g = (
        df.groupby(["data", "versao_app"], as_index=False)["id_validador"]
        .nunique()
        .rename(columns={"id_validador": "validadores"})
    )
    g["data"] = pd.to_datetime(g["data"])
    return g.sort_values(["versao_app", "data"])


def build_today_status(df: pd.DataFrame) -> pd.DataFrame:
    ref = latest_date(df)
    today_df = df[df["data"] == ref]
    g = (
        today_df.groupby("versao_app", as_index=False)["id_validador"]
        .nunique()
        .rename(columns={"id_validador": "validadores"})
    )
    g["__key"] = g["versao_app"].apply(_version_key)
    g = g.sort_values("__key", ascending=True).drop(columns="__key")
    return g.reset_index(drop=True)


def _ordered_versions(df: pd.DataFrame, target_build: str) -> List[str]:
    versions = sorted(df["versao_app"].dropna().unique(), key=_version_key, reverse=True)
    if target_build in versions and versions[0] != target_build:
        versions = [target_build] + [v for v in versions if v != target_build]
    return versions


def _dot_for_version(version: str | None, ordered_versions: List[str]) -> str:
    if version is None or version not in ordered_versions:
        return NO_ACTIVITY_DOT
    idx = ordered_versions.index(version)
    return ACTIVITY_DOTS[idx % len(ACTIVITY_DOTS)]


def _dedupe_max_version_per_day(df: pd.DataFrame) -> pd.DataFrame:
    """Se o mesmo validador reportou versões diferentes no mesmo dia, mantém a maior."""
    keyed = df.assign(_vk=df["versao_app"].apply(_version_key)).sort_values("_vk")
    return (
        keyed.drop_duplicates(["id_veiculo", "id_validador", "data"], keep="last")
        .drop(columns="_vk")
    )


def build_inventory_table(df: pd.DataFrame, target_build: str) -> pd.DataFrame:
    ref = latest_date(df)
    all_dates: List[date] = sorted(df["data"].unique())
    df = _dedupe_max_version_per_day(df)
    ordered = _ordered_versions(df, target_build)

    today_df = df[df["data"] == ref][["id_veiculo", "id_validador", "versao_app"]]
    today_df = today_df.rename(columns={"versao_app": "build_atual"})

    keys = df[["id_veiculo", "id_validador"]].drop_duplicates()
    inventory = keys.merge(today_df, on=["id_veiculo", "id_validador"], how="left")

    by_pair = {
        (v, val): grp.set_index("data")["versao_app"].to_dict()
        for (v, val), grp in df.groupby(["id_veiculo", "id_validador"])
    }

    def activity_for(row: pd.Series) -> str:
        per_date = by_pair.get((row["id_veiculo"], row["id_validador"]), {})
        return " ".join(_dot_for_version(per_date.get(d), ordered) for d in all_dates)

    inventory["atividade_recente"] = inventory.apply(activity_for, axis=1)
    inventory["build_atual"] = inventory["build_atual"].fillna("—")
    inventory["status_final"] = inventory["build_atual"].apply(
        lambda v: "OPERAÇÃO OK" if v == target_build else "PENDENTE"
    )

    inventory = inventory.sort_values(["id_veiculo", "id_validador"]).reset_index(drop=True)
    return inventory[
        ["id_veiculo", "id_validador", "build_atual", "atividade_recente", "status_final"]
    ]


def filter_inventory(
    inventory: pd.DataFrame, version: str | None, search: str | None
) -> pd.DataFrame:
    out = inventory
    if version and version != "Todas as versões":
        out = out[out["build_atual"] == version]
    if search:
        s = search.strip().lower()
        if s:
            mask = (
                out["id_veiculo"].str.lower().str.contains(s, na=False)
                | out["id_validador"].str.lower().str.contains(s, na=False)
            )
            out = out[mask]
    return out
