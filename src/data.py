from __future__ import annotations

import csv
import io
import threading
import warnings
from datetime import date, datetime
from typing import Dict, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
import requests
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
FLEET_API_TIMEOUT = 15
FLEET_TRUTH_TTL = 24 * 60 * 60
SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")

# Roster oficial da frota: planilha "mapeamento dos validadores" publicada
# como CSV (a mesma usada pelo dashboard de temperatura). Uso ADITIVO: só
# adiciona validadores que nunca reportaram; nunca remove quem o BigQuery vê.
MAPPING_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vTTVotmQMdtPhZ610EXnwE89MHFdWu31XpQVcU1XEapXiW1F9dUy_"
    "b7C4cyJhBTdGj3YdKLzcpIxx0i/pub?output=csv"
)

# Memória "última versão conhecida por validador": vive no próprio processo
# do Streamlit (@st.cache_resource) e é mesclada com a janela diária. Como a
# versão de um validador sem energia não muda (não existe OTA desligado),
# quem para de pingar — veículo em manutenção pesada — mantém a última versão
# em vez de sumir do dashboard ao sair da janela de 3 dias.
#
# Volátil por design: um redeploy reseta o acúmulo, que recomeça da janela do
# dia. Não é cache de consulta — o botão "Atualizar" NÃO deve limpá-la.
#
# Serial fora do roster que para de pingar é equipamento trocado/enviado à
# Jaé: sai da memória após 7 dias sem ping (e a janela de 3 dias ainda o
# mostra por mais alguns). Margem curta evita acúmulo de "fantasmas"
# PENDENTE distorcendo a adoção — trocas são frequentes (~26 em 4 meses).
STATE_PRUNE_DAYS = 7


@st.cache_resource(show_spinner=False)
def get_last_known_store() -> Dict[str, dict]:
    """Estado acumulado por id_validador: {versao_app, data_ultimo_ping, ...}."""
    return {}


@st.cache_resource(show_spinner=False)
def get_last_known_lock() -> threading.Lock:
    """Lock compartilhado entre sessões para o ciclo ler-mesclar-escrever do store.

    `get_last_known_store` é compartilhado por todas as sessões do Streamlit
    no mesmo processo; sem essa serialização, reruns concorrentes podem
    intercalar `clear()`/`update()` e perder validadores offline lembrados.
    """
    return threading.Lock()

ROLLOUT_QUERY = """
SELECT DISTINCT
    data,
    id_veiculo,
    id_validador,
    versao_app
FROM `rj-smtr.monitoramento.gps_validador`
WHERE id_operadora = @id_operadora
  AND data BETWEEN DATE_SUB(CURRENT_DATE('America/Sao_Paulo'), INTERVAL @window_days DAY) AND CURRENT_DATE('America/Sao_Paulo')
  AND (id_veiculo LIKE '515%' OR id_veiculo LIKE '516%')
  AND datetime_gps >= CAST(DATE_SUB(CURRENT_DATE('America/Sao_Paulo'), INTERVAL @window_days DAY) AS DATETIME)
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
    fetched_at = datetime.now(SAO_PAULO_TZ)
    return df, fetched_at


@st.cache_data(ttl=FLEET_TRUTH_TTL, show_spinner="Consultando frota em tempo real...")
def fetch_fleet_truth() -> frozenset[str]:
    """Conjunto de id_validador instalados na frota agora.

    A API devolve, no instante da chamada, os validadores que estão transmitindo —
    quem estiver momentaneamente offline pode ficar de fora. O resultado é usado
    para filtrar a base do BigQuery e descartar validadores já removidos da frota.
    """
    url = st.secrets.get("fleet_api", {}).get("url")
    if not url:
        raise RuntimeError(
            "URL da API da frota não configurada. Defina [fleet_api].url em "
            ".streamlit/secrets.toml (ver secrets.toml.example)."
        )
    resp = requests.get(url, timeout=FLEET_API_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    return frozenset(
        str(item["id_validador"])
        for item in payload
        if item.get("id_validador") is not None
    )


@st.cache_data(ttl=FLEET_TRUTH_TTL, show_spinner="Consultando mapeamento da frota...")
def fetch_fleet_mapping() -> pd.DataFrame:
    """Roster da frota a partir da planilha de mapeamento publicada como CSV.

    Retorna DataFrame com colunas id_veiculo e id_validador (2 linhas por
    veículo). Falha com RuntimeError se o formato mudar — o chamador degrada
    para o comportamento só-BigQuery.
    """
    resp = requests.get(MAPPING_CSV_URL, timeout=FLEET_API_TIMEOUT)
    resp.raise_for_status()
    rows = [
        r for r in csv.reader(io.StringIO(resp.content.decode("utf-8")))
        if any(c.strip() for c in r)
    ]
    if len(rows) < 2 or len(rows[0]) < 3:
        raise RuntimeError("Planilha de mapeamento com formato inesperado.")
    records = []
    for r in rows[1:]:
        if len(r) < 3:
            # Linha parcialmente preenchida (planilha editada manualmente):
            # ignora em vez de derrubar o roster inteiro com IndexError.
            continue
        veiculo = r[0].strip()
        for val in (r[1].strip(), r[2].strip()):
            if veiculo and val:
                records.append({"id_veiculo": veiculo, "id_validador": val})
    mapping = pd.DataFrame(records, columns=["id_veiculo", "id_validador"])
    if mapping.empty or mapping["id_validador"].duplicated().any():
        raise RuntimeError(
            "Planilha de mapeamento vazia ou com validadores duplicados."
        )
    return mapping


def today_sp() -> date:
    """Data de referência 'agora' no fuso do dashboard."""
    return datetime.now(SAO_PAULO_TZ).date()


def clear_all_caches() -> None:
    # NOTA: o store de última versão conhecida (get_last_known_store) é
    # memória acumulada, não cache de consulta — não deve ser limpo aqui.
    fetch_rollout_data.clear()
    fetch_fleet_truth.clear()
    fetch_fleet_mapping.clear()
