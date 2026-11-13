# Shared wire contract

Pydantic models in `backend/road_safety/contracts.py` are authoritative.
`python scripts/export_contracts.py` exports JSON Schema. In `frontend`, run
`npm run contracts` to generate Zod validators and inferred TypeScript types.
`npm run contracts:check` fails on drift. Do not edit generated validators.

SSE uses `event: run_started`, `event: stage`, `event: completed`, or `event: error`.
Each `data:` is a JSON object: StageEvent for start/stage, AnalysisResponse for
completed, ErrorEvent for error. POST `/api/chat` accepts ChatRequest.
Only a complete, validated final response changes the dashboard. End dates in
query filters and evidence are exclusive. Dataset rows are immutable per id.
