"""Transactional local sessions, immutable query results and request deduplication."""

import json
import sqlite3
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from road_safety.contracts import (
    AnalysisResponse,
    ChatMessage,
    Cohort,
    Dashboard,
    Dataset,
    Filters,
    QuerySpec,
    Session,
    SessionSummary,
)


class AnalysisContext(TypedDict, total=False):
    snapshot_id: str
    filters: dict[str, object]
    cohort: dict[str, object] | None
    previous_queries: list[dict[str, object]]
    messages: list[dict[str, str]]
    analyses: list[dict[str, object]]


class RequestConflict(ValueError):
    """A request id was reused for different input."""


def parse_context(value: object) -> AnalysisContext:
    """Validate persisted JSON before treating it as conversational query context."""
    if not isinstance(value, dict):
        raise ValueError("Contexto de investigação inválido.")
    result: AnalysisContext = {}
    snapshot = value.get("snapshot_id")
    if isinstance(snapshot, str):
        result["snapshot_id"] = snapshot
    if "filters" in value:
        result["filters"] = Filters.model_validate(value["filters"]).model_dump(mode="json")
    if "cohort" in value:
        cohort = value["cohort"]
        result["cohort"] = Cohort.model_validate(cohort).model_dump(mode="json") if cohort else None
    queries = value.get("previous_queries", [])
    if not isinstance(queries, list):
        raise ValueError("Consultas anteriores inválidas.")
    result["previous_queries"] = [
        QuerySpec.model_validate(item).model_dump(mode="json") for item in queries
    ]
    history = value.get("analyses", [])
    if not isinstance(history, list) or any(not isinstance(item, dict) for item in history):
        raise ValueError("Histórico de análises inválido.")
    result["analyses"] = history[-12:]
    return result


def is_vehicle_breakdown(dataset: Dataset) -> bool:
    """Vehicle groups can overlap within an accident and never form a partition."""
    return dataset.query.group_by == "vehicle_type" and dataset.query.operation not in (
        "overview",
        "detail",
    )


def validate_dashboard(dashboard: Dashboard, datasets: list[Dataset]) -> None:
    """Check references and renderer capabilities before any dashboard mutation."""
    by_id = {dataset.id: dataset for dataset in datasets}
    ids = [widget.id for widget in dashboard.widgets]
    if len(ids) != len(set(ids)):
        raise ValueError("IDs de widgets devem ser únicos.")
    if not set(dashboard.pinned_widget_ids).issubset(ids):
        raise ValueError("Um widget fixado não existe no painel.")
    for widget in dashboard.widgets:
        dataset = by_id.get(widget.dataset_id)
        if dataset is None:
            raise ValueError("O widget referencia um dataset desconhecido.")
        if is_vehicle_breakdown(dataset) and widget.type in ("metric", "donut_chart"):
            raise ValueError(
                "Categorias de veículos podem compartilhar a mesma ocorrência. "
                "Use barras ou tabela; não representam partes de um total."
            )
        columns = {column.key: column for column in dataset.columns}
        if widget.type == "table":
            fields = widget.columns
        elif widget.type == "metric":
            fields = [widget.field]
            if widget.aggregation != "count" and columns.get(widget.field):
                if columns[widget.field].data_type != "number":
                    raise ValueError("A métrica requer uma coluna numérica.")
        else:
            fields = [widget.x_field, widget.y_field]
            if columns.get(widget.y_field) and columns[widget.y_field].data_type != "number":
                raise ValueError("O eixo de valores requer uma coluna numérica.")
            if widget.type == "map_choropleth" and dataset.query.group_by != "uf":
                raise ValueError("O mapa requer uma agregação por UF.")
        if not set(fields).issubset(columns):
            raise ValueError("O widget referencia uma coluna desconhecida.")
    for layout in dashboard.layouts.values():
        if len({item.i for item in layout}) != len(layout):
            raise ValueError("IDs de layout duplicados.")
        if any(item.i not in ids or item.x + item.w > 12 for item in layout):
            raise ValueError("Layout inválido para este painel.")


