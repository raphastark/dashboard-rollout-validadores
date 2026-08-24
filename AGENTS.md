# AGENTS.md

Dashboard Streamlit que acompanha o rollout das versões do app dos validadores
embarcados nos veículos (SMTR). Consulta direto o BigQuery
(`rj-smtr.monitoramento.gps_validador`) via Service Account — substituiu o fluxo
antigo de Google Sheets + Gemini. UI e termos de domínio em português.

## Comandos

```bash
# Ambiente — ATENÇÃO: o venv/ local foi criado antes de uma formatação recente
# da máquina e aponta para um perfil de usuário que não existe mais
# ("Raphael Almeida"). O sistema usa o launcher `py` (Python 3.12), que já
# tem os requirements instalados:
py -m pip install -r requirements.txt

# Rodar local (http://localhost:8501)
py -m streamlit run app.py
```

Não há testes, lint nem typecheck configurados. Verificação prática = rodar o
app. Os dados exigem `.streamlit/secrets.toml` válido (ver Gotchas). Há
`.devcontainer/` para setup no VS Code / GitHub Codespaces.

## Arquitetura

Fluxo em camadas, uma responsabilidade por módulo — manter a separação:

- `app.py` — entry-point: page config, layout (`st.columns`) e orquestração.
  Não calcula nada nem renderiza componente complexo aqui. Contém o modo de
  manutenção (secret `[app].maintenance_mode`) e o botão "Atualizar"
  (`clear_all_caches()` + `st.rerun`).
- `src/data.py` — acesso a dados: BigQuery (`fetch_rollout_data`), API da
  frota em tempo real (`fetch_fleet_truth`, lê `[fleet_api].url`), roster da
  planilha de mapeamento (`fetch_fleet_mapping`, CSV público, uso ADITIVO:
  só adiciona quem nunca reportou, nunca remove quem pinga) e memória de
  última versão conhecida (`get_last_known_store`, `@st.cache_resource` +
  `STATE_PRUNE_DAYS`). Query parametrizada, credenciais e cache
  (`@st.cache_resource` no client, `@st.cache_data` nos dados, TTL 24h).
  Constantes (PROJECT_ID, ID_OPERADORA, prefixos de veículo, janela de dias,
  fuso) vivem aqui.
- `src/metrics.py` — transformações puras de pandas: KPIs (adoção sobre o
  estado conhecido), série histórica (snapshot _as-of_ por validador), merge
  incremental do estado (`merge_last_known_state`), inventário (universo =
  roster < estado < janela; marcadores `· OFFLINE` / `· OFFLINE HÁ N DIAS` /
  `NUNCA REPORTOU`) e filtro. **Não importar `streamlit` aqui** — é testável
  puro.
- `src/ui.py` — componentes visuais: HTML/CSS injetado, cards, gráficos
  Plotly. Carrega `static/styles.css` via `inject_styles()`.
- `static/styles.css` — todo o estilo custom (classes BEM: `kpi__value`,
  `masthead__title`...). Preferir CSS aqui a inline no Python.
