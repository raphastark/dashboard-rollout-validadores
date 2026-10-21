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
py -m streamlit run app.py     # Windows (launcher py)
# streamlit run app.py         # Linux/Mac
```

Acesse http://localhost:8501.

## Uso

A página segue a moldura do Monitoramento de Frota, de cima para baixo:

- **Cabeçalho:** marca Novacap, título e três selos de fonte de dados. **BigQuery SMTR** mostra a data de referência e o horário da consulta. **API da frota** mostra o horário do ciclo de consulta. **Mapeamento** mostra o tamanho do roster. O ponto fica verde quando a fonte está operacional, vermelho quando o BigQuery está indisponível e âmbar quando uma fonte auxiliar falha.
- **Atualizar:** força nova consulta ao BigQuery, à API da frota e à planilha. Não limpa a memória de última versão conhecida.
- **Avisos:** só aparecem quando uma fonte falha. Falha do BigQuery bloqueia a página; falha da API da frota ou da planilha só tira o marcador correspondente.
- **Adoção da build alvo (manchete):** % de validadores na build alvo sobre a última versão **conhecida**, "N de M validadores", barra segmentada por versão e, com 2+ dias de histórico, "Última madrugada: +X validadores" — quantos validadores passaram de outra versão para a build alvo entre os dois últimos dias da janela (quem aparece pela primeira vez já na alvo não entra na conta). Validadores mapeados que nunca reportaram aparecem à parte na legenda.
- **Indicadores:** frota operante (veículos que reportaram na janela de 3 dias), pendentes de atualização (versão conhecida abaixo da alvo) e versões ativas.
- **Build alvo:** detectada automaticamente como a versão mais alta presente no dia mais recente.
- **Cores das versões:** por papel. Build alvo em verde, versão imediatamente anterior em azul, mais antigas em cinza. As mesmas cores valem para a barra, os gráficos e os blocos do inventário.
- **Histórico do rollout:** barras empilhadas por dia nos últimos 3 dias, com a build alvo na base e o % na alvo no topo de cada barra.
- **Distribuição por versão:** último estado conhecido de cada validador — o mesmo universo da manchete, incluindo quem está offline há mais de 3 dias com a versão lembrada —, com valor absoluto e %.
- **Inventário:** barra com filtro por status (Todos, Atualizados, Pendentes, Nunca reportou, Offline — contagens sobre o inventário completo), filtro de versão e busca por `id_veiculo` ou `id_validador`. A tabela mostra 3 blocos de atividade, um por dia, pintados com a cor da versão reportada naquele dia; só o contorno quando o validador não reportou (cada bloco tem rótulo acessível e dica com data e versão). Em telas estreitas o filtro de status rola na horizontal. Status: `Atualizado`, `Pendente`, `Nunca reportou`, com sufixos `· Offline` / `· Offline há N dias` em âmbar.
- **Tema:** escuro por padrão, com modo claro pelo menu do Streamlit (Settings → Theme). O tema inicial segue o do sistema operacional, e a troca reflete na hora, sem recarregar os dados.
- **Atualização dos dados:** a query no BigQuery roda no máximo 1x a cada 24h (cache via `@st.cache_data(ttl=86400)`). Como os upgrades dos validadores são feitos pela empresa de bilhetagem na madrugada, não há ganho em consultar com mais frequência — e evita custo desnecessário no BigQuery.
- **Memória de última versão:** a última versão conhecida de cada validador fica acumulada na memória do próprio Streamlit (`@st.cache_resource`) e é atualizada a cada consulta diária — veículo em manutenção longa (sem ping) continua no dashboard com a versão que tinha ao parar de reportar, pois versão não muda sem energia. O roster oficial vem da planilha "mapeamento dos validadores" (uso aditivo: quem nunca reportou aparece como `Nunca reportou`).

## Changelog

### [2026-10-21] — Identidade visual Novacap

Mudança **somente de apresentação** (`app.py`, `src/ui.py`, `static/styles.css`, `.streamlit/config.toml`). **Nenhuma mudança de dados ou métricas:** query, janela de 3 dias, TTL de 24h, memória de última versão conhecida, roster, API da frota como marcador auxiliar, detecção da build alvo e significado dos status continuam idênticos. Em `src/metrics.py` entrou apenas o campo `total_conhecido` no dataclass `KPIs` (o denominador da adoção que já era calculado), sem alterar nenhum cálculo.

- **Moldura do Monitoramento de Frota:** cabeçalho `#293046` com fio laranja `#E87A3E`, boneco e letras Novacap (em `static/`), título "Rollout de Validadores" (também no `page_title`; o `page_icon` passa a ser o boneco) e três selos de fonte de dados — BigQuery SMTR, API da frota e Mapeamento — com ponto verde (operacional), vermelho (BigQuery indisponível) ou âmbar (fonte auxiliar indisponível). Saem o ícone de pulso, o eyebrow "SMTR · Rollout · Ao Vivo" e a metabar.
- **Tema:** escuro por padrão, com modo claro pelo menu do Streamlit (`[theme.light]` / `[theme.dark]`); tokens de cor, raios e espaçamentos iguais aos do outro painel. Fontes Barlow, Barlow Condensed e IBM Plex Mono substituem Geist e JetBrains Mono.
- **Adoção como manchete:** card com o % da build alvo, "N de M validadores com versão conhecida", barra segmentada por versão e legenda; com 2+ dias de histórico mostra "Última madrugada: +X validadores" (em texto, sem seta), contando transições reais para a build alvo entre os dois últimos dias — não a variação líquida da série, que confundia validador estreando na janela com atualização. Validadores mapeados que nunca reportaram aparecem na legenda.
- **Indicadores neutros:** Frota operante, Pendentes de atualização e Versões ativas, sem ícones, chips coloridos ou gradientes. O card "Meta atingida" saiu porque repetia o número da manchete.
- **Cores das versões por papel:** alvo verde, versão anterior azul, mais antigas cinza (substituem a paleta de 7 cores por índice). Laranja fica restrito à marca.
- **Histórico do rollout:** barras empilhadas por dia (alvo na base) com o % da alvo no topo, no lugar das linhas.
- **Distribuição por versão:** barras horizontais em HTML sobre trilho de 100%, com valor absoluto e %, e rodapé explicando a detecção da build alvo e a contagem de offline. Usa as mesmas contagens da manchete (estado conhecido), então inclui validadores offline há mais de 3 dias e os totais batem com "N de M".
- **Inventário:** busca saiu do cabeçalho e foi para a barra do inventário, junto com o novo filtro por status (Todos, Atualizados, Pendentes, Nunca reportou, Offline — contagens calculadas antes da busca e do filtro de versão) e o filtro de versão existente. Tabela HTML com cabeçalho fixo; atividade em blocos coloridos com a cor da versão de cada dia (substituem as bolinhas emoji); status com ponto colorido e sufixo de offline em âmbar.
- **Avisos:** só aparecem quando uma fonte falha, como card neutro com ponto âmbar (sem o fundo amarelo do Streamlit). Falha do BigQuery continua bloqueante (`st.error` + `st.stop`), com os tokens do tema. O modo de manutenção usa o mesmo cabeçalho e uma mensagem neutra.
- **Troca de tema instantânea:** os tokens de cor usam `light-dark()` e seguem o `color-scheme` que o Streamlit aplica à página, então alternar claro/escuro pelo menu reflete na hora, inclusive no gráfico do histórico. O tema inicial segue o do sistema operacional.
- **Telas estreitas:** cabeçalho, manchete e barra do inventário quebram linha em vez de cortar rótulos.
- **Botão Atualizar sem consulta dupla:** a limpeza de cache passou para o `on_click` do botão, que roda antes do rerun; antes, com o cache expirado, o clique consultava o BigQuery, limpava e consultava de novo.
- **Atividade e acessibilidade:** os blocos de atividade são montados direto das versões diárias da janela (mesma regra do inventário), sem decodificar os emojis de `atividade_recente` — que eram ambíguos com 8+ versões. Cada bloco tem `aria-label`/dica com data e versão. No modo claro, o texto verde da build alvo e o âmbar de offline ganharam tons próprios com contraste ≥ 4,5:1 (as cores dos gráficos não mudam).
- **Streamlit ≥ 1.61:** piso do `requirements.txt` alinhado à versão testada (tema claro/escuro duplo, `width="stretch"`, `st.context.theme`).
- **README e repositório:** seção "Uso" reescrita para a nova interface. `.claude/settings.local.json` (permissões locais do Claude Code) saiu do versionamento e, junto com a pasta `design_handoff_rollout_validadores/` (referência local do handoff), entrou no `.gitignore`.

