"""Deterministic evidence handling around an explicit, persisted analytical graph."""

import asyncio
from collections.abc import AsyncIterator
from typing import Literal, TypedDict
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from road_safety.agents.planner import AnalysisPlan, PlannedView, Planner
from road_safety.contracts import (
    AnalysisResponse,
    Catalog,
    ChartWidget,
    ChatRequest,
    Cohort,
    Dataset,
    Filters,
    MapWidget,
    MetricWidget,
    RemoveAction,
    Scalar,
    Session,
    StageEvent,
    TableWidget,
    UpsertAction,
    Widget,
)
from road_safety.data.service import DataService
from road_safety.storage import AnalysisContext, is_vehicle_breakdown, validate_dashboard
from road_safety.tools.accidents import build_query_tool


class GraphState(TypedDict):
    request: dict[str, object]
    run_id: str
    session: dict[str, object]
    prior_context: AnalysisContext
    next_context: AnalysisContext
    catalog: dict[str, object]
    filters: dict[str, object]
    plan: dict[str, object] | None
    datasets: list[dict[str, object]]
    response: dict[str, object] | None


type DashboardGraph = CompiledStateGraph[GraphState, None, GraphState, GraphState]
ViewType = Literal[
    "metric",
    "bar_chart",
    "line_chart",
    "area_chart",
    "donut_chart",
    "table",
    "map_choropleth",
]
DIMENSION_LABELS = {
    "road": "rodovia",
    "road_uf": "rodovia / UF",
    "segment_10km": "faixa de 10 km",
    "uf": "UF",
    "concession": "concessionária",
    "accident_type": "tipo de acidente",
    "direction": "sentido",
    "track_type": "tipo de pista",
    "month": "mês",
    "year": "ano",
    "weekday": "dia da semana",
    "hour": "hora",
    "vehicle_type": "veículo",
}


def emit(state: GraphState, stage: str, label: str) -> None:
    get_stream_writer()(StageEvent(run_id=state["run_id"], stage=stage, label=label).model_dump())


def display_value(value: Scalar) -> str:
    return "não informado" if value is None else str(value)


def make_widgets(datasets: list[Dataset], views: list[PlannedView] | None = None) -> list[Widget]:
    """Translate a closed visual vocabulary into renderer-owned widget configs."""
    if not views:
        views = []
        for index, dataset in enumerate(datasets):
            operation = dataset.query.operation
            kinds: list[ViewType] = (
                ["metric"]
                if operation == "overview"
                else ["line_chart", "table"]
                if operation == "timeseries"
                else ["table"]
                if operation == "detail"
                else ["donut_chart", "table"]
                if operation == "distribution"
                else ["metric", "bar_chart", "table"]
            )
            views.extend(PlannedView(query_index=index, type=kind) for kind in kinds)
    widgets: list[Widget] = []
    for view in views:
        if view.query_index >= len(datasets):
            raise ValueError("Visualização referencia uma consulta inexistente.")
        dataset = datasets[view.query_index]
        widget_type: ViewType = view.type
        if widget_type == "donut_chart" and is_vehicle_breakdown(dataset):
            widget_type = "bar_chart"
        title = dataset.title
        if dataset.query.operation != "overview":
            title += f" por {DIMENSION_LABELS[dataset.query.group_by]}"
        common = {
            "id": f"w_{uuid4().hex}",
            "title": title,
            "dataset_id": dataset.id,
            "description": (
                f"{dataset.evidence.definition} Período "
                f"[{dataset.evidence.start_date}, {dataset.evidence.end_date})."
            ),
        }
        if is_vehicle_breakdown(dataset):
            common["description"] += (
                " Categorias de veículos podem compartilhar a mesma ocorrência; "
                "não representam partes de um total."
            )
        if widget_type == "metric":
            if is_vehicle_breakdown(dataset):
                raise ValueError(
                    "Categorias de veículos se sobrepõem; não podem ser somadas em um card."
                )
            widget: Widget = MetricWidget(type="metric", **common)
            if dataset.query.operation != "overview":
                widget.title = f"{dataset.title} — soma dos {len(dataset.rows)} grupos exibidos"
        elif widget_type == "table":
            widget = TableWidget(
                type="table", columns=[column.key for column in dataset.columns], **common
            )
        elif widget_type == "map_choropleth":
            widget = MapWidget(type="map_choropleth", **common)
        else:
            widget = ChartWidget(type=widget_type, **common)
        widgets.append(widget)
    return widgets


