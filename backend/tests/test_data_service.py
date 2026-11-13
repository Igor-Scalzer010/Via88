"""Analytical correctness and bounded capability contracts."""

from datetime import date
from pathlib import Path

import pytest
from fixtures.data_helpers import source
from pydantic import ValidationError

from road_safety.contracts import Cohort, Filters, QuerySpec
from road_safety.data.demo import create_demo
from road_safety.data.ingestion import build_snapshot
from road_safety.data.service import DataService, DataUnavailableError


@pytest.fixture
def service(tmp_path: Path) -> DataService:
    build_snapshot(
        tmp_path,
        [
            source(
                tmp_path,
                [
                    {"data": "01/10/2023", "km": "9,999", "gravemente_feridos": "2", "mortos": "1"},
                    {"data": "30/09/2026", "km": "10,000", "gravemente_feridos": "3"},
                    {"data": "30/09/2026", "km": "19,999"},
                    {"data": "30/09/2026", "km": "20,000", "trecho": "BR-116/SP"},
                    {"data": "30/09/2026", "km": "10", "trecho": "BR-040/MG", "moto": "1"},
                    {"data": "30/09/2023", "km": "50", "trecho": "BR-999/AC"},
                ],
            )
        ],
    )
    return DataService(tmp_path)


def test_rolling_period_is_snapshot_anchored(service: DataService) -> None:
    filters = service.default_filters()
    assert filters.start_date == date(2023, 10, 1)
    assert filters.end_date == date(2026, 10, 1)
    result = service.query(QuerySpec(operation="overview"))
    assert result.rows[0]["value"] == 5
    assert result.evidence.end_date == "2026-10-01"


def test_bin_boundaries_and_severe_accidents_vs_people(service: DataService) -> None:
    result = service.query(QuerySpec(operation="ranking", group_by="segment_10km", limit=20))
    counts = {row["key"]: row["value"] for row in result.rows}
    assert counts["BR-101/ES|0"] == 1
    assert counts["BR-101/ES|10"] == 2
    assert counts["BR-116/SP|20"] == 1
    accidents = service.query(QuerySpec(operation="overview", metric="accidents_with_severe"))
    people = service.query(QuerySpec(operation="overview", metric="severe_injuries"))
    assert accidents.rows[0]["value"] == 2
    assert people.rows[0]["value"] == 5


def test_followup_restricts_same_cohort_and_snapshot(service: DataService, tmp_path: Path) -> None:
    first = service.query(QuerySpec(operation="ranking", group_by="road_uf", limit=2))
    cohort = Cohort(dimension="road_uf", keys=[str(row["key"]) for row in first.rows])
    spec = QuerySpec(operation="ranking", metric="accidents_with_severe", cohort=cohort, limit=20)
    result = service.query(spec, first.snapshot_id)
    assert {row["key"] for row in result.rows}.issubset(set(cohort.keys))
    build_snapshot(tmp_path, [source(tmp_path, [{"trecho": "BR-999/AC"}])])
    assert service.query(spec, first.snapshot_id).rows == result.rows


def test_temporal_order_and_detail_pagination(service: DataService) -> None:
    time = service.query(QuerySpec(operation="timeseries", group_by="month", limit=100))
    assert len(time.rows) == 36
    assert time.rows[0]["key"] == "2023-10"
    assert time.rows[-1]["key"] == "2026-09"
    assert time.rows[1]["value"] is None
    first = service.query(QuerySpec(operation="detail", limit=2))
    second = service.query(QuerySpec(operation="detail", limit=2, offset=2))
    assert first.row_count == second.row_count == 5
    assert len(first.rows) == len(second.rows) == 2
    assert not {row["key"] for row in first.rows} & {row["key"] for row in second.rows}


def test_comparison_zero_denominator_is_undefined(service: DataService) -> None:
    result = service.query(
        QuerySpec(
            operation="comparison",
            group_by="road_uf",
            limit=20,
            filters=Filters(start_date=date(2026, 9, 1), end_date=date(2026, 10, 1)),
        )
    )
    assert all(row["previous_value"] is None and row["delta_pct"] is None for row in result.rows)


def test_comparison_explicit_period_and_real_zero_denominator(tmp_path: Path) -> None:
    build_snapshot(
        tmp_path,
        [
            source(
                tmp_path,
                [
                    {"data": "01/09/2025", "gravemente_feridos": "0"},
                    {"data": "01/09/2026", "gravemente_feridos": "2"},
                ],
            )
        ],
    )
    result = DataService(tmp_path).query(
        QuerySpec(
            operation="comparison",
            metric="accidents_with_severe",
            filters=Filters(start_date=date(2026, 9, 1), end_date=date(2026, 10, 1)),
            comparison_filters=Filters(start_date=date(2025, 9, 1), end_date=date(2025, 10, 1)),
        )
    )
    assert result.rows[0]["value"] == 1
    assert result.rows[0]["previous_value"] == 0
    assert result.rows[0]["delta_pct"] is None