### [2026-08-21] — Validadores em manutenção longa não somem mais

- **Memória de última versão conhecida:** o estado de cada validador (versão + último ping) fica acumulado na memória do próprio Streamlit (`@st.cache_resource`) e é mesclado com a consulta diária. Como a versão de um validador não muda sem energia (não existe OTA desligado), quem para de pingar — ex.: veículo em manutenção pesada com a chave geral desligada — continua no dashboard com a versão que tinha, em vez de sumir ao sair da janela de 3 dias. Custo BigQuery inalterado: mesma query diária, nada de lookback.
- **Escopo "daqui para a frente":** a memória começa a acumular a partir do deploy desta versão. Validadores que já estavam silenciosos antes dela aparecem como `Nunca reportou` até voltarem a pingar; um redeploy futuro reseta o acúmulo, que recomeça da janela do dia.
- **Roster da frota:** planilha "mapeamento dos validadores" (CSV público) usada de forma **aditiva** — validadores mapeados que nunca reportaram aparecem com status `Nunca reportou`. Quem pinga nunca é removido (validador fora do veículo reporta id 99999, já filtrado pela query).
- **KPIs sobre o estado conhecido:** % de adoção e meta atingida contam validadores em manutenção longa com sua última versão conhecida. Frota operante continua sendo quem reportou na janela.
- **Inventário:** nova coluna `Último Ping` e marcador `· Offline há N dias` para quem está fora da janela de exibição.
- **Poda:** entradas fora do roster sem ping há mais de 7 dias são descartadas (equipamento trocado/enviado à Jaé não volta a reportar; a janela de 3 dias dá margem extra para a planilha ser atualizada).

