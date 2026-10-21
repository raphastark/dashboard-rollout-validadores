from __future__ import annotations

import base64
import html
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .metrics import (
    ACTIVITY_DOTS,
    NO_ACTIVITY_DOT,
    KPIs,
    _dedupe_max_version_per_day,
    _ordered_versions,
    _version_key,
)

# ---------------------------------------------------------------------------
# Identidade Novacap — tokens iguais aos do Monitoramento de Frota.
# O CSS (static/styles.css) consome os mesmos tokens via variáveis CSS
# injetadas por inject_styles(); os gráficos Plotly leem daqui.
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
LOGO_MARK = STATIC_DIR / "novacap-boneco-branco.png"
LOGO_WORDMARK = STATIC_DIR / "novacap-letras-branco.png"

FONT_UI = "Barlow, system-ui, sans-serif"
FONT_NUMBER = "Barlow Condensed, Barlow, sans-serif"
FONT_MONO = "IBM Plex Mono, ui-monospace, monospace"

HEADER_BG = "#293046"
HEADER_TEXT = "#ECEEF2"
SOURCE_OK = "#58D19B"
SOURCE_CRITICAL = "#F05A5A"
SOURCE_WARNING = "#E8A33D"

THEMES: Dict[str, Dict[str, str]] = {
    "dark": {
        "page": "#141D2B",
        "surface": "#1B2433",
        "track": "#222B3B",
        "border": "#2A3446",
        "control": "#3A4459",
        "text": "#ECEEF2",
        "text-2": "#C3C9D5",
        "caption": "#B7BFCC",
        "muted": "#8E98A9",
        "value": "#ECEEF2",
        "segment-active": "#2A3446",
        "warn": "#E8A33D",
        "warn-text": "#E8A33D",
        "warn-border": "#2A3446",
        "critical": "#F05A5A",
        "version-target": "#58D19B",
        "version-previous": "#7C93C3",
        "version-older": "#56607A",
        "version-none": "#3A4459",
    },
    "light": {
        "page": "#F3F4F7",
        "surface": "#FFFFFF",
        "track": "#E3E6EC",
        "border": "#DDE1E8",
        "control": "#C9CED8",
        "text": "#1A1D24",
        "text-2": "#3A3E48",
        "caption": "#4A4F5C",
        "muted": "#6E7483",
        "value": "#2B3245",
        "segment-active": "#E3E6EC",
        "warn": "#B7791F",
        "warn-text": "#B7791F",
        "warn-border": "#E8C98E",
        "critical": "#F05A5A",
        "version-target": "#1F9D63",
        "version-previous": "#5B74A8",
        "version-older": "#A3ABBA",
        "version-none": "#C9CED8",
    },
}

ALL_VERSIONS_OPTION = "Todas as versões"  # valor esperado por filter_inventory

STATUS_FILTERS: List[Tuple[str, str]] = [
    ("todos", "Todos"),
    ("atualizado", "Atualizados"),
    ("pendente", "Pendentes"),
    ("nunca", "Nunca reportou"),
    ("offline", "Offline"),
]

_STATUS_BASE = {
    "atualizado": "ATUALIZADO",
    "pendente": "PENDENTE",
    "nunca": "NUNCA REPORTOU",
}

_esc = html.escape


# ---------------------------------------------------------------------------
# Tema e estilos
# ---------------------------------------------------------------------------


def theme_mode() -> str:
    """'dark' ou 'light', conforme o tema ativo no Streamlit (padrão: escuro)."""
    try:
        mode = st.context.theme.type  # Streamlit >= 1.46
    except Exception:
        mode = None
    return mode if mode in THEMES else "dark"


def inject_styles() -> None:
    """Injeta static/styles.css + os tokens de cor como variáveis CSS.

    O CSS vem primeiro: o @import das fontes só vale como primeira regra.
    Os tokens ficam no .stApp em duas camadas: valores do modo detectado no
    servidor (st.context.theme) e, onde houver suporte, light-dark(), que
    segue o color-scheme que o próprio Streamlit aplica ao .stApp. Assim a
    troca de tema pelo menu reflete na hora, sem esperar um rerun.
    """
    mode = THEMES[theme_mode()]
    dark, light = THEMES["dark"], THEMES["light"]
    plain = ";".join(f"--{k}:{v}" for k, v in mode.items())
    adaptive = ";".join(f"--{k}:light-dark({light[k]},{dark[k]})" for k in dark)
    css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
    st.markdown(
        f"<style>{css}\n.stApp{{{plain}}}\n"
        f"@supports (color: light-dark(#000, #fff)) {{ .stApp{{{adaptive}}} }}</style>",
        unsafe_allow_html=True,
    )


