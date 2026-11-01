from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Set, Tuple

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
    # Denominador da adoção: validadores com versão conhecida fora de piloto.
    # Exposto para a UI exibir "N de M".
    total_conhecido: int = 0
    # Validadores em versão acima da alvo (pilotos): ficam fora do
    # denominador da adoção e dos pendentes — estão à frente, não atrasados.
    em_piloto: int = 0


def _version_key(v: str) -> Tuple[int, int, int, str]:
    m = VERSION_REGEX.match(v.strip())
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), v)
    return (-1, -1, -1, v)


def latest_date(df: pd.DataFrame) -> date:
    return df["data"].max()


def _latest_snapshot_as_of(df: pd.DataFrame, ref: date) -> pd.DataFrame:
    """Retorna o último estado conhecido por validador até `ref`.

    Args:
        df: DataFrame com colunas data, id_veiculo, id_validador e versao_app.
        ref: Data de referência para o recorte as-of.

    Returns:
        DataFrame com uma linha por id_validador contendo o registro mais recente
        até `ref`, priorizando versão mais alta quando houver empate no mesmo dia.
    """
    base = df[df["data"] <= ref]
    if base.empty:
        return base.copy()
    base = _dedupe_max_version_per_day(base)
    keyed = base.assign(_vk=base["versao_app"].apply(_version_key)).sort_values(
        ["id_validador", "data", "_vk"]
    )
    return keyed.drop_duplicates(["id_validador"], keep="last").drop(columns="_vk")


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def merge_last_known_state(
    prev_state: Dict[str, dict],
    window_df: pd.DataFrame,
    roster: Optional[pd.DataFrame],
    today: date,
    prune_days: int = 90,
) -> Dict[str, dict]:
    """Acumula incrementalmente a última versão conhecida por validador.

    Nunca consulta o BigQuery para trás: quem pingou na janela atualiza sua
    entrada; quem não pingou mantém a última (versão não muda sem energia).

    Entradas fora do roster são descartadas após `prune_days` sem ping —
    equipamento trocado/enviado à Jaé não volta a reportar.
    """
    state: Dict[str, dict] = {k: dict(v) for k, v in prev_state.items()}

    # Monotônico por data_ultimo_ping: só sobrescreve se o ping da janela for
    # igual ou mais recente que o já acumulado. Evita que uma sessão com df
    # mais antigo (concorrência entre sessões do Streamlit) regrida a memória.
    # No mesmo dia, desempata pela versão mais alta (como _latest_snapshot_as_of):
    # a query só guarda a data do ping, então uma sessão com df stale do mesmo
    # dia poderia regredir a build lembrada sem esse desempate.
    snap = _latest_snapshot_as_of(window_df, latest_date(window_df))
    for row in snap.itertuples():
        vid = str(row.id_validador)
        existing = state.get(vid) or {}
        existing_ping = _parse_iso_date(existing.get("data_ultimo_ping"))
        if existing_ping is not None:
            if existing_ping > row.data:
                continue
            existing_version = existing.get("versao_app")
            if (
                existing_ping == row.data
                and existing_version
                and _version_key(existing_version) >= _version_key(str(row.versao_app))
            ):
                continue
        state[vid] = {
            "id_veiculo": str(row.id_veiculo),
            "versao_app": str(row.versao_app),
            "data_ultimo_ping": row.data.isoformat(),
        }

    if roster is not None and not roster.empty:
        keep = set(roster["id_validador"])
        cutoff = today - timedelta(days=prune_days)
        state = {
            vid: rec
            for vid, rec in state.items()
            if vid in keep
            or (_parse_iso_date(rec.get("data_ultimo_ping")) or date.min) >= cutoff
        }
    return state


def _known_universe(
    df: pd.DataFrame,
    state: Optional[Dict[str, dict]],
    roster: Optional[pd.DataFrame],
) -> Dict[str, dict]:
    """Último registro conhecido por validador: {id_veiculo, versao_app, ultimo_ping}.

    Do menor para o maior precedente de informação: roster (existe na frota)
    < estado persistente < janela do BigQuery.
    """
    rows: Dict[str, dict] = {}
    if roster is not None and not roster.empty:
        for r in roster.itertuples():
            rows[str(r.id_validador)] = {
                "id_veiculo": str(r.id_veiculo),
                "versao_app": None,
                "ultimo_ping": None,
            }
    if state:
        for vid, rec in state.items():
            rows[vid] = {
                "id_veiculo": rec.get("id_veiculo", ""),
                "versao_app": rec.get("versao_app") or None,
                "ultimo_ping": _parse_iso_date(rec.get("data_ultimo_ping")),
            }
    snapshot = _latest_snapshot_as_of(df, latest_date(df))
    for r in snapshot.itertuples():
        rows[str(r.id_validador)] = {
            "id_veiculo": str(r.id_veiculo),
            "versao_app": str(r.versao_app),
            "ultimo_ping": r.data,
        }
    return rows