### [2026-05-31] — Contagem fiel de validadores offline

- **Correção:** validadores temporariamente offline (ex.: veículos em manutenção pesada com energia cortada) não são mais excluídos da contagem de KPIs e gráficos. Antes, o filtro da API da frota em tempo real removia esses validadores do DataFrame, fazendo com que o dashboard mostrasse 270/280 atualizados quando na verdade todos os 280 já estavam na versão nova.
- **Inventário:** a coluna `build_atual` agora reflete o último estado conhecido do validador (via snapshot _as-of_) em vez de considerar apenas o dia corrente — se o validador atualizou ontem e está offline hoje, continua aparecendo como atualizado.
- **Indicador de offline:** validadores que não estão transmitindo no momento recebem o marcador `· Offline` na coluna de status do inventário, mantendo a transparência operacional sem penalizar a métrica de adoção.
- **Ajuste:** a API da frota em tempo real passou a ser usada apenas como informação auxiliar (marcação de offline), não mais como filtro duro que exclui dados do BigQuery.

### [2026-05-01] — Correção de métricas do histórico de rollout

- **Correção:** contagem de validadores no histórico agora usa snapshot _as-of_ por validador — cada ponto da série reflete exatamente quais validadores estavam ativos naquele dia, evitando que veículos que saíram de operação distorçam os percentuais retroativamente.
- **Otimização:** a série histórica do gráfico foi limitada aos últimos 3 dias, alinhando custo de query BQ com a janela exibida na UI.

