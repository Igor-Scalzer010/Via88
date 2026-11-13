"""Integration checks run the real graph, SQLite persistence and DuckDB fixture."""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from road_safety.agents.graph import make_widgets
from road_safety.agents.planner import AnalysisPlan, PlannedView
from road_safety.api import create_app
from road_safety.config import Settings
from road_safety.contracts import AnalysisResponse, Catalog, Dataset, Filters, QuerySpec
from road_safety.data.demo import create_demo
from road_safety.data.service import DataService
from road_safety.storage import AnalysisContext, RequestConflict


class FixturePlanner:
    """A test dependency, never a production fallback for missing credentials."""

    def __init__(self) -> None:
        self.calls = 0
        self.delay = 0.0
        self.contexts: list[AnalysisContext] = []

    async def plan(
        self, question: str, prior_context: AnalysisContext, filters: Filters, catalog: Catalog
    ) -> AnalysisPlan:
        self.calls += 1
        self.contexts.append(prior_context)
        await asyncio.sleep(self.delay)
        if question == "ambiguous":
            return AnalysisPlan(
                status="clarification", clarification="Qual período deseja consultar?"
            )
        if question == "detail":
            return AnalysisPlan(
                queries=[QuerySpec(operation="detail", filters=filters, limit=3)],
                views=[PlannedView(query_index=0, type="table")],
            )
        if question == "clear_filters":
            return AnalysisPlan(
                queries=[
                    QuerySpec(
                        operation="ranking",
                        group_by="road_uf",
                        metric="accidents",
                        filters=Filters.model_validate(prior_context["filters"]),
                        limit=5,
                    )
                ],
                use_previous_cohort=True,
                clear_filters=["severity", "roads", "km_min"],
                views=[PlannedView(query_index=0, type="table")],
            )
        if question == "duplicate":
            query = QuerySpec(operation="ranking", group_by="road_uf", filters=filters, limit=2)
            return AnalysisPlan(
                queries=[query, query.model_copy(deep=True)],
                views=[
                    PlannedView(query_index=0, type="bar_chart"),
                    PlannedView(query_index=1, type="table"),
                ],
            )
        followup = question in ("followup", "earlier")
        spec = QuerySpec(
            operation="ranking",
            group_by="road_uf",
            metric="accidents_with_severe"
            if followup
            else "severe_injuries"
            if question == "unknown"
            else "accidents",
            filters=Filters() if followup else filters,
            limit=5 if followup else 2,
        )
        kind = "map_choropleth" if question == "invalid_map" else "bar_chart"
        return AnalysisPlan(
            queries=[spec],
            use_previous_cohort=followup,
            reference_analysis_id=(
                str(prior_context["analyses"][0]["analysis_id"]) if question == "earlier" else None
            ),
            views=[PlannedView(query_index=0, type=kind), PlannedView(query_index=0, type="table")],
        )


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    create_demo(tmp_path)
    return tmp_path


def settings_for(path: Path, timeout: float = 120) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=path,
        openai_api_key="test-unused",
        openai_model="test-model",
        run_timeout_seconds=timeout,
    )


def events(response: object) -> list[tuple[str, dict[str, object]]]:
    # HTTP response text is deliberately parsed like the browser's SSE consumer.
    text = response.text
    result = []
    for block in text.strip().split("\n\n"):
        lines = block.splitlines()
        name = next(line[7:] for line in lines if line.startswith("event: "))
        payload = next(line[6:] for line in lines if line.startswith("data: "))
        result.append((name, json.loads(payload)))
    return result


def question(
    client: TestClient, session_id: str, text: str = "ranking", request_id: str = "request_1"
) -> list[tuple[str, dict[str, object]]]:
    response = client.post(
        "/api/chat", json={"session_id": session_id, "message": text, "request_id": request_id}
    )
    assert response.status_code == 200, response.text
    return events(response)


