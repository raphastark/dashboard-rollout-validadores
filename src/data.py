from __future__ import annotations

import warnings
from datetime import datetime
from typing import Tuple

import pandas as pd
import streamlit as st
from google.cloud import bigquery
from google.oauth2 import service_account

# A lib opcional google-cloud-bigquery-storage só vale a pena para queries gigantes (GB+).
# Para o nosso volume (~600 linhas, 1x/dia), o caminho REST é instantâneo. Silencia o aviso.
warnings.filterwarnings(
    "ignore",
    message="BigQuery Storage module not found",
    category=UserWarning,
)

PROJECT_ID = "rj-smtr"
ID_OPERADORA = "220515009"
VEHICLE_PREFIXES = ("515", "516")
DEFAULT_WINDOW_DAYS = 2

ROLLOUT_QUERY = """
SELECT DISTINCT
    data,
    id_veiculo,
    id_validador,
    versao_app
FROM `rj-smtr.monitoramento.gps_validador`
WHERE id_operadora = @id_operadora
  AND data BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL @window_days DAY) AND CURRENT_DATE()
  AND (id_veiculo LIKE '515%' OR id_veiculo LIKE '516%')
  AND datetime_gps >= CAST(DATE_SUB(CURRENT_DATE(), INTERVAL @window_days DAY) AS DATETIME)
ORDER BY id_veiculo ASC, id_validador ASC
"""


@st.cache_resource(show_spinner=False)
def get_bq_client() -> bigquery.Client:
    if "gcp_service_account" not in st.secrets:
        raise RuntimeError(
            "Credenciais não encontradas. Crie .streamlit/secrets.toml a partir do "
            "secrets.toml.example com a chave [gcp_service_account]."
        )
    creds = service_account.Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"])
    )
    return bigquery.Client(credentials=creds, project=creds.project_id)


@st.cache_data(ttl=86400, show_spinner="Consultando BigQuery...")
def fetch_rollout_data(window_days: int = DEFAULT_WINDOW_DAYS) -> Tuple[pd.DataFrame, datetime]:
    client = get_bq_client()
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("id_operadora", "STRING", ID_OPERADORA),
            bigquery.ScalarQueryParameter("window_days", "INT64", window_days),
        ]
    )
    df = client.query(ROLLOUT_QUERY, job_config=job_config).to_dataframe()
    df["data"] = pd.to_datetime(df["data"]).dt.date
    df["id_veiculo"] = df["id_veiculo"].astype(str)
    df["id_validador"] = df["id_validador"].astype(str)
    df["versao_app"] = df["versao_app"].astype(str)
    fetched_at = datetime.now()
    return df, fetched_at


def clear_cache() -> None:
    fetch_rollout_data.clear()