def evidence_answer(datasets: list[Dataset]) -> str:
    """Only interpolate facts produced by validated database operations."""
    sections: list[str] = []
    for dataset in datasets:
        evidence = dataset.evidence
        sections.append(
            f"**{dataset.title}** — período de {evidence.start_date} "
            f"até {evidence.end_date} (fim exclusivo)."
        )
        if dataset.query.operation != "detail":
            rows = dataset.rows[:5]
            facts = [
                f"{row.get('label', row.get('key', 'Total'))}: "
                f"{display_value(row.get('value'))}"
                + (
                    f" (período anterior: {display_value(row.get('previous_value'))}; "
                    f"variação: {display_value(row.get('delta_pct'))}"
                    f"{'%' if row.get('delta_pct') is not None else ' (base zero ou ausente)'})"
                    if "previous_value" in row
                    else ""
                )
                for row in rows
            ]
            if facts:
                sections.append("; ".join(facts) + ".")
            if len(dataset.rows) > 5:
                sections.append(
                    f"A visualização contém {len(dataset.rows)} grupos; "
                    "os cinco primeiros estão resumidos acima."
                )
        sections.append(evidence.definition)
        sections.append(
            f"Base consultada: {evidence.matched_rows} registros; "
            f"{evidence.resources_with_records} de {evidence.resources_total} "
            "recursos com registros no recorte."
        )
        sections.extend(f"Observação: {warning}" for warning in evidence.warnings)
        if evidence.coverage == "partial":
            sections.append(
                "A cobertura é parcial; os resultados descrevem os registros disponíveis "
                "e podem não representar todo o período."
            )
    return "\n\n".join(sections)


def replacement_actions(
    session: Session, widgets: list[Widget]
) -> list[RemoveAction | UpsertAction]:
    pinned = set(session.dashboard.pinned_widget_ids)
    return [
        RemoveAction(action="remove", widget_id=widget.id)
        for widget in session.dashboard.widgets
        if widget.id not in pinned
    ] + [UpsertAction(action="add", widget=widget) for widget in widgets]