def find_replaced(
    df: pd.DataFrame,
    state: Optional[Dict[str, dict]] = None,
    roster: Optional[pd.DataFrame] = None,
    slots: int = 2,
) -> Set[str]:
    """Validadores que saíram do veículo porque outro serial ocupou a vaga.

    Cada veículo tem `slots` validadores. Se no mesmo veículo há pelo menos
    `slots` outros validadores com ping mais recente que o dele, o serial foi
    trocado (ex.: validador em loop de reinício substituído por outro). Ele
    sai das contagens em vez de aparecer como 3º validador "offline" do carro.
    Validador mapeado que nunca reportou, num veículo com `slots` outros
    reportando, é mapeamento desatualizado: mesmo tratamento.

    A comparação é por dia (a query só guarda a data do ping): troca feita no
    mesmo dia empata e só se resolve na consulta seguinte. Três validadores
    pingando no mesmo dia também empatam — anomalia de cadastro que continua
    visível em vez de ser escondida.

    Não poda a memória de última versão: se o serial voltar a pingar em
    qualquer veículo, a janela o traz de volta e a regra é reavaliada.
    """
    by_vehicle: Dict[str, List[Tuple[str, Optional[date]]]] = {}
    for vid, rec in _known_universe(df, state, roster).items():
        if rec["id_veiculo"]:
            by_vehicle.setdefault(rec["id_veiculo"], []).append((vid, rec["ultimo_ping"]))

    replaced: Set[str] = set()
    for members in by_vehicle.values():
        if len(members) <= slots:
            continue
        for vid, ping in members:
            newer = sum(
                1
                for other, other_ping in members
                if other != vid
                and other_ping is not None
                and (ping is None or other_ping > ping)
            )
            if newer >= slots:
                replaced.add(vid)
    return replaced


def is_pilot(version: Optional[str], target_build: str) -> bool:
    """Versão acima da build alvo está em piloto — à frente, não pendente."""
    if not version or version == "—" or not target_build:
        return False
    return _version_key(version) > _version_key(target_build)


def detect_target_build(
    df: pd.DataFrame,
    declared_pilots: Iterable[str] = (),
    forced: str = "",
    min_share: float = 0.10,
    exclude: Optional[Set[str]] = None,
) -> str:
    """Build alvo: a versão que está sendo distribuída para a frota toda.

    Automática: a versão mais alta, no último estado da janela fresca, com
    pelo menos `min_share` dos validadores. As que ficam acima dela com menos
    que isso são pilotos (ex.: biometria em 6 veículos), não a alvo. Versões
    em `declared_pilots` nunca viram alvo, qualquer que seja a fatia.

    `forced` (secrets) vence a detecção só se alguém já reporta essa versão e
    ela não é mais antiga que a automática: uma build forçada esquecida nos
    secrets deixa de valer sozinha quando o rollout seguinte passa à frente.
    Validadores em `exclude` (substituídos) não entram na conta.
    """
    snapshot = _latest_snapshot_as_of(df, latest_date(df))
    if exclude:
        snapshot = snapshot[~snapshot["id_validador"].isin(exclude)]
    counts = snapshot["versao_app"].dropna().astype(str).value_counts()
    if counts.empty:
        return ""
    total = int(counts.sum())
    declared = set(declared_pilots)
    candidates = sorted(
        (v for v in counts.index if v not in declared), key=_version_key, reverse=True
    )
    target = next((v for v in candidates if counts[v] / total >= min_share), "")
    if not target:
        # Frota fragmentada (nenhuma versão fora dos pilotos com a fatia
        # mínima): a mais comum entre as não declaradas.
        target = (
            max(candidates, key=lambda v: counts[v])
            if candidates
            else max(counts.index, key=_version_key)
        )
    if forced and forced in counts.index and _version_key(forced) >= _version_key(target):
        target = forced
    return target


def compute_kpis(
    df: pd.DataFrame,
    target_build: str,
    state: Optional[Dict[str, dict]] = None,
) -> KPIs:
    ref = latest_date(df)
    snapshot = _latest_snapshot_as_of(df, ref)

    # Com estado persistente, adoção/variedade/meta refletem a última versão
    # CONHECIDA (validador em manutenção conta como a versão que tinha ao parar
    # de reportar). Frota operante continua sendo quem reportou na janela.
    if state:
        known = [
            rec.get("versao_app") for rec in state.values() if rec.get("versao_app")
        ]
    else:
        known = snapshot["versao_app"].dropna().astype(str).tolist()

    on_target = sum(1 for v in known if v == target_build)
    em_piloto = sum(1 for v in known if is_pilot(v, target_build))
    total_validadores = len(known) - em_piloto
    pct = (on_target / total_validadores * 100.0) if total_validadores else 0.0
    return KPIs(
        frota_operante=int(snapshot["id_veiculo"].nunique()),
        adocao_alvo_pct=pct,
        variedade=len(set(known)),
        meta_atingida=on_target,
        target_build=target_build,
        reference_date=ref,
        total_conhecido=total_validadores,
        em_piloto=em_piloto,
    )