class Storage:
    """Use short SQLite transactions; never keep a connection across model calls."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, context TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS responses (
                    session_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (session_id, request_id)
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def create_session(self) -> Session:
        session = Session(id=uuid4().hex, title="Nova investigação")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?)",
                (session.id, session.model_dump_json(), "{}"),
            )
        return session

    def list_sessions(self) -> list[SessionSummary]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM sessions ORDER BY rowid DESC").fetchall()
        return [
            SessionSummary(id=session.id, title=session.title)
            for (payload,) in rows
            if (session := Session.model_validate_json(payload))
        ]

    def get_session(self, session_id: str) -> Session:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return Session.model_validate_json(row[0])

    def context(self, session_id: str) -> AnalysisContext:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT context FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return parse_context(json.loads(row[0]))

    def replay(self, session_id: str, request_id: str, fingerprint: str) -> AnalysisResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT fingerprint,payload FROM responses WHERE session_id=? AND request_id=?",
                (session_id, request_id),
            ).fetchone()
        if row is None:
            return None
        if row[0] != fingerprint:
            raise RequestConflict("request_id já utilizado com outra pergunta ou filtros.")
        return AnalysisResponse.model_validate_json(row[1])

    def patch_dashboard(self, session_id: str, dashboard: Dashboard) -> Dashboard:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
            if row is None:
                raise KeyError(session_id)
            session = Session.model_validate_json(row[0])
            validate_dashboard(dashboard, session.datasets)
            session.dashboard = dashboard
            connection.execute(
                "UPDATE sessions SET payload=? WHERE id=?", (session.model_dump_json(), session_id)
            )
        return dashboard

    def dataset(self, dataset_id: str) -> Dataset:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM datasets WHERE id=?", (dataset_id,)
            ).fetchone()
        if row is None:
            raise KeyError(dataset_id)
        return Dataset.model_validate_json(row[0])

    def commit(
        self,
        response: AnalysisResponse,
        context: AnalysisContext,
        fingerprint: str,
        question: str | None = None,
    ) -> AnalysisResponse:
        """Atomically save a validated response and apply its unpinned widget actions."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT fingerprint,payload FROM responses WHERE session_id=? AND request_id=?",
                (response.session_id, response.request_id),
            ).fetchone()
            if previous:
                if previous[0] != fingerprint:
                    raise RequestConflict("request_id já utilizado com outro conteúdo.")
                return AnalysisResponse.model_validate_json(previous[1])
            row = connection.execute(
                "SELECT payload FROM sessions WHERE id=?", (response.session_id,)
            ).fetchone()
            if row is None:
                raise KeyError(response.session_id)
            session = Session.model_validate_json(row[0])
            datasets = {dataset.id: dataset for dataset in session.datasets}
            for dataset in response.datasets:
                previous_dataset = connection.execute(
                    "SELECT payload FROM datasets WHERE id=?", (dataset.id,)
                ).fetchone()
                payload = dataset.model_dump_json()
                if previous_dataset and previous_dataset[0] != payload:
                    raise ValueError("Um dataset imutável não pode ser sobrescrito.")
                connection.execute(
                    "INSERT OR IGNORE INTO datasets VALUES (?,?,?)",
                    (dataset.id, response.session_id, payload),
                )
                datasets[dataset.id] = dataset
            widgets = {widget.id: widget for widget in session.dashboard.widgets}
            pinned = set(session.dashboard.pinned_widget_ids)
            for action in response.dashboard_actions:
                target_id = action.widget_id if action.action == "remove" else action.widget.id
                if target_id in pinned:
                    raise ValueError("O agente não pode alterar widgets fixados.")
                if action.action == "remove":
                    widgets.pop(target_id, None)
                else:
                    widgets[target_id] = action.widget
            dashboard = session.dashboard.model_copy(update={"widgets": list(widgets.values())})
            dashboard.layouts = {
                key: [item for item in items if item.i in widgets]
                for key, items in dashboard.layouts.items()
            }
            session.datasets = list(datasets.values())
            validate_dashboard(dashboard, session.datasets)
            session.dashboard = dashboard
            session.latest_analysis = response
            if response.status == "complete" and context.get("filters"):
                session.active_filters = Filters.model_validate(context["filters"])
            if question is not None:
                session.messages.extend(
                    [
                        ChatMessage(
                            id=f"{response.analysis_id}_user", role="user", content=question
                        ),
                        ChatMessage(
                            id=f"{response.analysis_id}_assistant",
                            role="assistant",
                            content=response.answer,
                            analysis_id=response.analysis_id,
                        ),
                    ]
                )
                if len(session.messages) == 2:
                    session.title = question[:80]
            connection.execute(
                "UPDATE sessions SET payload=?,context=? WHERE id=?",
                (session.model_dump_json(), json.dumps(context), session.id),
            )
            connection.execute(
                "INSERT INTO responses VALUES (?,?,?,?)",
                (session.id, response.request_id, fingerprint, response.model_dump_json()),
            )
        return response
