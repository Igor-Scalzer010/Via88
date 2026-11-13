"""Expose typed analytical commands without granting database programming access."""

from langchain_core.tools import BaseTool, tool

from road_safety.contracts import Contract, QuerySpec
from road_safety.data.service import DataService


class QueryCommand(Contract):
    spec: QuerySpec


def build_query_tool(service: DataService, snapshot_id: str) -> BaseTool:
    @tool(args_schema=QueryCommand)
    def query_accidents(spec: QuerySpec) -> dict[str, object]:
        """Run a validated ranking, time series, distribution, comparison or detail query."""
        validated = QuerySpec.model_validate(spec)
        return service.query(validated, snapshot_id).model_dump(mode="json")

    return query_accidents
