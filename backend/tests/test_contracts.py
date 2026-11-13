"""Public contract boundary checks, independent of the model provider."""

from datetime import date

import pytest
from pydantic import TypeAdapter, ValidationError

from road_safety.contracts import ChatRequest, Filters, QuerySpec, Widget


def test_only_declared_widgets_and_properties_are_accepted() -> None:
    adapter = TypeAdapter(Widget)
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {"id": "x", "type": "react", "title": "X", "dataset_id": "d", "jsx": "x"}
        )
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {"id": "x", "type": "metric", "title": "X", "dataset_id": "d", "code": "x"}
        )


def test_sql_is_not_a_public_query_operation() -> None:
    with pytest.raises(ValidationError):
        QuerySpec.model_validate({"operation": "sql", "sql": "SELECT * FROM raw.data"})
    with pytest.raises(ValidationError):
        QuerySpec.model_validate({"operation": "ranking", "group_by": "read_csv('x')"})


def test_filter_ranges_have_exclusive_nonempty_end() -> None:
    with pytest.raises(ValidationError):
        Filters(start_date=date(2025, 1, 1), end_date=date(2025, 1, 1))
    with pytest.raises(ValidationError):
        Filters(km_min=10, km_max=10)
    assert Filters(km_min=0, km_max=10).km_min == 0


def test_bounded_requests_and_identifiers() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="x", session_id="../other", request_id="a")
    with pytest.raises(ValidationError):
        QuerySpec(operation="ranking", limit=101)
    with pytest.raises(ValidationError):
        ChatRequest(message="x" * 4001, session_id="a", request_id="a")