@lru_cache(maxsize=None)
def _data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def page_icon() -> str:
    """Caminho do boneco Novacap para o page_icon do st.set_page_config."""
    return str(LOGO_MARK)


# ---------------------------------------------------------------------------
# Cores das versões — atribuição por papel, não por índice
# ---------------------------------------------------------------------------


ROLE_TARGET = "version-target"
ROLE_PREVIOUS = "version-previous"
ROLE_OLDER = "version-older"


def version_colors(target_build: str, versions: Iterable[Optional[str]]) -> Dict[str, str]:
    """Mapeia versão -> papel: alvo (verde), anterior (azul), demais (cinza).

    "Anterior" é a primeira versão, em ordem decrescente, que não é a alvo
    (cobre também o caso de rollback, em que a alvo não é a mais alta).
    O valor é o nome do token; no HTML vira var(--token), que acompanha o
    modo claro/escuro.
    """
    unique = sorted(
        {v for v in versions if v and v != "—"}, key=_version_key, reverse=True
    )
    colors: Dict[str, str] = {}
    if target_build:
        colors[target_build] = ROLE_TARGET
    previous_assigned = False
    for v in unique:
        if v == target_build:
            continue
        if not previous_assigned:
            colors[v] = ROLE_PREVIOUS
            previous_assigned = True
        else:
            colors[v] = ROLE_OLDER
    return colors


def _role(colors: Dict[str, str], version: Optional[str]) -> str:
    return colors.get(version or "", ROLE_OLDER)


def _color(colors: Dict[str, str], version: Optional[str]) -> str:
    """Cor CSS da versão (variável que segue o tema)."""
    return f"var(--{_role(colors, version)})"


def _color_hex(colors: Dict[str, str], version: Optional[str]) -> str:
    """Cor literal da versão no modo atual (para o Plotly)."""
    return THEMES[theme_mode()][_role(colors, version)]


def _ordered_for_display(versions: Iterable[str], target_build: str) -> List[str]:
    """Alvo primeiro, depois as demais em ordem decrescente (_version_key)."""
    rest = sorted({v for v in versions if v != target_build}, key=_version_key, reverse=True)
    return ([target_build] if target_build in set(versions) else []) + rest


def _short(version: str) -> str:
    return version[2:] if version.upper().startswith("V.") else version