- `.streamlit/` — `config.toml` (tema claro, verde #0F9D70) e
  `secrets.toml.example` (templates das seções `[gcp_service_account]` e
  `[fleet_api]`).

## Convenções

- `from __future__ import annotations` na primeira linha de todo módulo; type
  hints em todas as funções (usar `Tuple`/`List` de `typing` como o código
  atual).
- Versões seguem o formato `V.X.Y.Z` — ordenar sempre via `_version_key`
  (`src/metrics.py`), nunca por string.
- Identificadores de código em inglês; campos de domínio/KPIs podem ficar em
  português (`frota_operante`), como o restante do repo.
- Fontes dos gráficos: Geist (texto) e JetBrains Mono (números/eixos);
  cores centrais no `PALETTE` de `src/ui.py` e no tema do `config.toml`.

## Gotchas

- **`secrets.toml` é gitignored e nunca deve ser commitado.** Template:
  `.streamlit/secrets.toml.example` com as seções `[gcp_service_account]`
  (obrigatória) e `[fleet_api]` (obrigatória p/ API da frota); `[app]` com
  `maintenance_mode` é opcional. A `private_key` precisa manter os `\n`
  literais (não trocar por quebras reais).
- **O cache de 24h (`ttl=86400`) é intencional:** upgrades de validador ocorrem
  na madrugada, então consultas mais frequentes só geram custo no BigQuery.
  Não reduzir a TTL sem justificativa — o botão "Atualizar" já permite
  forçar refresh manualmente.
- **A API da frota é auxiliar, não filtro:** serve só para marcar `· OFFLINE`
  no inventário. Antes era filtro duro e excluía validadores offline das
  métricas (bug documentado no changelog de 2026-05-31) — não reintroduzir.
  Se a API falha, o app degrada graciosamente (warning + segue sem o marcador).
- **A tabela `gps_validador` é GIGANTE e compartilhada:** ~7,7 bilhões de
  linhas / 1,89 TB, particionada por dia no campo `data` (filtro de partição
  obrigatório), com pings de TODOS os validadores do Rio a cada ~30s. O custo
  é por partição varrida (~1,8 GB/dia), MESMO com filtros por id_validador.
  **Nunca ampliar a janela da query** — 120 dias ≈ ≥60 GB por consulta. A
  janela de 3 dias, 1x/dia, é o teto aceito; estado histórico deve ser
  acumulado incrementalmente, nunca consultado para trás.
- **Domínio:** ping com id_veiculo 515/516 significa que o validador está
  fisicamente instalado no veículo; validador ligado fora do veículo reporta
  id_veiculo 99999 (já excluído pelos prefixos da query). Versão de validador
  sem energia não muda (não existe OTA desligado).
- **Memória de última versão conhecida:** `get_last_known_store()`
  (`@st.cache_resource`) acumula a versão + último ping por validador no
  processo do Streamlit — funciona igual no local e no Community Cloud,
  sobrevive ao ciclo de cache diário e entre sessões; um redeploy reseta o
  acúmulo (aceito por design: escopo é "daqui para a frente"). NÃO limpar no
  botão "Atualizar" (é memória, não cache de consulta) e NUNCA re-consultar
  histórico no BQ para reconstruí-la. A build alvo continua detectada apenas
  pela janela fresca (proteção contra rollback da Jaé). Entradas fora do
  roster sem ping há >7 dias são podadas (serial trocado = sai rápido;
  trocas são frequentes — não deixar fantasmas PENDENTE inflando o
  denominador da adoção).
- **Fuso horário:** query e `fetched_at` usam `America/Sao_Paulo`
  (`CURRENT_DATE('America/Sao_Paulo')`, `ZoneInfo`) — não usar datas UTC.
- **Snapshot as-of:** `build_atual` e o histórico usam o último estado
  conhecido por validador (não só o dia corrente) — validador que atualizou
  ontem e está offline hoje continua contando como atualizado.
- O aviso "BigQuery Storage module not found" é silenciado de propósito no
  `src/data.py` (a lib de storage não vale a pena para ~600 linhas/dia).
- `DEFAULT_WINDOW_DAYS = 2` + `CURRENT_DATE()` cobre 3 dias de calendário —
  é a janela "últimos 3 dias" citada no README.
- Deploy é no Streamlit Community Cloud; secrets entram pelo painel
  (Advanced settings → Secrets), não pelo repo.

## Antes de mexer

Ler o `README.md` — setup completo das credenciais, contexto de uso dos
KPIs/filtros e principalmente a seção **Changelog**, que documenta decisões
deliberadas de métricas (as-of, offline como marcador) — antes de alterar
`src/data.py`, `src/metrics.py` ou o significado de status/KPIs
(`ATUALIZADO`/`PENDENTE`, `· OFFLINE`, build alvo, bolinhas de atividade).
