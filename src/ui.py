from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .metrics import KPIs, _version_key

PALETTE = [
    "#0F9D70",
    "#2563EB",
    "#C2680A",
    "#6D28D9",
    "#DC2626",
    "#EA580C",
    "#0F766E",
]

CHART_FONT = "Geist, system-ui, sans-serif"
CHART_MONO = "JetBrains Mono, monospace"
CHART_INK = "#0E1014"
CHART_MUTED = "#9CA3AF"
CHART_GRID = "#EDEEE8"

LOGO_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h3l2-7 4 14 2-9 2 5 2-3h3"/></svg>'

KPI_ICONS = {
    "bus": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6v6"/><path d="M15 6v6"/><path d="M2 12h19.6"/><path d="M18 18h3s.5-1.7.8-2.8c.1-.4.2-.8.2-1.2 0-.4-.1-.8-.2-1.2l-1.4-5C20.1 6.8 19.1 6 18 6H4a2 2 0 0 0-2 2v10h3"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/></svg>',
    "target": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>',
    "layers": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>',
    "trending": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>',
}


def inject_styles() -> None:
    """Carrega static/styles.css e injeta uma vez por sessão."""
    css_path = Path(__file__).resolve().parent.parent / "static" / "styles.css"
    css = css_path.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_masthead() -> None:
    html = (
        '<div class="masthead">'
        f'<div class="masthead__logo">{LOGO_SVG}</div>'
        '<div class="masthead__textwrap">'
        '<div class="masthead__eyebrow">SMTR · Rollout · Ao Vivo</div>'
        '<h1 class="masthead__title">Dashboard de Versões Operacionais</h1>'
        '</div>'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_metabar(kpis: KPIs, fetched_at: datetime) -> None:
    ref = kpis.reference_date.strftime("%d/%m/%Y")
    upd = fetched_at.strftime("%d/%m %H:%M")
    target = kpis.target_build or "—"
    html = (
        '<div class="metabar">'
        '<div class="metabar__pill">'
        '<span class="metabar__label">Referência</span>'
        f'<span class="metabar__value">{ref}</span>'
        '</div>'
        '<div class="metabar__pill">'
        '<span class="metabar__label">Atualizado</span>'
        f'<span class="metabar__value">{upd}</span>'
        '</div>'
        '<div class="metabar__pill metabar__pill--accent">'
        '<span class="metabar__label">Build alvo</span>'
        f'<span class="metabar__value">{target}</span>'
        '</div>'
        '<span class="metabar__note">Consulta 1×/dia · updates dos validadores ocorrem na madrugada</span>'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_section_head(title: str, caption: str | None = None) -> None:
    cap_html = f'<span class="section-head__caption">{caption}</span>' if caption else ""
    html = (
        '<div class="section-head">'
        f'<h2 class="section-head__title">{title}</h2>'
        f'{cap_html}'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def render_kpi_cards(kpis: KPIs) -> None:
    cards = [
        ("blue", "bus", "Frota Operante", str(kpis.frota_operante), "Reportando hoje"),
        ("green", "target", "Adoção Alvo", f"{kpis.adocao_alvo_pct:.1f}%", f"Build {kpis.target_build}"),
        ("amber", "layers", "Variedade", str(kpis.variedade), "Versões ativas"),
        ("purple", "trending", "Meta Atingida", str(kpis.meta_atingida), "Unidades atualizadas"),
    ]
    cards_html = "".join(
        '<div class="kpi kpi--' + color + '">'
        '<div class="kpi__head">'
        f'<div class="kpi__icon">{KPI_ICONS[icon]}</div>'
        f'<span class="kpi__chip">{chip}</span>'
        '</div>'
        f'<div class="kpi__value">{value}</div>'
        f'<div class="kpi__caption">{caption}</div>'
        '</div>'
        for color, icon, chip, value, caption in cards
    )
    st.markdown(f'<div class="kpi-grid">{cards_html}</div>', unsafe_allow_html=True)


def _color_for(version: str, ordered_versions: list[str]) -> str:
    if version in ordered_versions:
        idx = ordered_versions.index(version)
        return PALETTE[idx % len(PALETTE)]
    return PALETTE[0]


def _base_layout(height: int = 340) -> dict:
    return dict(
        height=height,
        margin=dict(l=22, r=44, t=54, b=48),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=CHART_FONT, color=CHART_INK, size=12),
        hoverlabel=dict(
            bgcolor=CHART_INK,
            font_color="#F6F7F2",
            font_family=CHART_MONO,
            font_size=11,
            bordercolor=CHART_INK,
        ),
    )


def render_history_chart(history: pd.DataFrame) -> None:
    versions_sorted = sorted(history["versao_app"].unique(), key=_version_key, reverse=True)
    unique_dates = sorted(pd.to_datetime(history["data"]).unique())
    fig = go.Figure()
    for v in versions_sorted:
        sub = history[history["versao_app"] == v].sort_values("data")
        color = _color_for(v, versions_sorted)
        short = v.replace("V.", "")
        fig.add_trace(
            go.Scatter(
                x=sub["data"],
                y=sub["validadores"],
                mode="lines",
                name=short,
                line=dict(color=color, width=2.5, shape="spline", smoothing=0.4),
                legendgroup=v,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=sub["data"],
                y=sub["validadores"],
                mode="markers",
                marker=dict(size=10, line=dict(color="#FFFFFF", width=2), color=color),
                legendgroup=v,
                showlegend=False,
                hovertemplate=f"<b>{v}</b><br>%{{x|%d/%m/%Y}} · %{{y}} validadores<extra></extra>",
            )
        )
    layout = _base_layout(height=340)
   layout.update(
        legend=dict(
            orientation="h",
            yanchor="top", y=-0.15,      # <-- Modificado: Ancora no topo, posicionado abaixo do eixo X
            xanchor="center", x=0.5,
            font=dict(family=CHART_MONO, size=10.5, color=CHART_INK),
            bgcolor="rgba(0,0,0,0)",
        ),
        xaxis=dict(
            showgrid=False,
            tickformat="%d/%m",
            tickfont=dict(family=CHART_MONO, size=10.5, color=CHART_MUTED),
            linecolor=CHART_GRID,
            showline=True,
            ticks="outside",
            ticklen=4,
            tickcolor=CHART_GRID,
            tickmode="array",
            tickvals=unique_dates,
            automargin=True,
        ),
        yaxis=dict(
            gridcolor=CHART_GRID,
            tickfont=dict(family=CHART_MONO, size=10.5, color=CHART_MUTED),
            zeroline=False,
            automargin=True,
        ),
    )
    fig.update_layout(**layout)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def render_today_chart(today: pd.DataFrame, target_build: str) -> None:
    versions_sorted = sorted(today["versao_app"].unique(), key=_version_key, reverse=True)
    today = today.set_index("versao_app").loc[versions_sorted].reset_index()
    today["display_y"] = today["versao_app"].str.replace("V.", "", regex=False)

    colors = ["#0F9D70" if v == target_build else "#2563EB" for v in today["versao_app"]]
    fig = go.Figure(
        go.Bar(
            x=today["validadores"],
            y=today["display_y"],
            orientation="h",
            marker=dict(
                color=colors,
                line=dict(color=colors, width=0),
            ),
            text=today["validadores"],
            textposition="outside",
            textfont=dict(family=CHART_MONO, size=11, color=CHART_INK),
            customdata=today["versao_app"],
            hovertemplate="<b>%{customdata}</b><br>%{x} validadores<extra></extra>",
            width=0.55,
        )
    )
    layout = _base_layout(height=340)
    layout.update(
        xaxis=dict(
            showgrid=True,
            gridcolor=CHART_GRID,
            tickfont=dict(family=CHART_MONO, size=10.5, color=CHART_MUTED),
            zeroline=False,
            automargin=True,
        ),
        yaxis=dict(
            autorange="reversed",
            tickfont=dict(family=CHART_MONO, size=11, color=CHART_INK),
            showgrid=False,
            automargin=True,
        ),
        showlegend=False,
        bargap=0.35,
    )
    fig.update_layout(**layout)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def render_inventory(inventory: pd.DataFrame) -> None:
    display = inventory.rename(
        columns={
            "id_veiculo": "Veículo",
            "id_validador": "ID Validador",
            "build_atual": "Build Atual",
            "atividade_recente": "Atividade Recente",
            "status_final": "Status Final",
        }
    )
    display["Veículo"] = "#" + display["Veículo"].astype(str)
    display["Status Final"] = display["Status Final"].apply(
        lambda v: "● Atualizado" if v == "ATUALIZADO" else "○ Pendente"
    )
    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_config={
            "Veículo": st.column_config.TextColumn(width="small"),
            "ID Validador": st.column_config.TextColumn(width="medium"),
            "Build Atual": st.column_config.TextColumn(width="small"),
            "Atividade Recente": st.column_config.TextColumn(width="medium"),
            "Status Final": st.column_config.TextColumn(width="small"),
        },
    )