def test_overview_without_llm_and_dashboard_validation(data_dir: Path) -> None:
    settings = settings_for(data_dir).model_copy(update={"openai_api_key": "", "openai_model": ""})
    with TestClient(create_app(settings)) as client:
        assert not client.get("/api/health").json()["llm_configured"]
        session_id = client.post("/api/sessions").json()["id"]
        response = client.get(f"/api/sessions/{session_id}/overview")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "complete"
        session = client.get(f"/api/sessions/{session_id}").json()
        dashboard = session["dashboard"]
        assert len(dashboard["widgets"]) == 9
        dashboard["widgets"][0]["field"] = "unknown_field"
        assert (
            client.patch(f"/api/sessions/{session_id}/dashboard", json=dashboard).status_code == 422
        )
        response_events = question(client, session_id)
        assert response_events[-1][0] == "error"
        assert response_events[-1][1]["code"] == "llm_not_configured"
        assert client.get(f"/api/sessions/{session_id}").json()["messages"] == []


def test_followup_cohort_survives_restart_and_replay_is_idempotent(data_dir: Path) -> None:
    planner = FixturePlanner()
    with TestClient(create_app(settings_for(data_dir), planner)) as client:
        session_id = client.post("/api/sessions").json()["id"]
        first_events = question(client, session_id)
        assert first_events[0][0] == "run_started"
        assert "stage" in [kind for kind, _ in first_events]
        assert first_events[-1][0] == "completed"
        first = first_events[-1][1]
        assert first["status"] == "complete"
        assert len(first["datasets"][0]["rows"]) == 2
        repeated = question(client, session_id)
        assert repeated[-1][1] == first
        assert planner.calls == 1
        conflict = client.post(
            "/api/chat",
            json={"session_id": session_id, "message": "different", "request_id": "request_1"},
        )
        assert conflict.status_code == 409
    with TestClient(create_app(settings_for(data_dir), planner)) as client:
        second_events = question(client, session_id, "followup", "request_2")
        assert second_events[-1][0] == "completed", second_events
        second = second_events[-1][1]
        first_data, second_data = first["datasets"][0], second["datasets"][0]
        first_keys = {row["key"] for row in first_data["rows"]}
        assert set(second_data["query"]["cohort"]["keys"]) == first_keys
        assert {row["key"] for row in second_data["rows"]}.issubset(first_keys)
        assert second_data["query"]["filters"] == first_data["query"]["filters"]
        assert second_data["query"]["metric"] == "accidents_with_severe"
        assert len(client.get(f"/api/sessions/{session_id}").json()["messages"]) == 4
        assert [message["role"] for message in planner.contexts[-1]["messages"]] == [
            "user",
            "assistant",
        ]
        earlier = question(client, session_id, "earlier", "request_3")[-1][1]
        assert earlier["status"] == "complete"
        assert set(earlier["datasets"][0]["query"]["cohort"]["keys"]) == first_keys


def test_invalid_widgets_clarification_and_pin_preserve_dashboard(data_dir: Path) -> None:
    with TestClient(create_app(settings_for(data_dir), FixturePlanner())) as client:
        session_id = client.post("/api/sessions").json()["id"]
        question(client, session_id)
        dashboard = client.get(f"/api/sessions/{session_id}").json()["dashboard"]
        pinned_id = dashboard["widgets"][0]["id"]
        dashboard["pinned_widget_ids"] = [pinned_id]
        assert (
            client.patch(f"/api/sessions/{session_id}/dashboard", json=dashboard).status_code == 200
        )
        invalid = question(client, session_id, "invalid_map", "invalid")
        assert invalid[-1][0] == "error"
        assert client.get(f"/api/sessions/{session_id}").json()["dashboard"] == dashboard
        clarification = question(client, session_id, "ambiguous", "clarify")[-1][1]
        assert clarification["status"] == "clarification"
        assert clarification["dashboard_actions"] == []
        assert client.get(f"/api/sessions/{session_id}").json()["dashboard"] == dashboard
        second = question(client, session_id, "followup", "new")[-1][1]
        assert all(action.get("widget_id") != pinned_id for action in second["dashboard_actions"])
        final = client.get(f"/api/sessions/{session_id}").json()["dashboard"]
        assert (
            next(widget for widget in final["widgets"] if widget["id"] == pinned_id)
            == dashboard["widgets"][0]
        )