def _pct_br(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + "%"


def _plural(n: int, singular: str, plural: str) -> str:
    return singular if abs(n) == 1 else plural


# ---------------------------------------------------------------------------
# Cabeçalho de marca + selos das fontes de dados
# ---------------------------------------------------------------------------


@dataclass
class SourceStatus:
    name: str
    ok: bool
    detail: str
    critical: bool = False  # True: indisponível em vermelho (fonte principal)


def bigquery_source(
    ok: bool, reference_date: Optional[date], fetched_at: Optional[datetime]
) -> SourceStatus:
    if ok and reference_date is not None and fetched_at is not None:
        detail = f"ref. {reference_date:%d/%m} · consulta {fetched_at:%H:%M}"
    elif ok and fetched_at is not None:
        detail = f"sem registros · consulta {fetched_at:%H:%M}"
    else:
        detail = "consulta falhou"
    return SourceStatus("BigQuery SMTR", ok, detail, critical=True)


def fleet_source(ok: bool, fetched_at: Optional[datetime]) -> SourceStatus:
    # A API da frota é consultada no mesmo ciclo do BigQuery (mesma TTL de
    # 24h, limpas juntas pelo botão Atualizar); o horário exibido é o do ciclo.
    if ok and fetched_at is not None:
        detail = f"{fetched_at:%d/%m %H:%M}"
    elif ok:
        detail = "consultada"
    else:
        detail = "sem marcador de offline"
    return SourceStatus("API da frota", ok, detail)


def mapping_source(ok: bool, roster_size: int) -> SourceStatus:
    if ok:
        detail = f"{roster_size} {_plural(roster_size, 'validador', 'validadores')}"
    else:
        detail = "só dados do BigQuery"
    return SourceStatus("Mapeamento", ok, detail)


def render_header(sources: Optional[List[SourceStatus]] = None) -> None:
    sources_html = ""
    if sources:
        items = []
        for s in sources:
            if s.ok:
                tone, state = "ok", "Operacional"
            else:
                tone = "critical" if s.critical else "warning"
                state = "Indisponível"
            items.append(
                '<div class="source">'
                f'<span class="source__dot source__dot--{tone}"></span>'
                '<div class="source__text">'
                f'<span class="source__name">{_esc(s.name)} · {state}</span>'
                f'<span class="source__detail">{_esc(s.detail)}</span>'
                "</div></div>"
            )
        sources_html = f'<div class="brandbar__sources">{"".join(items)}</div>'

    html_ = (
        '<div class="brandbar">'
        '<div class="brandbar__brand">'
        f'<img class="brandbar__mark" src="{_data_uri(LOGO_MARK)}" alt="Boneco Novacap">'
        f'<img class="brandbar__wordmark" src="{_data_uri(LOGO_WORDMARK)}" alt="NOVACAP">'
        "</div>"
        '<div class="brandbar__divider"></div>'
        '<div class="brandbar__titles">'
        '<span class="brandbar__title">Rollout de Validadores</span>'
        '<span class="brandbar__subtitle">Versões operacionais · consulta 1×/dia, '
        "updates ocorrem na madrugada</span>"
        "</div>"
        f"{sources_html}"
        "</div>"
    )
    st.markdown(html_, unsafe_allow_html=True)


def render_notice(title: str, body: str = "", tone: str = "warning") -> None:
    """Aviso neutro com ponto colorido (substitui o st.warning amarelo)."""
    body_html = f" {_esc(body)}" if body else ""
    st.markdown(
        f'<div class="notice notice--{tone}"><span class="notice__dot"></span>'
        f"<span><strong>{_esc(title)}</strong>{body_html}</span></div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Manchete de adoção + indicadores
# ---------------------------------------------------------------------------


def known_version_counts(
    state: Optional[Dict[str, dict]], today_status: pd.DataFrame
) -> Dict[str, int]:
    """Validadores por versão sobre o mesmo universo de compute_kpis.

    Com memória de última versão conhecida, conta o estado (mesmo denominador
    da adoção); sem ela, cai no snapshot da janela (build_today_status).
    """
    if state:
        counts: Dict[str, int] = {}
        for rec in state.values():
            v = rec.get("versao_app")
            if v:
                counts[v] = counts.get(v, 0) + 1
        return counts
    return {
        str(r.versao_app): int(r.validadores) for r in today_status.itertuples()
    }


def never_reported_count(inventory: pd.DataFrame) -> int:
    return int((inventory["build_atual"] == "—").sum())


def last_night_delta(history: pd.DataFrame, target_build: str) -> Optional[int]:
    """Variação da build alvo entre os dois últimos dias da série histórica."""
    if history.empty:
        return None
    dates = sorted(history["data"].unique())
    if len(dates) < 2:
        return None
    on_target = history[history["versao_app"] == target_build]
    by_day = on_target.groupby("data")["validadores"].sum()
    return int(by_day.get(dates[-1], 0)) - int(by_day.get(dates[-2], 0))


def render_overview(
    kpis: KPIs,
    counts: Dict[str, int],
    colors: Dict[str, str],
    never_reported: int,
    delta: Optional[int],
) -> None:
    target = kpis.target_build
    total = kpis.total_conhecido
    ordered = _ordered_for_display(list(counts), target)

    if delta is None:
        second_line = "com versão conhecida"
    elif delta == 0:
        second_line = "Última madrugada: sem atualizações"
    else:
        sign = "+" if delta > 0 else "−"
        second_line = (
            f"Última madrugada: {sign}{abs(delta)} "
            f"{_plural(delta, 'validador', 'validadores')}"
        )

    parts = "".join(
        f'<div class="segbar__part" style="flex:{counts[v]};background:{_color(colors, v)}"></div>'
        for v in ordered
        if counts.get(v, 0) > 0
    )
    legend = "".join(
        '<span class="legend-item">'
        f'<span class="legend-item__swatch" style="background:{_color(colors, v)}"></span>'
        f'<span class="mono">{_esc(_short(v))}</span>'
        f'{"alvo · " if v == target else "· "}{counts[v]}'
        "</span>"
        for v in ordered
    )
    if never_reported:
        legend += (
            '<span class="adoption__never">'
            f"+ {never_reported} "
            f"{_plural(never_reported, 'validador mapeado que nunca reportou', 'validadores mapeados que nunca reportaram')}"
            "</span>"
        )

    pill = (
        '<span class="pill">'
        f'<span class="pill__swatch" style="background:{_color(colors, target)}"></span>'
        f"{_esc(target or '—')}</span>"
    )
    adoption = (
        '<div class="card adoption">'
        '<div class="adoption__head">'
        '<span class="adoption__label">Adoção da build alvo</span>'
        f"{pill}</div>"
        '<div class="adoption__main">'
        f'<span class="adoption__value">{_pct_br(kpis.adocao_alvo_pct)}</span>'
        '<span class="adoption__detail">'
        f"<strong>{kpis.meta_atingida} de {total}</strong> validadores<br>{second_line}"
        "</span></div>"
        f'<div class="segbar">{parts}</div>'
        f'<div class="adoption__legend">{legend}</div>'
        "</div>"
    )

    indicators = [
        ("Frota operante", "Veículos que reportaram na janela de 3 dias", kpis.frota_operante),
        (
            "Pendentes de atualização",
            "Com versão conhecida abaixo da alvo",
            max(total - kpis.meta_atingida, 0),
        ),
        ("Versões ativas", "Na última versão conhecida de cada validador", kpis.variedade),
    ]
    indicators_html = "".join(
        '<div class="card indicator">'
        '<div class="indicator__text">'
        f'<span class="indicator__label">{label}</span>'
        f'<span class="indicator__desc">{desc}</span>'
        "</div>"
        f'<span class="indicator__value">{value}</span>'
        "</div>"
        for label, desc, value in indicators
    )
    st.markdown(
        f'<div class="overview">{adoption}<div class="indicators">{indicators_html}</div></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------


def _card_head(title: str, meta: str) -> str:
    return (
        '<div class="card__head">'
        f'<span class="card__title">{_esc(title)}</span>'
        f'<span class="card__meta">{_esc(meta)}</span>'
        "</div>"
    )


def render_history_card(
    history: pd.DataFrame, target_build: str, colors: Dict[str, str]
) -> None:
    """Histórico do rollout: barras empilhadas por dia, alvo na base."""
    tokens = THEMES[theme_mode()]
    head = _card_head("Histórico do rollout", "Últimos 3 dias · % na build alvo")
    with st.container(key="card_history"):
        if history.empty:
            st.markdown(
                head + '<div class="empty">Sem histórico na janela consultada.</div>',
                unsafe_allow_html=True,
            )
            return

        pivot = (
            history.pivot_table(
                index="data", columns="versao_app", values="validadores", aggfunc="sum"
            )
            .sort_index()
            .fillna(0)
        )
        labels = [pd.Timestamp(d).strftime("%d/%m") for d in pivot.index]
        stack = _ordered_for_display(list(pivot.columns), target_build)

        # O Plotly precisa de cores literais; o CSS abaixo as reaponta para os
        # tokens, para que a troca de tema pelo menu reflita sem rerun.
        overrides = "".join(
            f".st-key-card_history .barlayer .trace:nth-child({i}) .point path"
            f"{{fill:{_color(colors, v)} !important}}"
            for i, v in enumerate(stack, start=1)
        )
        st.markdown(f"<style>{overrides}</style>{head}", unsafe_allow_html=True)

        fig = go.Figure()
        for v in stack:  # primeiro trace = base da pilha
            fig.add_trace(
                go.Bar(
                    x=labels,
                    y=pivot[v].tolist(),
                    name=v,
                    width=0.5,
                    marker=dict(color=_color_hex(colors, v), line=dict(width=0)),
                    hovertemplate=f"{_esc(v)} · %{{x}} · %{{y:.0f}} validadores<extra></extra>",
                )
            )

        totals = pivot.sum(axis=1)
        on_target = pivot[target_build] if target_build in pivot.columns else totals * 0
        annotations = [
            dict(
                x=label,
                y=float(total),
                text=f"<b>{_pct_br(float(hit) / float(total) * 100.0) if total else '—'}</b>",
                showarrow=False,
                yanchor="bottom",
                yshift=6,
                font=dict(family=FONT_NUMBER, size=20, color=tokens["text"]),
            )
            for label, total, hit in zip(labels, totals.tolist(), on_target.tolist())
        ]
        y_max = float(totals.max()) if len(totals) else 1.0

        fig.update_layout(
            height=300,
            barmode="stack",
            bargap=0.45,
            showlegend=False,
            margin=dict(l=8, r=8, t=36, b=8),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family=FONT_UI, size=12, color=tokens["text"]),
            hoverlabel=dict(
                bgcolor=HEADER_BG,
                bordercolor=HEADER_BG,
                font=dict(family=FONT_MONO, size=11, color=HEADER_TEXT),
            ),
            annotations=annotations,
            xaxis=dict(
                type="category",
                showgrid=False,
                showline=False,
                zeroline=False,
                ticks="",
                tickfont=dict(family=FONT_MONO, size=11, color=tokens["caption"]),
                fixedrange=True,
            ),
            yaxis=dict(
                visible=False,
                range=[0, y_max * 1.16 if y_max else 1],
                fixedrange=True,
            ),
        )
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def render_distribution_card(
    today_status: pd.DataFrame,
    target_build: str,
    colors: Dict[str, str],
    reference: date,
) -> None:
    """Distribuição por versão (último estado conhecido na janela)."""
    counts = {str(r.versao_app): int(r.validadores) for r in today_status.itertuples()}
    total = sum(counts.values())
    rows = []
    for v in _ordered_for_display(list(counts), target_build):
        n = counts[v]
        pct = (n / total * 100.0) if total else 0.0
        color = _color(colors, v)
        rows.append(
            '<span class="dist__version">'
            f'<span class="swatch" style="background:{color}"></span>{_esc(_short(v))}</span>'
            '<div class="dist__track">'
            f'<div class="dist__fill" style="width:{pct:.2f}%;background:{color}"></div></div>'
            f'<span class="dist__count">{n}</span>'
            f'<span class="dist__pct">{_pct_br(pct)}</span>'
        )
    body = (
        f'<div class="dist__grid">{"".join(rows)}</div>'
        if rows
        else '<div class="empty">Nenhuma versão reportada na janela.</div>'
    )
    st.markdown(
        '<div class="card dist">'
        + _card_head("Distribuição por versão", f"Último estado conhecido · {reference:%d/%m/%Y}")
        + body
        + '<div class="card__foot">'
        "<span>Build alvo detectada automaticamente: a versão mais alta reportada no dia mais recente.</span>"
        "<span>Validadores offline contam com a última versão conhecida (versão não muda sem energia).</span>"
        "</div></div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Inventário
# ---------------------------------------------------------------------------


def _status_base(inventory: pd.DataFrame) -> pd.Series:
    return inventory["status_final"].str.split(" · ").str[0]


def _is_offline(inventory: pd.DataFrame) -> pd.Series:
    return inventory["status_final"].str.contains("· OFFLINE", regex=False)


def status_counts(inventory: pd.DataFrame) -> Dict[str, int]:
    """Contagens do filtro de status, sobre o inventário completo."""
    base = _status_base(inventory)
    counts = {key: int((base == value).sum()) for key, value in _STATUS_BASE.items()}
    counts["todos"] = len(inventory)
    counts["offline"] = int(_is_offline(inventory).sum())
    return counts


def filter_by_status(inventory: pd.DataFrame, status: Optional[str]) -> pd.DataFrame:
    """Offline é transversal: filtra quem tem o sufixo · OFFLINE."""
    if not status or status == "todos":
        return inventory
    if status == "offline":
        return inventory[_is_offline(inventory)]
    return inventory[_status_base(inventory) == _STATUS_BASE[status]]


def render_inventory_filters(
    counts: Dict[str, int], versions: List[str]
) -> Tuple[str, str, str]:
    """Barra do inventário: título, status, versão e busca."""
    labels = dict(STATUS_FILTERS)
    title_col, status_col, version_col, search_col = st.columns(
        [0.8, 4.2, 1.5, 1.9], vertical_alignment="center", gap="small"
    )
    with title_col:
        st.markdown('<span class="card__title">Inventário</span>', unsafe_allow_html=True)
    with status_col:
        status = st.segmented_control(
            "Status",
            options=[key for key, _ in STATUS_FILTERS],
            format_func=lambda key: f"{labels[key]} · {counts.get(key, 0)}",
            default="todos",
            key="status_filter",
            label_visibility="collapsed",
        )
    with version_col:
        version = st.selectbox(
            "Versão",
            [ALL_VERSIONS_OPTION] + versions,
            format_func=lambda v: "Versão: todas" if v == ALL_VERSIONS_OPTION else f"Versão: {v}",
            key="version_filter",
            label_visibility="collapsed",
        )
    with search_col:
        search = st.text_input(
            "Buscar",
            placeholder="Buscar ônibus ou serial…",
            key="search",
            label_visibility="collapsed",
        )
    return status or "todos", version, search


def _activity_versions(dots: str, window_versions: List[str]) -> List[Optional[str]]:
    """Traduz a string de atividade de metrics (um marcador por dia) em versões.

    Cada marcador é ACTIVITY_DOTS[i % 7], com i = posição da versão em
    _ordered_versions da janela; NO_ACTIVITY_DOT = não reportou. A UI só usa
    isso para pintar os blocos com a cor do papel da versão.
    """
    out: List[Optional[str]] = []
    for ch in dots:
        if ch == NO_ACTIVITY_DOT or ch not in ACTIVITY_DOTS:
            out.append(None)
            continue
        idx = ACTIVITY_DOTS.index(ch)
        out.append(window_versions[idx] if idx < len(window_versions) else None)
    return out


def _status_html(status: str) -> str:
    base, *extra = status.split(" · ")
    label, tone = {
        "ATUALIZADO": ("Atualizado", "target"),
        "PENDENTE": ("Pendente", "previous"),
        "NUNCA REPORTOU": ("Nunca reportou", "never"),
    }.get(base, (base.capitalize(), "never"))
    flag = (
        f'<span class="status__flag"> · {_esc(" · ".join(e.capitalize() for e in extra))}</span>'
        if extra
        else ""
    )
    return (
        f'<span class="status status--{tone}"><span class="status__dot"></span>'
        f"{label}{flag}</span>"
    )


def render_inventory_table(
    inventory: pd.DataFrame,
    total: int,
    df: pd.DataFrame,
    target_build: str,
    colors: Dict[str, str],
) -> None:
    days: List[date] = sorted(df["data"].unique())
    window_versions = _ordered_versions(_dedupe_max_version_per_day(df), target_build)
    days_label = " · ".join(f"{d:%d}" for d in days)

    if inventory.empty:
        body = '<div class="empty">Nenhum registro com os filtros atuais.</div>'
    else:
        rows = []
        for r in inventory.itertuples(index=False):
            build = str(r.build_atual)
            if build == "—":
                build_class = " inv__build--none"
            elif build == target_build:
                build_class = " inv__build--target"
            else:
                build_class = ""
            blocks = "".join(
                f'<span class="block" style="background:{_color(colors, v)}"></span>'
                if v
                else '<span class="block block--empty"></span>'
                for v in _activity_versions(str(r.atividade_recente), window_versions)
            )
            rows.append(
                "<tr>"
                f'<td class="inv__vehicle">{_esc(str(r.id_veiculo) or "—")}</td>'
                f'<td class="mono">{_esc(str(r.id_validador))}</td>'
                f'<td class="mono{build_class}">{_esc(build)}</td>'
                f'<td class="mono inv__ping">{_esc(str(r.ultimo_ping))}</td>'
                f'<td><span class="blocks">{blocks}</span></td>'
                f"<td>{_status_html(str(r.status_final))}</td>"
                "</tr>"
            )
        body = (
            '<div class="inv__scroll"><table class="inv">'
            "<thead><tr>"
            "<th>Veículo</th><th>Validador</th><th>Build atual</th><th>Último ping</th>"
            f'<th>Atividade <span class="inv__days">{days_label}</span></th>'
            "<th>Status</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )

    legend = (
        '<span class="legend-item"><span class="legend-block legend-block--target">'
        "</span>reportou na alvo</span>"
        '<span class="legend-item"><span class="legend-block legend-block--previous">'
        "</span>reportou em versão anterior</span>"
    )
    if ROLE_OLDER in colors.values():
        legend += (
            '<span class="legend-item"><span class="legend-block legend-block--older">'
            "</span>versões mais antigas</span>"
        )
    legend += (
        '<span class="legend-item"><span class="legend-block legend-block--empty">'
        "</span>não reportou</span>"
    )
    footer = (
        '<div class="inv__foot">'
        f"<span>Mostrando {len(inventory)} de {total} "
        f"{_plural(total, 'validador', 'validadores')}</span>"
        f"{legend}"
        '<span class="inv__source mono">rj-smtr.monitoramento.gps_validador · janela de 3 dias</span>'
        "</div>"
    )
    st.markdown(body + footer, unsafe_allow_html=True)