### [2026-04-29] — Modo de manutenção

- **Novo:** adicionado suporte a _maintenance mode_; quando ativo, o dashboard exibe mensagem informativa em vez de tentar buscar dados.

### [2026-04-28] — Dev Container

- **Novo:** adicionada configuração de Dev Container (`.devcontainer/`) para facilitar o setup do ambiente no VS Code / GitHub Codespaces.

### [2026-04-28] — Legenda do gráfico de Histórico de Rollout

- **Correção:** itens da legenda não se sobrepõem mais quando há muitas versões ativas — largura de cada entrada ajustada via `entrywidthmode="pixels"` / `entrywidth=92`.
- **Ajuste:** margem superior do layout base aumentada (`t 54 → 62`) para dar respiro à legenda horizontal.

### [2026-04-28] — Polish inicial (v1.1)

Primeira rodada de melhorias visuais e de UX após o commit inicial:

- **Nomenclatura de status:** `"Operação OK"` renomeado para `"Atualizado"` — o rótulo anterior sugeria erroneamente que validadores ainda em versão antiga não estavam operacionais.
- **Legenda do gráfico de linha:** removido o prefixo `"Build "` e o namespace `"V."` — legenda passa a exibir apenas `"2.22.28"` em vez de `"─●─ Build V.2.22.28"`. Cada versão virou dois traces (`lines` + `markers`) com o mesmo `legendgroup`, mantendo o toggle por clique.
- **Eixo Y do gráfico de barras:** removido o prefixo `"V."` dos rótulos do eixo para evitar corte em cards estreitos; versão completa ainda aparece no tooltip via `customdata`.
- **Tabela de inventário:** fonte reduzida (13 → 12 px) e espaçamento entre emojis de atividade removido — o indicador de 3 dias fica mais compacto.
- **Cards de gráfico:** adicionado `overflow: hidden` — elimina a barra de scroll interna e corrige o bug em que o gráfico capturava o scroll do mouse ao passar sobre ele.

### [2026-04-28] — Lançamento inicial

- Dashboard Streamlit para acompanhamento do rollout de versões do app dos validadores embarcados nos veículos.
- Consulta direta ao BigQuery (`rj-smtr.monitoramento.gps_validador`) — substitui o fluxo anterior baseado em Google Sheets + Gemini.
- KPIs: frota operante, % de adoção da build alvo, número de versões ativas, total de validadores atualizados.
- Gráficos: Histórico de Rollout (linha por versão) e Status Hoje (distribuição por versão).
- Tabela de inventário com indicadores de atividade diária por validador (🟢 / 🟡 / ⚪).
- Cache de 24 h via `@st.cache_data(ttl=86400)` para minimizar custo no BigQuery.

---

## Deploy no Streamlit Community Cloud

1. `git init` e suba o repo no GitHub (o `.gitignore` já protege o `secrets.toml`).
2. https://share.streamlit.io → **New app** apontando para o repo.
3. Em **Advanced settings → Secrets**, cole o conteúdo do seu `secrets.toml`.
4. Deploy. Compartilhe a URL com a equipe.

## Estrutura

```
app.py                    # entry-point Streamlit
src/
  data.py                 # cliente BQ + query + cache + roster + memória de estado
  metrics.py              # cálculo dos KPIs, merge de estado e tabelas
  ui.py                   # componentes visuais
static/
  styles.css              # estilo custom (injetado via inject_styles)
  novacap-*.png           # boneco e letras Novacap (cabeçalho e page_icon)
.streamlit/
  config.toml             # tema
  secrets.toml.example    # template da Service Account
requirements.txt
```
# dashboard-rollout-validadores
