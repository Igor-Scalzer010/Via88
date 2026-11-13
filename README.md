# Via — Inteligência Rodoviária

Um ambiente de investigação dos acidentes registrados pelas concessionárias de
rodovias federais na ANTT. Combine filtros, gráficos e perguntas em português;
continue uma análise sem perder o recorte anterior e fixe resultados para comparar.

O agente descreve análises e widgets em JSON validado. FastAPI executa ferramentas
tipadas sobre DuckDB, enquanto Next.js renderiza componentes conhecidos. O modelo
não escreve React, Python ou SQL executável.

## Executar no Windows

Requisitos: Python 3.12 e Node.js LTS (22 ou superior). Execute na raiz:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
Copy-Item .env.example .env
cd frontend
npm.cmd ci
cd ..
```

Edite `.env`: `OPENAI_API_KEY` e `OPENAI_MODEL` habilitam as perguntas em linguagem
natural. Escolha um modelo com suporte a saída estruturada JSON Schema. A chave
fica somente no FastAPI. A visão inicial, os filtros e o histórico não exigem LLM.
O frontend usa a API local na porta 8000. Para alterar esse endereço, copie
`frontend/.env.example` para `frontend/.env.local` e configure `BACKEND_URL` ali.

### Limites por chamada ao modelo

Para os testes, o `.env.example` sugere `gpt-6-luna` e os seguintes controles:

| Variável | Padrão | Efeito |
| --- | --- | --- |
| `OPENAI_MAX_OUTPUT_TOKENS` | `4096` | Máximo de tokens gerados, incluindo raciocínio e JSON. |
| `OPENAI_REASONING_EFFORT` | `low` | Esforço de raciocínio do modelo. |
| `OPENAI_MAX_RETRIES` | `0` | Nenhuma nova tentativa automática após falha do provedor. |
| `OPENAI_TIMEOUT_SECONDS` | `60` | Timeout da chamada ao modelo, limitado também pelo tempo da análise. |
| `RUN_TIMEOUT_SECONDS` | `120` | Tempo máximo de toda a análise, incluindo consultas locais. |

Os tokens devem estar entre 1 e 128.000; tentativas adicionais, entre 0 e 3;
timeouts devem ser positivos e de até 600 segundos. Esforço aceita `none`, `low`,
`medium`, `high`, `xhigh` ou `max`, conforme suporte do modelo escolhido.
Reinicie o backend após editar `.env`.

Cada pergunta faz uma chamada lógica ao modelo. Com `OPENAI_MAX_RETRIES=0`, não há
repetição automática; aumentar esse valor permite novas tentativas do SDK em falhas
e pode aumentar o consumo. O plano continua limitado a oito consultas locais aos
dados. Elas não são chamadas adicionais à OpenAI. Se o modelo atingir o limite de
tokens, a aplicação informa que a resposta ficou incompleta e preserva o painel
anterior; não aumenta o limite nem tenta completar o JSON automaticamente.

O backend registra identificador da chamada, modelo, resultado, duração e consumo
de tokens de entrada, saída, raciocínio e total, quando fornecidos pelo provedor.
Raciocínio já está incluído na saída e não deve ser somado novamente. Falhas sem
metadados aparecem como `unavailable`, não como consumo zero. Os logs não incluem
chave, perguntas ou respostas; para acompanhar localmente, use nível de log `INFO`.

Não há teto financeiro acumulado nem limite adicional de tokens de entrada. Os
limites existentes de mensagem e histórico continuam valendo, mas o custo varia
com o contexto, o modelo e as tentativas. Esses controles não reservam os créditos
da conta. Para conferir preços e consumo da conta, consulte a
[tabela oficial](https://developers.openai.com/api/docs/pricing) e o
[painel de uso](https://platform.openai.com/usage).

### Preparar a base

```powershell
# Dados reais: descobre os CSVs do catálogo, baixa e publica um snapshot validado.
.\.venv\Scripts\road-safety.exe ingest

