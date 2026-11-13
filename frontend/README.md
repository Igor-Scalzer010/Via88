# Via — frontend

Next.js App Router, React e TypeScript estrito. O FastAPI mantém a base analítica,
as conversas e os resultados. A interface só renderiza componentes conhecidos.

```powershell
npm.cmd install
npm.cmd run contracts
npm.cmd run dev
```

`BACKEND_URL` é uma variável privada do servidor Next, com padrão
`http://127.0.0.1:8000`. O proxy `/api/[...path]` transmite SSE sem buffer.
Nenhuma chave de modelo é necessária no navegador.

O contrato Pydantic é a fonte da verdade. Após alterar os modelos Python,
execute `python scripts/export_contracts.py` na raiz e `npm.cmd run contracts`
nesta pasta. `contracts:check` detecta divergências. Não edite o arquivo gerado.

O consumidor SSE aceita eventos de etapa e aplica somente o resultado final
validado, de forma atômica. Componentes não aceitam código React, HTML, SQL ou
opções livres de bibliotecas enviadas pelo modelo.

Fixar preserva o resultado e seu snapshot durante novas análises; bloquear
layout impede movimento e redimensionamento. Layouts e resultados fixados são
persistidos no backend. Alterar filtros gera uma visão geral determinística,
inclusive sem chave LLM. O mapa representa totais por UF, com malha fornecida
pelo backend, sem inferir coordenadas de acidentes. Exportação de tabela baixa
somente a página visível, indicada no nome do arquivo.

```powershell
npm.cmd run lint
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e
npm.cmd run test:e2e:integration
```

O teste E2E de integração inicia FastAPI com DuckDB de teste e um planejador
determinístico. Ele exercita a aplicação real sem consumir uma API de LLM.
Dados sintéticos existem apenas nos testes e no comando explícito de demo do
backend. Screenshots de aceitação ficam em `../tmp/via-dashboard-*.png`.