def test_unknown_severity_is_not_zero_and_partial_values_warn(tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path, [source(tmp_path, [{"gravemente_feridos": ""}])])
    service = DataService(tmp_path)
    unknown = service.query(
        QuerySpec(operation="overview", metric="accidents_with_severe"), snapshot
    )
    assert unknown.rows[0]["value"] is None
    build_snapshot(
        tmp_path,
        [
            source(
                tmp_path,
                [
                    {"gravemente_feridos": ""},
                    {"gravemente_feridos": "2"},
                ],
            )
        ],
    )
    partial = service.query(QuerySpec(operation="overview", metric="accidents_with_severe"))
    assert partial.rows[0]["value"] == 1
    assert "subestimar" in " ".join(partial.evidence.warnings)


def test_invalid_uf_stays_out_of_map_keys_without_losing_total(tmp_path: Path) -> None:
    build_snapshot(tmp_path, [source(tmp_path, [{"trecho": "BR-101/XX"}])])
    service = DataService(tmp_path)
    assert service.catalog().total_accidents == 1
    assert "XX" not in service.catalog().filters["ufs"]
    assert service.query(QuerySpec(operation="ranking", group_by="uf")).rows == []


def test_unlocated_records_are_not_ranked_as_a_real_road_segment(tmp_path: Path) -> None:
    build_snapshot(
        tmp_path,
        [
            source(
                tmp_path,
                [
                    {"trecho": "Alça Sul"},
                    {"trecho": "BR-101/ES", "km": "10,000"},
                ],
            )
        ],
    )
    service = DataService(tmp_path)
    result = service.query(QuerySpec(operation="ranking", group_by="segment_10km"))
    assert result.rows == [{"key": "BR-101/ES|10", "label": "BR-101/ES · km [10, 20)", "value": 1}]
    assert "excluídas" in " ".join(result.evidence.warnings)
    assert service.catalog().total_accidents == 2


def test_active_sources_without_valid_dates_remain_in_coverage(tmp_path: Path) -> None:
    build_snapshot(
        tmp_path,
        [
            source(tmp_path, [{}], identifier="valid", family="valid"),
            source(tmp_path, [{"data": "invalid"}], identifier="invalid", family="invalid"),
        ],
    )
    service = DataService(tmp_path)
    assert service.catalog().resources == 2
    result = service.query(QuerySpec(operation="overview"))
    assert result.evidence.resources_total == 2
    assert result.evidence.resources_with_records == 1
    assert result.evidence.coverage == "partial"


def test_detail_sort_applies_before_pagination(service: DataService) -> None:
    result = service.query(QuerySpec(operation="detail", limit=2, sort="ascending"), sort_by="km")
    assert [row["km"] for row in result.rows] == [9.999, 10.0]
    with pytest.raises(ValueError, match="ordenação"):
        service.query(QuerySpec(operation="detail"), sort_by="secret DESC; DROP TABLE raw")


def test_filters_are_parameterized_and_unknown_enums_rejected(service: DataService) -> None:
    dataset = service.query(
        QuerySpec(
            operation="overview", filters=Filters(roads=["'; DROP SCHEMA analytics CASCADE; --"])
        )
    )
    assert dataset.rows[0]["value"] == 0
    assert service.catalog().total_accidents == 6
    with pytest.raises(ValidationError):
        QuerySpec(operation="ranking", group_by="read_csv('secret')")
    with pytest.raises(ValueError, match="veículo"):
        service.query(QuerySpec(operation="ranking", filters=Filters(vehicle_types=["secret"])))
    with pytest.raises(DataUnavailableError):
        service.catalog("../../secret")


def test_vehicle_categories_do_not_duplicate_non_vehicle_cohorts(service: DataService) -> None:
    result = service.query(
        QuerySpec(
            operation="overview",
            cohort=Cohort(dimension="vehicle_type", keys=["automovel", "moto"]),
        )
    )
    assert result.rows[0]["value"] == 5


def test_demo_is_explicitly_labelled(tmp_path: Path) -> None:
    create_demo(tmp_path)
    service = DataService(tmp_path)
    assert "SINTÉTICOS" in " ".join(service.catalog().warnings)
    result = service.query(QuerySpec(operation="overview"))
    assert "SINTÉTICOS" in result.evidence.source