def test_timeout_does_not_commit_and_same_request_can_retry(data_dir: Path) -> None:
    planner = FixturePlanner()
    planner.delay = 0.3
    settings = settings_for(data_dir, timeout=0.05)
    with TestClient(create_app(settings, planner)) as client:
        session_id = client.post("/api/sessions").json()["id"]
        result = question(client, session_id)
        assert result[-1][0] == "error"
        assert result[-1][1]["code"] == "timeout"
        session = client.get(f"/api/sessions/{session_id}").json()
        assert session["messages"] == []
        assert session["dashboard"]["widgets"] == []
        planner.delay = 0
        settings.run_timeout_seconds = 120
        retry = question(client, session_id)
        assert retry[-1][0] == "completed", retry
        assert len(client.get(f"/api/sessions/{session_id}").json()["messages"]) == 2


def test_empty_data_and_invalid_requests(tmp_path: Path) -> None:
    with TestClient(create_app(settings_for(tmp_path), FixturePlanner())) as client:
        assert client.get("/api/catalog").json()["available"] is False
        session_id = client.post("/api/sessions").json()["id"]
        response = client.get(f"/api/sessions/{session_id}/overview").json()
        assert response["status"] == "insufficient_data"
        assert not response["dashboard_actions"]
        assert client.get("/api/sessions/unknown").status_code == 404
        assert client.get("/api/datasets/unknown").status_code == 404
        assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_isolated_sessions_and_pagination(data_dir: Path) -> None:
    with TestClient(create_app(settings_for(data_dir), FixturePlanner())) as client:
        session_id = client.post("/api/sessions").json()["id"]
        other_id = client.post("/api/sessions").json()["id"]
        first = question(client, session_id)[-1][1]
        dataset = first["datasets"][0]
        page = client.get(f"/api/datasets/{dataset['id']}?offset=1&limit=1").json()
        assert page["rows"] == dataset["rows"][1:2]
        assert client.get(f"/api/datasets/{dataset['id']}?sort_by=not_a_column").status_code == 422
        other = question(client, other_id, "followup")[-1][1]
        assert other["status"] == "clarification"
        assert not client.get(f"/api/sessions/{other_id}").json()["dashboard"]["widgets"]


def test_unknown_metric_and_empty_period_preserve_previous_widgets(data_dir: Path) -> None:
    class UnknownCountsService(DataService):
        unknown = False

        def query(
            self, spec: QuerySpec, snapshot_id: str | None = None, *, sort_by: str | None = None
        ) -> Dataset:
            dataset = super().query(spec, snapshot_id, sort_by=sort_by)
            if self.unknown:
                return dataset.model_copy(
                    update={"rows": [{**row, "value": None} for row in dataset.rows]}
                )
            return dataset

    service = UnknownCountsService(data_dir)
    with TestClient(create_app(settings_for(data_dir), FixturePlanner(), service)) as client:
        session_id = client.post("/api/sessions").json()["id"]
        question(client, session_id)
        previous = client.get(f"/api/sessions/{session_id}").json()["dashboard"]
        previous_filters = client.get(f"/api/sessions/{session_id}").json()["active_filters"]
        service.unknown = True
        unknown = question(client, session_id, "unknown", "unknown")[-1][1]
        assert unknown["status"] == "insufficient_data"
        assert unknown["dashboard_actions"] == []
        assert client.get(f"/api/sessions/{session_id}").json()["dashboard"] == previous
        assert (
            client.get(f"/api/sessions/{session_id}").json()["active_filters"] == previous_filters
        )
        service.unknown = False
        empty = client.post(
            f"/api/sessions/{session_id}/overview",
            json={"start_date": "1900-01-01", "end_date": "1901-01-01"},
        ).json()
        assert empty["status"] == "insufficient_data"
        assert client.get(f"/api/sessions/{session_id}").json()["dashboard"] == previous
        assert (
            client.get(f"/api/sessions/{session_id}").json()["active_filters"] == previous_filters
        )


