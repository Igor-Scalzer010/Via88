"""Small typed boundary around DuckDB's dynamically typed result rows."""

from typing import Any

import duckdb


def fetch_one(cursor: duckdb.DuckDBPyConnection) -> tuple[Any, ...]:
    """Require the single metadata row returned by scalar/aggregate SQL queries."""
    row = cursor.fetchone()
    if row is None:
        raise ValueError("A consulta não retornou a linha de metadados esperada.")
    return row