def build_graph(
    planner: Planner, service: DataService, checkpointer: BaseCheckpointSaver[str]
) -> DashboardGraph:
    """Compile the persisted workflow; only validated plans can reach data tools."""

    async def interpret(state: GraphState) -> dict[str, object]:
        emit(state, "interpret", "Interpretando a pergunta")
        request = ChatRequest.model_validate(state["request"])
        session = Session.model_validate(state["session"])
        planning_context = state["prior_context"].copy()
        planning_context["messages"] = [
            {"role": message.role, "content": message.content[:3000]}
            for message in session.messages[-12:]
        ]
        plan = await planner.plan(
            request.message,
            planning_context,
            Filters.model_validate(state["filters"]),
            Catalog.model_validate(state["catalog"]),
        )
        return {"plan": AnalysisPlan.model_validate(plan).model_dump(mode="json")}

    def validate_plan(state: GraphState) -> dict[str, object]:
        emit(state, "validate", "Validando o plano de análise")
        plan = AnalysisPlan.model_validate(state["plan"])
        if plan.status == "query" and not plan.queries:
            raise ValueError("O plano não contém consultas.")
        if plan.use_previous_cohort:
            prior: dict[str, object] = dict(state["prior_context"])
            if plan.reference_analysis_id:
                reference = next(
                    (
                        item
                        for item in state["prior_context"].get("analyses", [])
                        if item.get("analysis_id") == plan.reference_analysis_id
                    ),
                    None,
                )
                prior = reference or {}
            if not prior.get("cohort"):
                plan = AnalysisPlan(
                    status="clarification",
                    clarification=(
                        "A quais trechos você se refere? "
                        "Faça primeiro um ranking ou selecione um grupo."
                    ),
                )
            else:
                cohort = Cohort.model_validate(prior["cohort"])
                previous_filters = Filters.model_validate(prior.get("filters", {}))
                for query in plan.queries:
                    query.cohort = cohort
                    merged = previous_filters.model_dump(mode="json")
                    defaults = Filters().model_dump(mode="json")
                    merged.update(
                        {
                            key: value
                            for key, value in query.filters.model_dump(mode="json").items()
                            if value != defaults[key]
                        }
                    )
                    if plan.inherit_previous_period:
                        merged["start_date"] = previous_filters.start_date
                        merged["end_date"] = previous_filters.end_date
                    query.filters = Filters.model_validate(merged)
        # Explicit removals override both inherited restrictions and copied model values.
        defaults = Filters().model_dump(mode="json")
        for query in plan.queries:
            cleared = query.filters.model_dump(mode="json")
            for field in plan.clear_filters:
                cleared[field] = defaults[field]
            query.filters = Filters.model_validate(cleared)
        return {"plan": plan.model_dump(mode="json")}

    async def execute(state: GraphState) -> dict[str, object]:
        emit(state, "query", "Consultando os dados da ANTT")
        plan = AnalysisPlan.model_validate(state["plan"])
        catalog = Catalog.model_validate(state["catalog"])
        if not catalog.snapshot_id:
            return {"datasets": []}
        query_tool = build_query_tool(service, catalog.snapshot_id)
        datasets: list[dict[str, object]] = []
        for query in plan.queries:
            result = await asyncio.to_thread(query_tool.invoke, {"spec": query})
            dataset = Dataset.model_validate(result)
            datasets.append(dataset.model_dump(mode="json"))
        return {"datasets": datasets}

    def finish(state: GraphState) -> dict[str, object]:
        emit(state, "analyze", "Conferindo evidências e preparando visualizações")
        request = ChatRequest.model_validate(state["request"])
        plan = AnalysisPlan.model_validate(state["plan"])
        session = Session.model_validate(state["session"])
        query_datasets = [Dataset.model_validate(value) for value in state["datasets"]]
        # Views address original query positions; wire results are unique immutable datasets.
        by_id: dict[str, Dataset] = {}
        for dataset in query_datasets:
            existing = by_id.get(dataset.id)
            if existing is not None and existing.model_dump() != dataset.model_dump():
                raise ValueError("Consultas produziram o mesmo ID com datasets divergentes.")
            by_id.setdefault(dataset.id, dataset)
        datasets = list(by_id.values())
        catalog = Catalog.model_validate(state["catalog"])
        context = state["prior_context"].copy()
        status: Literal["complete", "clarification", "insufficient_data"] = "complete"
        actions: list[RemoveAction | UpsertAction] = []
        if plan.status != "query":
            status = plan.status
            answer = (
                plan.clarification
                or "Não há evidências suficientes para responder a essa pergunta com esta base."
            )
        elif not datasets or any(
            dataset.evidence.coverage == "none"
            or dataset.evidence.matched_rows == 0
            or (
                dataset.query.operation != "detail"
                and not any(isinstance(row.get("value"), (int, float)) for row in dataset.rows)
            )
            for dataset in datasets
        ):
            status = "insufficient_data"
            answer = (
                "Não há dados suficientes para a métrica e o recorte solicitados. "
                "Ausência de registros ou contagens desconhecidas não comprova "
                "ausência de acidentes. Ajuste o período ou os filtros."
            )
        else:
            emit(state, "visualize", "Preparando gráficos e tabelas")
            widgets = make_widgets(query_datasets, plan.views)
            pinned = set(session.dashboard.pinned_widget_ids)
            dashboard = session.dashboard.model_copy(
                update={
                    "widgets": [
                        widget for widget in session.dashboard.widgets if widget.id in pinned
                    ]
                    + widgets
                }
            )
            dashboard.layouts = {}
            validate_dashboard(dashboard, session.datasets + datasets)
            actions = replacement_actions(session, widgets)
            answer = evidence_answer(datasets)
            primary = datasets[0]
            cohort = (
                Cohort(
                    dimension=primary.query.group_by,
                    keys=[str(row["key"]) for row in primary.rows if row.get("key") is not None],
                )
                if primary.query.operation in ("ranking", "distribution") and primary.rows
                else primary.query.cohort
            )
            context.update(
                {
                    "snapshot_id": primary.snapshot_id,
                    "filters": primary.query.filters.model_dump(mode="json"),
                    "cohort": cohort.model_dump(mode="json") if cohort else None,
                    "previous_queries": [
                        dataset.query.model_dump(mode="json") for dataset in datasets
                    ],
                }
            )
        response = AnalysisResponse(
            session_id=request.session_id,
            request_id=request.request_id,
            run_id=state["run_id"],
            analysis_id=f"analysis_{uuid4().hex}",
            snapshot_id=catalog.snapshot_id,
            status=status,
            answer=answer,
            datasets=datasets,
            dashboard_actions=actions,
            evidence=[dataset.evidence for dataset in datasets],
            suggestions=[
                "Mostre a evolução mensal desses resultados",
                "Compare acidentes e vítimas graves",
            ],
        )
        if status == "complete":
            context["analyses"] = (
                context.get("analyses", [])
                + [
                    {
                        "analysis_id": response.analysis_id,
                        "question": request.message,
                        "filters": context.get("filters", {}),
                        "cohort": context.get("cohort"),
                        "queries": context.get("previous_queries", []),
                    }
                ]
            )[-12:]
        return {"response": response.model_dump(mode="json"), "next_context": context}

    builder = StateGraph(GraphState)
    builder.add_node("interpret", interpret)
    builder.add_node("validate_plan", validate_plan)
    builder.add_node("execute_tools", execute)
    builder.add_node("finish", finish)
    builder.add_edge(START, "interpret")
    builder.add_edge("interpret", "validate_plan")
    builder.add_conditional_edges(
        "validate_plan",
        lambda state: (
            "query" if AnalysisPlan.model_validate(state["plan"]).status == "query" else "finish"
        ),
        {"query": "execute_tools", "finish": "finish"},
    )
    builder.add_edge("execute_tools", "finish")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)


async def stream_analysis(
    graph: DashboardGraph,
    request: ChatRequest,
    session: Session,
    context: AnalysisContext,
    catalog: Catalog,
    filters: Filters,
    run_id: str,
) -> AsyncIterator[tuple[str, dict[str, object]]]:
    """Reset transient fields on every turn; only the last successful context survives."""
    initial: GraphState = {
        "request": request.model_dump(mode="json"),
        "run_id": run_id,
        "session": session.model_dump(mode="json"),
        "prior_context": context,
        "next_context": context,
        "catalog": catalog.model_dump(mode="json"),
        "filters": filters.model_dump(mode="json"),
        "plan": None,
        "datasets": [],
        "response": None,
    }
    async for part in graph.astream(
        initial,
        config={"configurable": {"thread_id": request.session_id}},
        stream_mode=["updates", "custom"],
        version="v2",
    ):
        if part["type"] == "custom":
            yield "stage", part["data"]
        elif part["type"] == "updates" and "finish" in part["data"]:
            yield "result", part["data"]["finish"]