def build_history_series(
    df: pd.DataFrame, days: int = 3, replaced: Optional[Set[str]] = None
) -> pd.DataFrame:
    """Constrói série diária por versão com snapshot as-of na janela recente.

    Para cada data da janela (padrão: últimos 3 dias disponíveis), calcula a
    distribuição por versão usando o último estado conhecido de cada validador
    até aquela data. Substituído só conta até o último dia em que pingou: o
    as-of não o carrega para os dias em que o veículo já tinha outro serial.
    """
    all_dates: List[date] = sorted(df["data"].unique())[-max(days, 1) :]
    chunks: List[pd.DataFrame] = []
    for d in all_dates:
        snapshot = _latest_snapshot_as_of(df, d)
        if replaced:
            snapshot = snapshot[
                ~(snapshot["id_validador"].isin(replaced) & (snapshot["data"] < d))
            ]
        if snapshot.empty:
            continue
        per_version = (
            snapshot.groupby("versao_app", as_index=False)["id_validador"]
            .nunique()
            .rename(columns={"id_validador": "validadores"})
        )
        per_version["data"] = pd.to_datetime(d)
        chunks.append(per_version)
    if not chunks:
        return pd.DataFrame(columns=["data", "versao_app", "validadores"])
    g = pd.concat(chunks, ignore_index=True)
    return g.sort_values(["versao_app", "data"])


def build_today_status(df: pd.DataFrame) -> pd.DataFrame:
    ref = latest_date(df)
    today_df = _latest_snapshot_as_of(df, ref)
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


def build_inventory_table(
    df: pd.DataFrame,
    target_build: str,
    fleet_truth: frozenset[str] | None = None,
    state: Optional[Dict[str, dict]] = None,
    roster: Optional[pd.DataFrame] = None,
    replaced: Optional[Set[str]] = None,
) -> pd.DataFrame:
    ref = latest_date(df)
    all_dates: List[date] = sorted(df["data"].unique())
    df_deduped = _dedupe_max_version_per_day(df)
    ordered = _ordered_versions(df_deduped, target_build)
    rows = _known_universe(df, state, roster)
    replaced = replaced or set()

    # Agregado só por id_validador (não por par com id_veiculo): se o
    # validador mudou de veiculo durante a janela, a atividade das datas em
    # que ele estava no veiculo anterior não pode se perder.
    by_validador = {
        val: (
            grp.assign(_vk=grp["versao_app"].apply(_version_key))
            .sort_values("_vk")
            .set_index("data")["versao_app"]
            .to_dict()
        )
        for val, grp in df_deduped.groupby("id_validador")
    }

    inventory = pd.DataFrame(
        [
            {
                "id_veiculo": v["id_veiculo"],
                "id_validador": vid,
                "build_atual": v["versao_app"] or "—",
                "_ping": v["ultimo_ping"],
            }
            for vid, v in rows.items()
        ],
        columns=["id_veiculo", "id_validador", "build_atual", "_ping"],
    )

    def activity_for(row: pd.Series) -> str:
        per_date = by_validador.get(row["id_validador"], {})
        return "".join(_dot_for_version(per_date.get(d), ordered) for d in all_dates)

    inventory["atividade_recente"] = inventory.apply(activity_for, axis=1)

    def _status(row: pd.Series) -> str:
        if row["id_validador"] in replaced:
            # Saiu do veículo: não volta a pingar ali, então offline não se aplica.
            return "SUBSTITUÍDO"
        build = row["build_atual"]
        if build == "—":
            base = "NUNCA REPORTOU"
        elif build == target_build:
            base = "ATUALIZADO"
        elif is_pilot(build, target_build):
            base = "PILOTO"
        else:
            base = "PENDENTE"
        if fleet_truth is None or row["id_validador"] in fleet_truth:
            return base
        dias = (ref - row["_ping"]).days if row["_ping"] else None
        if dias is not None and dias >= len(all_dates):
            unidade = "DIA" if dias == 1 else "DIAS"
            return f"{base} · OFFLINE HÁ {dias} {unidade}"

        return f"{base} · OFFLINE"

    inventory["status_final"] = inventory.apply(_status, axis=1)
    inventory["ultimo_ping"] = inventory["_ping"].map(
        lambda d: d.strftime("%d/%m") if d else "—"
    )

    inventory = inventory.sort_values(["id_veiculo", "id_validador"]).reset_index(drop=True)
    return inventory[
        [
            "id_veiculo",
            "id_validador",
            "build_atual",
            "ultimo_ping",
            "atividade_recente",
            "status_final",
        ]
    ]


def available_versions(inventory: pd.DataFrame) -> List[str]:
    """Versões selecionáveis no filtro, a partir do inventário completo.

    Usa o inventário (roster + estado + janela) em vez só do df da janela,
    para não esconder do filtro uma versão "lembrada" de um validador
    offline há mais tempo que não aparece nos últimos 3 dias.
    """
    versions = inventory["build_atual"].dropna().unique().tolist()
    versions = [v for v in versions if v != "—"]
    return sorted(versions, key=_version_key, reverse=True)


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
