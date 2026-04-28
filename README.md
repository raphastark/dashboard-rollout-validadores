# Dashboard de Rollout de Versões — Validadores

Dashboard em Streamlit que acompanha o rollout das versões do app dos validadores
embarcados nos veículos. Substitui o fluxo anterior baseado em Google Sheets +
Gemini, consultando direto o BigQuery (`rj-smtr.monitoramento.gps_validador`).

## Stack

- Streamlit
- google-cloud-bigquery (Service Account)
- Pandas + Plotly

## Setup

### 1. Criar a Service Account no GCP

1. Console GCP → **IAM & Admin → Service Accounts**.
2. Crie uma SA chamada `dashboard-rollout` (ou similar).
3. Conceda as roles:
   - `BigQuery Data Viewer` no dataset `rj-smtr.monitoramento` (ou no projeto inteiro se não tiver controle granular)
   - `BigQuery Job User` no projeto `rj-smtr`
4. Em **Keys → Add Key → Create new key → JSON** baixe o arquivo.

### 2. Configurar o secrets.toml

Crie uma cópia do template `.streamlit/secrets.toml.example` chamada
`.streamlit/secrets.toml` (sem o `.example`). Três formas de fazer:

- **Explorador do Windows:** copie o arquivo, cole na mesma pasta e renomeie.
- **PowerShell** (terminal padrão do Windows):
  ```powershell
  copy .streamlit\secrets.toml.example .streamlit\secrets.toml
  ```
- **Git Bash / Linux / Mac:**
  ```bash
  cp .streamlit/secrets.toml.example .streamlit/secrets.toml
  ```

Abra `.streamlit/secrets.toml` no VS Code e cole os campos do JSON da Service
Account. Atenção à `private_key`: precisa preservar os `\n` literais entre as
linhas (não troque por quebras reais).

> O arquivo `secrets.toml` está no `.gitignore` — ele nunca vai pro GitHub.
> O `.example` fica no repo só como template do formato.

### 3. Ambiente Python

```bash
python -m venv venv
venv\Scripts\activate         # Windows
# source venv/bin/activate    # Linux/Mac
pip install -r requirements.txt
```

### 4. Rodar local

```bash
streamlit run app.py
```

Acesse http://localhost:8501.

## Uso

- **KPIs do topo:** frota operante (veículos reportando hoje), % de adoção da build alvo, número de versões ativas e quantidade de validadores já atualizados.
- **Build alvo:** detectada automaticamente como a versão mais alta presente no dia mais recente.
- **Histórico de Rollout:** linha por versão ao longo dos últimos 3 dias.
- **Status Hoje:** distribuição dos validadores por versão no dia mais recente.
- **Inventário:** tabela com 3 bolinhas de atividade (uma por dia): 🟢 reportou na build alvo, 🟡 reportou em build anterior, ⚪ não reportou.
- **Filtros:** dropdown de versão e busca por `id_veiculo` ou `id_validador`.
- **Atualização dos dados:** a query no BigQuery roda no máximo 1x a cada 24h (cache via `@st.cache_data(ttl=86400)`). Como os upgrades dos validadores são feitos pela empresa de bilhetagem na madrugada, não há ganho em consultar com mais frequência — e evita custo desnecessário no BigQuery.

## Deploy no Streamlit Community Cloud

1. `git init` e suba o repo no GitHub (o `.gitignore` já protege o `secrets.toml`).
2. https://share.streamlit.io → **New app** apontando para o repo.
3. Em **Advanced settings → Secrets**, cole o conteúdo do seu `secrets.toml`.
4. Deploy. Compartilhe a URL com a equipe.

## Estrutura

```
app.py                    # entry-point Streamlit
src/
  data.py                 # cliente BQ + query + cache
  metrics.py              # cálculo dos KPIs e tabelas
  ui.py                   # componentes visuais
.streamlit/
  config.toml             # tema
  secrets.toml.example    # template da Service Account
requirements.txt
```
# dashboard-rollout-validadores
