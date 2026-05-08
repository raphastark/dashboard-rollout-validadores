from __future__ import annotations

import streamlit as st

from src.data import fetch_rollout_data
from src.metrics import (
    build_history_series,
    build_inventory_table,
    build_today_status,
    compute_kpis,
    detect_target_build,
    filter_inventory,
    latest_date,
)
from src.ui import (
    inject_styles,
    render_history_chart,
    render_inventory,
    render_kpi_cards,
    render_masthead,
    render_metabar,
    render_section_head,
    render_today_chart,
)

st.set_page_config(
    page_title="Dashboard de Versões Operacionais",
    page_icon="\U0001F68C",
    layout="wide",
    initial_sidebar_state="collapsed",
)

maintenance = st.secrets.get("app", {}).get("maintenance_mode", False)
if maintenance:
    st.title("🔧 Em manutenção")
    st.info("Este dashboard está temporariamente indisponível.")
    st.stop()
    
def main() -> None:
    inject_styles()

    header_left, header_right = st.columns([7, 5])
    with header_left:
        render_masthead()
    with header_right:
        st.markdown('<div class="search-pad"></div>', unsafe_allow_html=True)
        search = st.text_input(
            "Busca rápida",
            placeholder="Buscar por ônibus ou serial...",
            label_visibility="collapsed",
            key="search",
        )

    try:
        df, fetched_at = fetch_rollout_data()
    except Exception as exc:
        st.error(
            "Falha ao consultar o BigQuery. Verifique se .streamlit/secrets.toml "
            "está configurado e se a Service Account tem as roles necessárias."
        )
        st.exception(exc)
        st.stop()

    if df.empty:
        st.warning("Nenhum dado retornado pela query nos últimos dias.")
        st.stop()

    target_build = detect_target_build(df)
    kpis = compute_kpis(df, target_build)

    render_metabar(kpis, fetched_at)
    render_kpi_cards(kpis)

    chart_left, chart_right = st.columns(2, gap="medium")
    with chart_left:
        render_section_head("Histórico de Rollout", "Últimos 3 dias")
        render_history_chart(build_history_series(df))
    with chart_right:
        render_section_head("Status Hoje", latest_date(df).strftime("%d/%m/%Y"))
        render_today_chart(build_today_status(df), target_build)
        st.caption(
            f"Último estado conhecido por validador na janela consultada "
            f"(últimos 3 dias), até o dia {latest_date(df).strftime('%d/%m/%Y')}."
        )

    st.markdown('<div style="height: 16px"></div>', unsafe_allow_html=True)

    inv_left, inv_right = st.columns([3, 1.2])
    with inv_left:
        render_section_head(
            "Inventário Operacional Ativo",
            f"Status · {kpis.reference_date.strftime('%d/%m/%Y')}",
        )
    with inv_right:
        st.markdown('<div style="height: 6px"></div>', unsafe_allow_html=True)
        versions = ["Todas as versões"] + sorted(
            df["versao_app"].dropna().unique().tolist(), reverse=True
        )
        selected_version = st.selectbox(
            "Filtrar versão",
            versions,
            label_visibility="collapsed",
        )

    inventory = build_inventory_table(df, target_build)
    inventory = filter_inventory(inventory, selected_version, search)

    if inventory.empty:
        st.info("Nenhum registro com os filtros atuais.")
    else:
        render_inventory(inventory)


if __name__ == "__main__":
    main()
