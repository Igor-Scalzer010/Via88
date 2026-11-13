"""FastAPI boundary for evidence-backed, component-based dashboard updates."""

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from road_safety.agents.graph import (
    DashboardGraph,
    build_graph,
    evidence_answer,
    make_widgets,
    replacement_actions,
    stream_analysis,
)
from road_safety.agents.planner import (
    ModelUnavailableError,
    OpenAIPlanner,
    OutputTokenLimitError,
    PlannedView,
    Planner,
)
from road_safety.config import Settings
from road_safety.contracts import (
    AnalysisResponse,
    Catalog,
    ChatRequest,
    Dashboard,
    Dataset,
    ErrorEvent,
    Filters,
    Health,
    Metric,
    QuerySpec,
    Scalar,
    Session,
    SessionSummary,
    StageEvent,
)
from road_safety.data.service import DataService, DataUnavailableError
from road_safety.storage import AnalysisContext, RequestConflict, Storage, parse_context

LOGGER = logging.getLogger(__name__)


def sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def fingerprint(request: ChatRequest) -> str:
    return hashlib.sha256(request.model_dump_json().encode()).hexdigest()


def create_app(
    settings: Settings | None = None,
    planner: Planner | None = None,
    data_service: DataService | None = None,
) -> FastAPI:
    """Build the local, single-worker API with injectable planning for integration tests."""
    configuration = settings or Settings()
    service = data_service or DataService(configuration.data_dir)
    selected_planner = planner or OpenAIPlanner(configuration)
    locks: dict[str, asyncio.Lock] = {}
    stores: list[Storage] = []
    graphs: list[DashboardGraph] = []

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(level=logging.INFO)
        configuration.data_dir.mkdir(parents=True, exist_ok=True)
        stores.append(Storage(configuration.data_dir / "app.sqlite"))
        application.state.storage = stores[0]
        async with AsyncSqliteSaver.from_conn_string(
            str(configuration.data_dir / "checkpoints.sqlite")
        ) as checkpointer:
            graphs.append(build_graph(selected_planner, service, checkpointer))
            application.state.graph = graphs[0]
            try:
                yield
            finally:
                graphs.clear()
                stores.clear()

    application = FastAPI(title="Road Safety Intelligence", version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=configuration.allowed_origins,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type"],
    )

    def storage() -> Storage:
        return stores[0]

    def session_or_404(session_id: str) -> Session:
        try:
            return storage().get_session(session_id)
        except KeyError as error:
            raise HTTPException(404, "Investigação não encontrada.") from error

    def catalog_for(context: AnalysisContext) -> Catalog:
        try:
            return service.catalog(context.get("snapshot_id"))
        except ValueError as error:
            raise HTTPException(
                503,
                "O snapshot desta investigação não está disponível. "
                "Reimporte os dados ou crie uma nova investigação.",
            ) from error

    @application.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health(
            data_available=service.catalog().available,
            llm_configured=configuration.llm_configured,
            model=configuration.openai_model or None,
        )

    @application.get("/api/catalog", response_model=Catalog)
    def catalog() -> Catalog:
        return service.catalog()

    @application.get("/api/geography")
    def geography() -> dict[str, object]:
        try:
            return service.geography()
        except ValueError as error:
            raise HTTPException(
                503,
                "Malha geográfica indisponível. "
                "Execute a importação geográfica descrita no README.",
            ) from error

    @application.get("/api/sessions", response_model=list[SessionSummary])
    def list_sessions() -> list[SessionSummary]:
        return storage().list_sessions()

    @application.post("/api/sessions", response_model=Session, status_code=201)
    def create_session() -> Session:
        return storage().create_session()

    @application.get("/api/sessions/{session_id}", response_model=Session)
    def get_session(session_id: str) -> Session:
        return session_or_404(session_id)

    @application.patch("/api/sessions/{session_id}/dashboard", response_model=Dashboard)
    async def patch_dashboard(session_id: str, dashboard: Dashboard) -> Dashboard:
        session_or_404(session_id)
        lock = locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            raise HTTPException(409, "Aguarde a análise em andamento para editar o painel.")
        async with lock:
            try:
                return storage().patch_dashboard(session_id, dashboard)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error

    @application.get("/api/datasets/{dataset_id}", response_model=Dataset)
    def get_dataset(
        dataset_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        sort_by: str | None = None,
        sort_direction: Literal["ascending", "descending"] = "ascending",
    ) -> Dataset:
        try:
            dataset = storage().dataset(dataset_id)
        except KeyError as error:
            raise HTTPException(404, "Resultado não encontrado.") from error
        if sort_by and sort_by not in {column.key for column in dataset.columns}:
            raise HTTPException(422, "Coluna de ordenação desconhecida.")
        if dataset.query.operation == "detail":
            query = dataset.query.model_copy(
                update={"offset": offset, "limit": limit, "sort": sort_direction}
            )
            try:
                page = service.query(query, dataset.snapshot_id, sort_by=sort_by)
            except ValueError as error:
                raise HTTPException(
                    503, "O snapshot deste resultado não está disponível."
                ) from error
            return page.model_copy(update={"id": dataset.id, "query": dataset.query})
        rows = dataset.rows
        if sort_by:
            non_null = [row for row in rows if row.get(sort_by) is not None]
            missing = [row for row in rows if row.get(sort_by) is None]
            selected_column = next(column for column in dataset.columns if column.key == sort_by)

            def sort_key(row: dict[str, Scalar]) -> str | float:
                value = row[sort_by]
                if selected_column.data_type == "number" and isinstance(value, (int, float)):
                    return float(value)
                return str(value)

            rows = sorted(non_null, key=sort_key, reverse=sort_direction == "descending") + missing
        return dataset.model_copy(update={"rows": rows[offset : offset + limit]})

    async def overview(session_id: str, filters: Filters | None = None) -> AnalysisResponse:
        session_or_404(session_id)
        lock = locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            raise HTTPException(409, "Uma análise já está em andamento nesta investigação.")
        async with lock:
            session = session_or_404(session_id)
            context = storage().context(session_id)
            current_catalog = await asyncio.to_thread(catalog_for, context)
            request_id = f"overview_{uuid4().hex}"
            response = AnalysisResponse(
                session_id=session_id,
                request_id=request_id,
                run_id=uuid4().hex,
                analysis_id=f"analysis_{uuid4().hex}",
                snapshot_id=current_catalog.snapshot_id,
                status="insufficient_data",
                answer=(
                    "Nenhum snapshot de dados disponível. "
                    "Execute a importação da ANTT para começar."
                ),
            )
            if not current_catalog.available or not current_catalog.snapshot_id:
                return response
            resolved_filters = filters or service.default_filters(current_catalog.snapshot_id)
            metrics: tuple[Metric, ...] = (
                "accidents",
                "accidents_with_severe",
                "severe_injuries",
                "deaths",
            )
            specs = [
                QuerySpec(operation="overview", metric=metric, filters=resolved_filters)
                for metric in metrics
            ]
            specs.extend(
                [
                    QuerySpec(
                        operation="timeseries",
                        group_by="month",
                        filters=resolved_filters,
                        limit=100,
                    ),
                    QuerySpec(
                        operation="ranking", group_by="road_uf", filters=resolved_filters, limit=5
                    ),
                    QuerySpec(
                        operation="distribution",
                        group_by="accident_type",
                        filters=resolved_filters,
                        limit=12,
                    ),
                    QuerySpec(
                        operation="distribution", group_by="uf", filters=resolved_filters, limit=27
                    ),
                ]
            )
            try:
                datasets = [
                    await asyncio.to_thread(service.query, spec, current_catalog.snapshot_id)
                    for spec in specs
                ]
            except ValueError as error:
                raise HTTPException(
                    503, "Não foi possível consultar o snapshot. Verifique a importação."
                ) from error
            if not datasets or datasets[0].evidence.matched_rows == 0:
                response.datasets = datasets
                response.evidence = [dataset.evidence for dataset in datasets]
                response.answer = (
                    "Nenhum registro encontrado nos filtros escolhidos. "
                    "O painel anterior foi preservado; ausência de registros "
                    "não comprova ausência de acidentes."
                )
                return response
            views = [PlannedView(query_index=index, type="metric") for index in range(4)]
            views.extend(
                [
                    PlannedView(query_index=4, type="line_chart"),
                    PlannedView(query_index=5, type="bar_chart"),
                    PlannedView(query_index=5, type="table"),
                    PlannedView(query_index=6, type="donut_chart"),
                    PlannedView(query_index=7, type="map_choropleth"),
                ]
            )
            widgets = make_widgets(datasets, views)
            response.status = "complete"
            response.datasets = datasets
            response.dashboard_actions = replacement_actions(session, widgets)
            response.evidence = [dataset.evidence for dataset in datasets]
            response.answer = evidence_answer(datasets[:1])
            context.update(
                {
                    "snapshot_id": current_catalog.snapshot_id,
                    "filters": datasets[0].query.filters.model_dump(mode="json"),
                    "cohort": None,
                    "previous_queries": [],
                }
            )
            return storage().commit(response, context, request_id)

    @application.get("/api/sessions/{session_id}/overview", response_model=AnalysisResponse)
    async def get_overview(session_id: str) -> AnalysisResponse:
        return await overview(session_id)

    @application.post("/api/sessions/{session_id}/overview", response_model=AnalysisResponse)
    async def filtered_overview(session_id: str, filters: Filters) -> AnalysisResponse:
        return await overview(session_id, filters)

    @application.post("/api/chat")
    async def chat(body: ChatRequest, request: Request) -> StreamingResponse:
        session_or_404(body.session_id)
        digest = fingerprint(body)
        try:
            replay = storage().replay(body.session_id, body.request_id, digest)
        except RequestConflict as error:
            raise HTTPException(409, str(error)) from error
        lock = locks.setdefault(body.session_id, asyncio.Lock())
        if replay is None and lock.locked():
            raise HTTPException(409, "Uma análise já está em andamento nesta investigação.")

        async def events() -> AsyncIterator[str]:
            if replay is not None:
                yield sse("completed", replay.model_dump(mode="json"))
                return
            async with lock:
                # Recheck after acquisition in case concurrent callers shared a request id.
                try:
                    previous = storage().replay(body.session_id, body.request_id, digest)
                except RequestConflict:
                    # Headers are already sent here: terminate with a typed stream error.
                    yield sse(
                        "error",
                        ErrorEvent(
                            run_id=uuid4().hex,
                            code="request_conflict",
                            message="request_id já utilizado com outra pergunta ou filtros.",
                        ).model_dump(),
                    )
                    return
                if previous:
                    yield sse("completed", previous.model_dump(mode="json"))
                    return
                run_id = uuid4().hex
                yield sse(
                    "run_started",
                    StageEvent(
                        run_id=run_id, stage="started", label="Análise iniciada"
                    ).model_dump(),
                )
                try:
                    session = storage().get_session(body.session_id)
                    context = storage().context(body.session_id)
                    current_catalog = await asyncio.to_thread(catalog_for, context)
                    if not current_catalog.available:
                        raise DataUnavailableError(
                            "Importe os dados da ANTT antes de consultar o agente."
                        )
                    filters = body.filters
                    if filters is None and context.get("filters"):
                        filters = Filters.model_validate(context["filters"])
                    filters = filters or service.default_filters(current_catalog.snapshot_id)
                    result: dict[str, object] | None = None
                    async with asyncio.timeout(configuration.run_timeout_seconds):
                        async for event, payload in stream_analysis(
                            graphs[0],
                            body,
                            session,
                            context,
                            current_catalog,
                            filters,
                            run_id,
                        ):
                            if await request.is_disconnected():
                                return
                            if event == "result":
                                result = payload
                            else:
                                yield sse(event, payload)
                    if result is None:
                        raise ValueError("A análise não produziu uma resposta válida.")
                    if await request.is_disconnected():
                        return
                    response = AnalysisResponse.model_validate(result["response"])
                    committed = storage().commit(
                        response, parse_context(result["next_context"]), digest, body.message
                    )
                    yield sse("completed", committed.model_dump(mode="json"))
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    if isinstance(error, ModelUnavailableError):
                        code, message = "llm_not_configured", str(error)
                    elif isinstance(error, OutputTokenLimitError):
                        code, message = (
                            "output_token_limit",
                            "A resposta do modelo atingiu o limite de tokens e ficou incompleta. "
                            "Simplifique a pergunta e tente novamente.",
                        )
                    elif isinstance(error, TimeoutError):
                        code, message = (
                            "timeout",
                            "A análise excedeu o tempo limite. Tente uma pergunta mais específica.",
                        )
                    elif isinstance(error, DataUnavailableError):
                        code, message = "data_unavailable", str(error)
                    elif isinstance(error, ValueError):
                        code, message = (
                            "invalid_analysis",
                            "Não foi possível validar esta análise. "
                            "Ajuste a pergunta ou confira a disponibilidade dos dados.",
                        )
                    elif isinstance(error, HTTPException):
                        code, message = "data_unavailable", str(error.detail)
                    else:
                        code, message = (
                            "analysis_failed",
                            "Não foi possível concluir a análise. "
                            "Verifique a configuração do provedor e tente novamente.",
                        )
                    LOGGER.warning(
                        "Analysis failed run_id=%s error_type=%s", run_id, type(error).__name__
                    )
                    yield sse(
                        "error", ErrorEvent(run_id=run_id, code=code, message=message).model_dump()
                    )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return application


app = create_app()