def test_post_lock_replay_conflict_ends_with_a_structured_error(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = create_app(settings_for(data_dir), FixturePlanner())
    with TestClient(application) as client:
        session_id = client.post("/api/sessions").json()["id"]
        question(client, session_id)
        baseline = client.get(f"/api/sessions/{session_id}").json()
        question(client, session_id, "ambiguous", "clarification")
        assert (
            client.get(f"/api/sessions/{session_id}").json()["active_filters"]
            == baseline["active_filters"]
        )
        original_replay = application.state.storage.replay
        calls = 0

        def replay(sid: str, request_id: str, digest: str) -> AnalysisResponse | None:
            nonlocal calls
            if request_id == "race":
                calls += 1
                if calls == 2:
                    raise RequestConflict("simulated concurrent request id conflict")
            return original_replay(sid, request_id, digest)

        monkeypatch.setattr(application.state.storage, "replay", replay)
        result = question(client, session_id, "ranking", "race")
        assert result[-1][0] == "error"
        assert result[-1][1]["code"] == "request_conflict"
        assert (
            client.get(f"/api/sessions/{session_id}").json()["dashboard"] == baseline["dashboard"]
        )


def test_detail_paginates_and_sorts_over_the_complete_snapshot(data_dir: Path) -> None:
    with TestClient(create_app(settings_for(data_dir), FixturePlanner())) as client:
        session_id = client.post("/api/sessions").json()["id"]
        result = question(client, session_id, "detail")[-1][1]
        assert result["status"] == "complete"
        dataset = result["datasets"][0]
        assert dataset["row_count"] > len(dataset["rows"])
        base = f"/api/datasets/{dataset['id']}?limit=3&sort_by=km&sort_direction=ascending"
        first = client.get(base).json()
        second = client.get(base + "&offset=3").json()
        kilometer_values = [row["km"] for row in first["rows"] + second["rows"]]
        assert kilometer_values == sorted(kilometer_values)
        assert first["id"] == second["id"] == dataset["id"]
        assert not ({row["key"] for row in first["rows"]} & {row["key"] for row in second["rows"]})


def test_explicit_filter_clears_preserve_exact_cohort_and_unmentioned_filters(
    data_dir: Path,
) -> None:
    service = DataService(data_dir)
    default_filters = service.default_filters()
    top = service.query(QuerySpec(operation="ranking", filters=default_filters, limit=1))
    road, uf = str(top.rows[0]["key"]).split("/")
    restricted = default_filters.model_copy(
        update={
            "roads": [road],
            "ufs": [uf],
            "severity": "with_severe",
            "km_min": 0.0,
            "km_max": 1000.0,
        }
    )
    with TestClient(create_app(settings_for(data_dir), FixturePlanner())) as client:
        session_id = client.post("/api/sessions").json()["id"]
        first_events = events(
            client.post(
                "/api/chat",
                json={
                    "session_id": session_id,
                    "request_id": "restricted",
                    "message": "ranking",
                    "filters": restricted.model_dump(mode="json"),
                },
            )
        )
        first = first_events[-1][1]
        assert first["status"] == "complete"
        second = question(client, session_id, "clear_filters", "cleared")[-1][1]
        assert second["status"] == "complete"
        first_data, second_data = first["datasets"][0], second["datasets"][0]
        assert set(second_data["query"]["cohort"]["keys"]) == {
            row["key"] for row in first_data["rows"]
        }
        filters = second_data["query"]["filters"]
        assert filters["severity"] == "all"
        assert filters["roads"] == []
        assert filters["km_min"] is None
        for unchanged in ("start_date", "end_date", "ufs", "km_max"):
            assert filters[unchanged] == first_data["query"]["filters"][unchanged]
        assert sum(row["value"] for row in second_data["rows"]) > sum(
            row["value"] for row in first_data["rows"]
        )
        assert client.get(f"/api/sessions/{session_id}").json()["active_filters"] == filters
    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate({"clear_filters": ["start_date"]})
    assert AnalysisPlan(clear_filters=["km_max", "vehicle_types"]).clear_filters == [
        "km_max",
        "vehicle_types",
    ]


def test_equivalent_queries_share_one_dataset_without_losing_view_indices(data_dir: Path) -> None:
    with TestClient(create_app(settings_for(data_dir), FixturePlanner())) as client:
        session_id = client.post("/api/sessions").json()["id"]
        response = question(client, session_id, "duplicate")[-1][1]
        assert response["status"] == "complete"
        assert len(response["datasets"]) == len(response["evidence"]) == 1
        assert response["answer"].count("Base consultada:") == 1
        widgets = [action["widget"] for action in response["dashboard_actions"]]
        assert [widget["type"] for widget in widgets] == ["bar_chart", "table"]
        assert all(widget["dataset_id"] == response["datasets"][0]["id"] for widget in widgets)
        restored = client.get(f"/api/sessions/{session_id}").json()
        assert restored["datasets"] == response["datasets"]
        assert restored["dashboard"]["widgets"] == widgets
        assert restored["latest_analysis"] == response


def test_conflicting_payloads_with_the_same_dataset_id_do_not_commit(data_dir: Path) -> None:
    class ConflictingService(DataService):
        calls = 0

        def query(
            self, spec: QuerySpec, snapshot_id: str | None = None, *, sort_by: str | None = None
        ) -> Dataset:
            dataset = super().query(spec, snapshot_id, sort_by=sort_by)
            self.calls += 1
            return (
                dataset.model_copy(update={"title": "conflicting title"})
                if self.calls == 2
                else dataset
            )

    with TestClient(
        create_app(settings_for(data_dir), FixturePlanner(), ConflictingService(data_dir))
    ) as client:
        session_id = client.post("/api/sessions").json()["id"]
        response_events = question(client, session_id, "duplicate")
        assert response_events[-1][0] == "error"
        assert response_events[-1][1]["code"] == "invalid_analysis"
        restored = client.get(f"/api/sessions/{session_id}").json()
        assert restored["messages"] == restored["datasets"] == []
        assert restored["dashboard"]["widgets"] == []


@pytest.mark.parametrize("explicit_donut", [False, True])
def test_vehicle_distribution_uses_bars_and_rejects_partition_or_total_widgets(
    data_dir: Path,
    explicit_donut: bool,
) -> None:
    class VehiclePlanner:
        async def plan(
            self, question: str, prior_context: AnalysisContext, filters: Filters, catalog: Catalog
        ) -> AnalysisPlan:
            return AnalysisPlan(
                queries=[
                    QuerySpec(
                        operation="distribution", group_by="vehicle_type", filters=filters, limit=10
                    )
                ],
                views=(
                    [
                        PlannedView(query_index=0, type="donut_chart"),
                        PlannedView(query_index=0, type="table"),
                    ]
                    if explicit_donut
                    else []
                ),
            )

    service = DataService(data_dir)
    expected = service.query(
        QuerySpec(
            operation="distribution",
            group_by="vehicle_type",
            filters=service.default_filters(),
            limit=10,
        )
    )
    with TestClient(create_app(settings_for(data_dir), VehiclePlanner())) as client:
        session_id = client.post("/api/sessions").json()["id"]
        response = question(client, session_id)[-1][1]
        assert response["status"] == "complete"
        assert response["datasets"][0]["rows"] == expected.rows
        assert "não some" in response["answer"]
        dashboard = client.get(f"/api/sessions/{session_id}").json()["dashboard"]
        assert [widget["type"] for widget in dashboard["widgets"]] == ["bar_chart", "table"]
        assert "não representam partes de um total" in dashboard["widgets"][0]["description"]
        donut_dashboard = {
            **dashboard,
            "widgets": [
                {**dashboard["widgets"][0], "type": "donut_chart"},
                dashboard["widgets"][1],
            ],
        }
        invalid_donut = client.patch(f"/api/sessions/{session_id}/dashboard", json=donut_dashboard)
        assert invalid_donut.status_code == 422
        assert "Categorias de veículos" in invalid_donut.json()["detail"]
        original = dashboard["widgets"][0]
        metric_dashboard = {
            **dashboard,
            "widgets": [
                {
                    "id": original["id"],
                    "title": "Total inválido",
                    "type": "metric",
                    "dataset_id": original["dataset_id"],
                    "field": "value",
                    "aggregation": "sum",
                },
                dashboard["widgets"][1],
            ],
        }
        invalid_metric = client.patch(
            f"/api/sessions/{session_id}/dashboard", json=metric_dashboard
        )
        assert invalid_metric.status_code == 422
        assert "Categorias de veículos" in invalid_metric.json()["detail"]
        assert client.get(f"/api/sessions/{session_id}").json()["dashboard"] == dashboard
    with pytest.raises(ValueError, match="Categorias de veículos"):
        make_widgets([expected], [PlannedView(query_index=0, type="metric")])