# Limites estaduais simplificados do IBGE para o mapa.
.\.venv\Scripts\road-safety.exe geography
```

Para experimentar a interface sem baixar a ANTT, use uma base separada:

```powershell
.\.venv\Scripts\road-safety.exe demo --data-dir data-demo
```

Depois defina `DATA_DIR=data-demo` em `.env`. A aplicação identifica essa base como
sintética; seus números não representam acidentes reais. Não copie dados de
demonstração para a base ANTT.

### Iniciar os serviços

Em dois terminais na raiz:

```powershell
.\scripts\dev.ps1 backend
```

```powershell
.\scripts\dev.ps1 frontend
```

Abra **http://localhost:3000**. API/OpenAPI: http://127.0.0.1:8000/docs.
Os serviços escutam apenas interfaces locais. Esta versão é individual, sem login,
e não foi preparada para exposição pública.

No Linux/macOS, use `.venv/bin/python`, `.venv/bin/road-safety` e `npm` nos comandos
equivalentes; inicie o backend com `python -m uvicorn road_safety.api:app --reload`.

## Perguntas e contexto

- “Quais foram os cinco trechos com mais acidentes nos últimos três anos?”
- “Desses trechos, quais tiveram mais acidentes com vítimas graves?”
- “Mostre a evolução mensal dos acidentes na BR-101 em 2025.”
- “Compare os acidentes por tipo em SP e RJ.”
- “Quais faixas de 10 km tiveram mais acidentes na BR-116 em SP?”

“Desses trechos” mantém a coorte e o período da resposta anterior. Uma nova conversa
começa uma investigação independente. Fixar um widget preserva seus dados e sua
configuração; ele não é substituído pela próxima pergunta. Layouts e conversas são
persistidos localmente.

## Regras de análise

- A fonte cobre **rodovias federais concedidas informadas à ANTT**. Não representa
  todos os acidentes de todas as rodovias brasileiras.
- `trecho` na origem significa rodovia/UF, como `BR-116/SP`. Segmentos quilométricos
  são outra dimensão, formada por faixas de 10 km `[início, fim)`.
- “Últimos três anos” resolve uma janela móvel de 36 meses. O fim exclusivo é o
  dia seguinte à maior data válida do snapshot; o início é esse fim menos 36 meses.
- Acidentes com vítimas graves contam ocorrências com feridos graves; vítimas
  graves somam pessoas. Esses valores têm definições e rótulos distintos.
- Atualização do catálogo não comprova cobertura completa. Os gráficos e a
  explicação mostram o intervalo consultado e as lacunas observadas.
- Frequência absoluta não mede risco por veículo. A base não informa exposição ao
  tráfego, causas, clima ou coordenadas dos acidentes. O mapa agrega por UF.
- Ausência de cobertura, valor desconhecido e zero não são equivalentes.

## Organização e operação

```text
backend/road_safety/   API, agente, ferramentas, persistência e pipeline
backend/tests/         Testes determinísticos com dados pequenos e modelo simulado
frontend/              Next.js, widgets, chat e validadores Zod gerados
contracts/             JSON Schema exportado dos modelos Pydantic
scripts/               Execução, geração e validação
data/                  Downloads, snapshots e bancos locais (ignorado pelo Git)
```

O pipeline preserva arquivos originais e mantém schemas `raw`, `staging` e
`analytics`. Recursos antigos e sucessores de uma concessão são reconciliados por
um manifesto explícito; não se deve unir indiscriminadamente todas as versões raw.
Cada publicação cria um DuckDB imutável e troca o ponteiro da versão ativa somente
após validar o novo arquivo. Conversas e datasets guardam a versão consultada.

A atualização é manual: execute `ingest` novamente. Falhas não substituem a versão
ativa. Snapshots antigos não são removidos automaticamente, pois análises salvas
podem depender deles. Para backup, pare o backend e copie o diretório `DATA_DIR`
inteiro, incluindo SQLite, manifests e snapshots. Restaure o conjunto no mesmo
diretório configurado.

Para detalhes do contrato, consulte [contracts/README.md](contracts/README.md).
As decisões e evidências de normalização estão em
[docs/data-quality.md](docs/data-quality.md); o fluxo entre as camadas está em
[docs/architecture.md](docs/architecture.md).
Mudanças em Pydantic exigem regenerar JSON Schema e Zod:

```powershell
.\.venv\Scripts\python.exe scripts/export_contracts.py
cd frontend
npm.cmd run contracts
```

## Validação

```powershell
.\scripts\check.ps1
cd frontend
npm.cmd run test:e2e
npm.cmd run test:e2e:integration
```

Os testes não precisam de chave OpenAI e não fazem chamadas pagas. O teste com um
modelo real é uma verificação adicional manual: configure a chave e o modelo,
execute a pergunta inicial e a continuação e confira as fontes de ambos resultados.
No Windows, Playwright usa o Microsoft Edge instalado. Em Linux/macOS, instale o
Chromium antes com `npx playwright install chromium`.

Dependências Python ficam fixadas em `requirements.lock`, gerado com pip-tools a
partir de `pyproject.toml`; o frontend usa `package-lock.json`. Para atualizar o lock
Python, use a `.venv` e `python -m piptools compile --extra dev --output-file
requirements.lock pyproject.toml`, depois execute todas as verificações.

## Fontes e atribuição

- [ANTT — Acidentes](https://dados.antt.gov.br/dataset/acidentes-rodovias), dados das
  concessionárias, conforme licença de atribuição indicada no catálogo.
- [API de malhas do IBGE](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3),
  limites geográficos usados no mapa agregado por UF.
- [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview), grafo,
  checkpoints e streaming; [LangChain](https://docs.langchain.com/oss/python/langchain/models),
  integração com o modelo e saída estruturada.
