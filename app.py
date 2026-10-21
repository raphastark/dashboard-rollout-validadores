from __future__ import annotations

import streamlit as st

from src.data import (
    STATE_PRUNE_DAYS,
    clear_all_caches,
    fetch_fleet_mapping,
    fetch_fleet_truth,
    fetch_rollout_data,
    get_last_known_lock,
    get_last_known_store,
    today_sp,
)
from src.metrics import (
    available_versions,
    build_history_series,
    build_inventory_table,
    build_today_status,
    compute_kpis,
    detect_target_build,
    filter_inventory,
    latest_date,
    merge_last_known_state,
)
from src.ui import (
    bigquery_source,
    filter_by_status,
    fleet_source,
    inject_styles,
    known_version_counts,
    last_night_upgrades,
    mapping_source,
    never_reported_count,
    page_icon,
    render_distribution_card,
    render_header,
    render_history_card,
    render_inventory_filters,
    render_inventory_table,
    render_notice,
    render_overview,
    status_counts,
    version_colors,
)

st.set_page_config(
    page_title="Rollout de Validadores",
    page_icon=page_icon(),
    layout="wide",
    initial_sidebar_state="collapsed",
)


def main() -> None:
    inject_styles()

    maintenance = st.secrets.get("app", {}).get("maintenance_mode", False)
    if maintenance:
        render_header()
        render_notice(
            "Painel em manutenção.",
            "Os dados voltam a ser exibidos assim que a manutenção terminar.",
            tone="neutral",
        )
        st.stop()

    # --- Fontes de dados (mesmos try/except de antes; o resultado alimenta
    # os selos do cabeçalho e os avisos). ---
    bq_error: Exception | None = None
    try:
        df, fetched_at = fetch_rollout_data()
    except Exception as exc:
        df, fetched_at, bq_error = None, None, exc

    try:
        roster = fetch_fleet_mapping()
    except Exception:
        roster = None

    fleet_empty = False
    try:
        fleet_truth = fetch_fleet_truth()
    except Exception:
        fleet_truth = None
    if fleet_truth is not None and not fleet_truth:
        fleet_empty = True
        fleet_truth = None

    has_data = df is not None and not df.empty
    render_header(
        [
            bigquery_source(
                bq_error is None,
                latest_date(df) if has_data else None,
                fetched_at,
            ),
            fleet_source(fleet_truth is not None, fetched_at),
            mapping_source(roster is not None, len(roster) if roster is not None else 0),
        ]
    )

    # on_click roda ANTES do rerun disparado pelo clique: os caches são
    # limpos antes das consultas acima, então o rerun já busca dados novos
    # uma única vez (sem st.rerun extra, sem consulta dupla ao BigQuery).
    with st.container(key="refresh_row"):
        st.button(
            "Atualizar",
            key="refresh",
            help="Atualizar dados agora (BigQuery + API da frota)",
            on_click=clear_all_caches,
        )

    if bq_error is not None:
        st.error(
            "Falha ao consultar o BigQuery. Verifique se .streamlit/secrets.toml "
            "está configurado e se a Service Account tem as roles necessárias."
        )
        st.exception(bq_error)
        st.stop()

    if not has_data:
        render_notice(
            "Nenhum dado retornado.",
            "A consulta ao BigQuery não trouxe registros nos últimos dias.",
        )
        st.stop()

    if roster is None:
        render_notice(
            "Planilha de mapeamento indisponível.",
            "Exibindo apenas o que o BigQuery reporta.",
        )
    if fleet_empty:
        render_notice(
            "API da frota retornou vazia.",
            "O inventário segue sem o marcador de offline.",
        )
    elif fleet_truth is None:
        render_notice(
            "API da frota indisponível.",
            "O inventário segue sem o marcador de offline.",
        )

    # Última versão conhecida por validador: memória do processo Streamlit.
    # A janela diária é mesclada ao acúmulo; quem para de pingar mantém a
    # versão anterior (não existe OTA sem energia).
    store = get_last_known_store()
    with get_last_known_lock():
        state = merge_last_known_state(store, df, roster, today_sp(), STATE_PRUNE_DAYS)
        store.clear()
        store.update(state)

    target_build = detect_target_build(df)
    kpis = compute_kpis(df, target_build, state=state)
    inventory = build_inventory_table(
        df, target_build, fleet_truth=fleet_truth, state=state, roster=roster
    )
    history = build_history_series(df)
    today_status = build_today_status(df)

    colors = version_colors(
        target_build,
        [rec.get("versao_app") for rec in state.values()]
        + df["versao_app"].tolist()
        + inventory["build_atual"].tolist(),
    )

    counts = known_version_counts(state, today_status)
    render_overview(
        kpis,
        counts,
        colors,
        never_reported_count(inventory),
        last_night_upgrades(df, target_build),
    )

    chart_left, chart_right = st.columns(2, gap="small")
    with chart_left:
        render_history_card(history, target_build, colors)
    with chart_right:
        render_distribution_card(counts, target_build, colors, latest_date(df))

    with st.container(key="inventory_card"):
        status, version, search = render_inventory_filters(
            status_counts(inventory), available_versions(inventory)
        )
        shown = filter_by_status(filter_inventory(inventory, version, search), status)
        render_inventory_table(shown, len(inventory), df, target_build, colors)


if __name__ == "__main__":
    main()
