"""Read-only analytical service; callers select capabilities, never SQL text."""

import calendar
import hashlib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

import duckdb

from road_safety.contracts import Catalog, Column, Dataset, Evidence, Filters, QuerySpec, Scalar
from road_safety.data.db import fetch_one
from road_safety.data.models import VEHICLES

METRICS = {
    "accidents": ("count(*)", "Acidentes", "Número de ocorrências registradas."),
    "accidents_with_severe": (
        "CASE WHEN count(gravemente_feridos) = 0 THEN NULL "
        "ELSE count(*) FILTER (WHERE gravemente_feridos > 0) END",
        "Acidentes com vítimas graves",
        "Ocorrências com pelo menos uma pessoa gravemente ferida; não é o número de vítimas.",
    ),
    "severe_injuries": (
        "sum(gravemente_feridos)",
        "Vítimas graves",
        "Soma das pessoas gravemente feridas.",
    ),
    "deaths": ("sum(mortos)", "Mortes", "Soma dos óbitos registrados nas ocorrências."),
    "injuries": (
        "sum(levemente_feridos + moderadamente_feridos + gravemente_feridos)",
        "Pessoas feridas",
        "Soma de feridos leves, moderados e graves, sem incluir óbitos.",
    ),
}
DIMENSIONS: dict[str, tuple[str, str]] = {
    "road": (
        "coalesce(nullif(road, ''), 'unknown')",
        "coalesce(nullif(road, ''), 'Não informado')",
    ),
    "road_uf": (
        "coalesce(nullif(road_uf, ''), 'unknown')",
        "coalesce(nullif(road_uf, ''), 'Não informado')",
    ),
    "segment_10km": (
        "CASE WHEN kilometer IS NOT NULL THEN segment_key ELSE 'unknown' END",
        "CASE WHEN kilometer IS NOT NULL THEN concat(road_uf, ' · km [', "
        "segment_start::VARCHAR, ', ', (segment_start + 10)::VARCHAR, ')') "
        "ELSE 'Não informado' END",
    ),
    "uf": ("coalesce(nullif(uf, ''), 'unknown')", "coalesce(nullif(uf, ''), 'Não informado')"),
    "concession": ("concession", "concession"),
    "accident_type": (
        "coalesce(accident_type, 'unknown')",
        "coalesce(accident_type, 'Não informado')",
    ),
    "direction": ("coalesce(direction, 'unknown')", "coalesce(direction, 'Não informado')"),
    "track_type": ("coalesce(track_type, 'unknown')", "coalesce(track_type, 'Não informado')"),
    "month": ("strftime(occurred_on, '%Y-%m')", "strftime(occurred_on, '%Y-%m')"),
    "year": ("year(occurred_on)::VARCHAR", "year(occurred_on)::VARCHAR"),
    "weekday": (
        "isodow(occurred_on)::VARCHAR",
        "list_extract(['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', "
        "'Sexta-feira', 'Sábado', 'Domingo'], isodow(occurred_on)::BIGINT)",
    ),
    "hour": (
        "CASE WHEN occurred_at IS NULL THEN 'unknown' ELSE "
        "lpad(hour(occurred_at)::VARCHAR, 2, '0') END",
        "CASE WHEN occurred_at IS NULL THEN 'Não informado' ELSE "
        "concat(lpad(hour(occurred_at)::VARCHAR, 2, '0'), ':00') END",
    ),
    "vehicle_type": ("vehicle_type", "vehicle_type"),
}
FILTER_COLUMNS = {
    "roads": "road",
    "ufs": "uf",
    "concessions": "concession",
    "accident_types": "accident_type",
    "directions": "direction",
    "track_types": "track_type",
}
SPATIAL_VALID = {
    "road": "nullif(road, '') IS NOT NULL",
    "road_uf": "nullif(road, '') IS NOT NULL AND uf IS NOT NULL",
    "uf": "uf IS NOT NULL",
    "segment_10km": ("nullif(road, '') IS NOT NULL AND uf IS NOT NULL AND kilometer IS NOT NULL"),
}
GEOGRAPHY_PATH = "geography/ufs.geojson"


class DataUnavailableError(ValueError):
    """No validated snapshot is available for this operation."""


def _subtract_months(value: date, months: int) -> date:
    total = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _scalar(value: object) -> Scalar:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _active_sources(manifest: dict[str, object]) -> list[dict[str, object]]:
    values = manifest.get("sources", [])
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict) and value.get("active") is True]


class DataService:
    """Open independent immutable DuckDB readers for each bounded request."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir.resolve()

    def _snapshot(self, snapshot_id: str | None = None) -> tuple[str, Path]:
        if snapshot_id is None:
            pointer = self.data_dir / "active.json"
            if not pointer.is_file():
                raise DataUnavailableError("Importe os dados da ANTT antes de consultar o painel.")
            try:
                snapshot_id = str(json.loads(pointer.read_text(encoding="utf-8"))["snapshot_id"])
            except (ValueError, KeyError) as error:
                raise DataUnavailableError("O ponteiro do snapshot está inválido.") from error
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", snapshot_id):
            raise DataUnavailableError("Identificador de snapshot inválido.")
        directory = self.data_dir / "snapshots" / snapshot_id
        if (
            not (directory / "road_safety.duckdb").is_file()
            or not (directory / "manifest.json").is_file()
        ):
            raise DataUnavailableError("O snapshot solicitado não está disponível.")
        return snapshot_id, directory

    @contextmanager
    def _connect(self, directory: Path) -> Iterator[duckdb.DuckDBPyConnection]:
        # Disable filesystem/network table functions for the entire query connection.
        connection = duckdb.connect(
            str(directory / "road_safety.duckdb"),
            read_only=True,
            config={"enable_external_access": "false", "threads": "2", "memory_limit": "512MB"},
        )
        try:
            yield connection
        finally:
            connection.close()

    def default_filters(self, snapshot_id: str | None = None) -> Filters:
        """Use a rolling 36-month window ending just after the last observed day."""
        _, directory = self._snapshot(snapshot_id)
        with self._connect(directory) as connection:
            maximum = fetch_one(
                connection.execute("SELECT max(occurred_on) FROM analytics.acidentes")
            )[0]
        end = maximum + timedelta(days=1)
        return Filters(start_date=_subtract_months(end, 36), end_date=end)

    def catalog(self, snapshot_id: str | None = None) -> Catalog:
        try:
            identifier, directory = self._snapshot(snapshot_id)
        except DataUnavailableError:
            if snapshot_id is not None:
                raise
            return Catalog(available=False, warnings=["Nenhum snapshot importado."])
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        with self._connect(directory) as connection:
            minimum, maximum, total = fetch_one(
                connection.execute(
                    "SELECT min(occurred_on), max(occurred_on), count(*) FROM analytics.acidentes"
                )
            )
            filters = {
                name: [
                    str(row[0])
                    for row in connection.execute(
                        f"SELECT DISTINCT {column} FROM analytics.acidentes "
                        f"WHERE {column} IS NOT NULL AND {column} != '' ORDER BY 1"
                    ).fetchall()
                ]
                for name, column in FILTER_COLUMNS.items()
            }
            filters["vehicle_types"] = list(VEHICLES)
            coverage_rows = connection.execute("""
                SELECT _resource_id, concession, min(occurred_on), max(occurred_on), count(*),
                    count(DISTINCT date_trunc('month', occurred_on))
                FROM analytics.acidentes GROUP BY ALL ORDER BY concession
            """).fetchall()
        coverage: list[dict[str, Scalar]] = [
            {
                "resource_id": row[0],
                "concession": row[1],
                "start_date": str(row[2]),
                "end_date": str(row[3]),
                "records": row[4],
                "observed_months": row[5],
            }
            for row in coverage_rows
        ]
        warnings = self._quality_warnings(manifest)
        active_sources = _active_sources(manifest)
        represented = {row[0] for row in coverage_rows}
        for source in active_sources:
            if source["resource_id"] not in represented:
                coverage.append(
                    {
                        "resource_id": str(source["resource_id"]),
                        "concession": str(source["concession"]),
                        "start_date": None,
                        "end_date": None,
                        "records": 0,
                        "observed_months": 0,
                    }
                )
                warnings.append(
                    f"{source['concession']}: recurso ativo sem ocorrências com data válida."
                )
        warnings.append(
            "A base cobre rodovias concedidas informadas à ANTT; não representa todas as rodovias "
            "do Brasil. Presença de registros não comprova completude."
        )
        return Catalog(
            available=True,
            snapshot_id=identifier,
            min_date=str(minimum),
            max_date=str(maximum),
            total_accidents=total,
            resources=len(active_sources),
            filters=filters,
            warnings=warnings,
            coverage=coverage,
        )

    @staticmethod
    def _quality_warnings(manifest: dict[str, object]) -> list[str]:
        warnings = []
        if manifest.get("synthetic"):
            warnings.append("DADOS SINTÉTICOS DE DEMONSTRAÇÃO — não são ocorrências reais da ANTT.")
        quality = manifest.get("quality", {})
        if isinstance(quality, dict):
            for key, text in (
                ("rejected_dates", "registros excluídos da análise por data inválida"),
                ("exact_duplicates", "duplicatas exatas removidas"),
                (
                    "business_key_collisions",
                    "chaves de ocorrência com registros divergentes preservados",
                ),
                (
                    "missing_or_invalid_km",
                    "registros sem km válido; indisponíveis para faixas de 10 km",
                ),
                ("unknown_road_uf", "registros com rodovia/UF não reconhecida"),
            ):
                count = quality.get(key, 0)
                if count:
                    warnings.append(f"{count} {text}.")
            counts = quality.get("missing_or_invalid_counts", {})
            if isinstance(counts, dict) and any(counts.values()):
                warnings.append(
                    "Existem contagens ausentes ou inválidas; valores desconhecidos não foram "
                    "convertidos em zero."
                )
        return warnings

    @staticmethod
    def _where(spec: QuerySpec) -> tuple[str, list[object]]:
        filters = spec.filters
        clauses = ["occurred_on >= ?", "occurred_on < ?"]
        parameters: list[object] = [filters.start_date, filters.end_date]
        for attribute, column in FILTER_COLUMNS.items():
            values = getattr(filters, attribute)
            if values:
                clauses.append(f"{column} IN ({','.join('?' for _ in values)})")
                parameters.extend(values)
        if filters.km_min is not None:
            clauses.append("kilometer >= ?")
            parameters.append(filters.km_min)
        if filters.km_max is not None:
            clauses.append("kilometer < ?")
            parameters.append(filters.km_max)
        severity = {
            "with_severe": "gravemente_feridos > 0",
            "with_deaths": "mortos > 0",
            "with_injuries": "(levemente_feridos > 0 OR moderadamente_feridos > 0 "
            "OR gravemente_feridos > 0)",
        }.get(filters.severity)
        if severity:
            clauses.append(severity)
        if filters.vehicle_types:
            if any(vehicle not in VEHICLES for vehicle in filters.vehicle_types):
                raise ValueError("Tipo de veículo desconhecido.")
            clauses.append(
                "(" + " OR ".join(f'"{item}" > 0' for item in filters.vehicle_types) + ")"
            )
        if spec.cohort:
            if spec.cohort.dimension == "vehicle_type" and not (
                spec.group_by == "vehicle_type" and spec.operation not in ("overview", "detail")
            ):
                if any(key not in VEHICLES for key in spec.cohort.keys):
                    raise ValueError("Tipo de veículo desconhecido na coorte.")
                clauses.append("(" + " OR ".join(f'"{key}" > 0' for key in spec.cohort.keys) + ")")
            else:
                expression = DIMENSIONS[spec.cohort.dimension][0]
                clauses.append(f"{expression} IN ({','.join('?' for _ in spec.cohort.keys)})")
                parameters.extend(spec.cohort.keys)
        return " AND ".join(clauses), parameters

    def query(
        self, spec: QuerySpec, snapshot_id: str | None = None, *, sort_by: str | None = None
    ) -> Dataset:
        """Execute an allowlisted aggregate or paginated detail query with provenance."""
        # Revalidation also protects direct Python callers using model_construct().
        spec = QuerySpec.model_validate(spec.model_dump())
        identifier, directory = self._snapshot(snapshot_id)
        defaults = self.default_filters(identifier)
        filters = Filters.model_validate(
            {
                **spec.filters.model_dump(),
                "start_date": spec.filters.start_date or defaults.start_date,
                "end_date": spec.filters.end_date or defaults.end_date,
            }
        )
        spec = spec.model_copy(update={"filters": filters})
        if spec.operation == "timeseries":
            # Temporal series should contain the entire bounded requested interval;
            # the ranking-oriented default of five must not truncate six years.
            spec = spec.model_copy(update={"limit": 100, "offset": 0})
        start_date, end_date = filters.start_date, filters.end_date
        if start_date is None or end_date is None:
            raise ValueError("O período da consulta é obrigatório.")
        if spec.operation == "timeseries" and spec.group_by not in (
            "month",
            "year",
            "weekday",
            "hour",
        ):
            raise ValueError("Série temporal requer mês, ano, dia da semana ou hora.")
        # A vehicle breakdown counts involvements: an accident can involve more
        # than one vehicle category. Its buckets are never additive accident totals.
        vehicle_breakdown = spec.group_by == "vehicle_type" and spec.operation not in (
            "overview",
            "detail",
        )
        vehicle_values = ", ".join(f"('{vehicle}', {vehicle})" for vehicle in VEHICLES)
        source = "analytics.acidentes"
        if vehicle_breakdown:
            source += (
                f" CROSS JOIN LATERAL (VALUES {vehicle_values}) v(vehicle_type, vehicle_count)"
            )
        where, parameters = self._where(spec)
        if vehicle_breakdown:
            where += " AND vehicle_count > 0"
        aggregate, title, definition = METRICS[spec.metric]
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        warnings = self._quality_warnings(manifest)
        comparison_partial = False
        with self._connect(directory) as connection:
            spatial_condition = (
                SPATIAL_VALID.get(spec.group_by)
                if spec.operation in ("ranking", "distribution", "comparison")
                else None
            )
            spatial_excluded = 0
            if spatial_condition:
                spatial_excluded = fetch_one(
                    connection.execute(
                        f"SELECT count(*) FROM {source} WHERE {where} "
                        f"AND NOT ({spatial_condition})",
                        parameters,
                    )
                )[0]
                where += f" AND ({spatial_condition})"
                if spatial_excluded:
                    warnings.append(
                        f"{spatial_excluded} ocorrências sem localização válida para esta dimensão "
                        "foram excluídas do resultado espacial; permanecem nos totais globais."
                    )
            matched, resources = fetch_one(
                connection.execute(
                    f"SELECT count(DISTINCT accident_id), count(DISTINCT _resource_id) "
                    f"FROM {source} WHERE {where}",
                    parameters,
                )
            )
            if spec.operation == "detail":
                allowed_sort = {
                    "key",
                    "data",
                    "horario",
                    "trecho",
                    "km",
                    "concessionaria",
                    "tipo_de_acidente",
                    "sentido",
                    "gravemente_feridos",
                    "mortos",
                    "resource_id",
                    "source_row",
                }
                if sort_by is not None and sort_by not in allowed_sort:
                    raise ValueError("Coluna de ordenação desconhecida.")
                ordering = sort_by or "data"
                select = (
                    "accident_id AS key, occurred_on AS data, occurred_at::VARCHAR AS horario, "
                    "road_uf AS trecho, kilometer AS km, concession AS concessionaria, "
                    "accident_type AS tipo_de_acidente, direction AS sentido, "
                    "gravemente_feridos, mortos, _resource_id AS resource_id, "
                    "_source_row AS source_row"
                )
                cursor = connection.execute(
                    f"SELECT DISTINCT {select} FROM {source} WHERE {where} "
                    f"ORDER BY {ordering} {'ASC' if spec.sort == 'ascending' else 'DESC'} "
                    "NULLS LAST, key LIMIT ? OFFSET ?",
                    [*parameters, spec.limit, spec.offset],
                )
                names = [description[0] for description in cursor.description]
                rows = [
                    dict(zip(names, (_scalar(value) for value in row), strict=True))
                    for row in cursor.fetchall()
                ]
                columns = [
                    Column(
                        key=name,
                        label=name.replace("_", " ").capitalize(),
                        data_type="number"
                        if name in ("km", "gravemente_feridos", "mortos", "source_row")
                        else "date"
                        if name == "data"
                        else "string",
                        format="number"
                        if name in ("km", "gravemente_feridos", "mortos", "source_row")
                        else "text",
                    )
                    for name in names
                ]
                row_count = matched
            elif spec.operation == "overview":
                value = fetch_one(
                    connection.execute(
                        f"SELECT {aggregate} FROM {source} WHERE {where}",
                        parameters,
                    )
                )[0]
                rows = [{"key": spec.metric, "label": title, "value": _scalar(value)}]
                columns = self._aggregate_columns()
                row_count = 1
            else:
                key, label = DIMENSIONS[spec.group_by]
                order = (
                    "key ASC"
                    if spec.operation == "timeseries"
                    else (
                        "value ASC NULLS LAST, key ASC"
                        if spec.sort == "ascending"
                        else "value DESC NULLS LAST, key ASC"
                    )
                )
                grouped = (
                    f"SELECT {key} AS key, {label} AS label, {aggregate} AS value "
                    f"FROM {source} WHERE {where} GROUP BY ALL"
                )
                if spec.operation == "comparison":
                    duration = end_date - start_date
                    if spec.comparison_filters is not None:
                        comparison = spec.comparison_filters
                        if comparison.start_date is None or comparison.end_date is None:
                            raise ValueError(
                                "Informe início e fim exclusivos do período de comparação."
                            )
                        previous_filters = comparison
                    else:
                        previous_filters = filters.model_copy(
                            update={
                                "start_date": start_date - duration,
                                "end_date": start_date,
                            }
                        )
                    previous_start = previous_filters.start_date
                    previous_end = previous_filters.end_date
                    if previous_start is None or previous_end is None:
                        raise ValueError("O período de comparação é obrigatório.")
                    previous_spec = spec.model_copy(update={"filters": previous_filters})
                    previous_where, previous_parameters = self._where(previous_spec)
                    if vehicle_breakdown:
                        previous_where += " AND vehicle_count > 0"
                    if spatial_condition:
                        previous_where += f" AND ({spatial_condition})"
                    previous_grouped = (
                        f"SELECT {key} AS key, {label} AS label, {aggregate} AS value "
                        f"FROM {source} WHERE {previous_where} GROUP BY ALL"
                    )
                    previous_observed = fetch_one(
                        connection.execute(
                            f"SELECT count(*) FROM {source} WHERE {previous_where}",
                            previous_parameters,
                        )
                    )[0]
                    grouped = f"""
                        WITH current_result AS ({grouped}), previous_result AS ({previous_grouped}),
                        combined AS (
                            SELECT coalesce(c.key, p.key) AS key,
                                coalesce(c.label, p.label) AS label,
                                c.value AS value, p.value AS previous_value
                            FROM current_result c FULL OUTER JOIN previous_result p ON c.key = p.key
                        )
                        SELECT *, CASE WHEN previous_value > 0
                            THEN 100.0 * (value - previous_value) / previous_value END AS delta_pct
                        FROM combined
                    """
                    parameters = [*parameters, *previous_parameters]
                    warnings.append(
                        f"Período de referência da comparação: "
                        f"[{previous_filters.start_date}, {previous_filters.end_date}). "
                        "Variação percentual fica indefinida quando o valor anterior é zero."
                    )
                    if not previous_observed:
                        comparison_partial = True
                        warnings.append(
                            "Não há observações no recorte de referência; "
                            "valor anterior e variação permanecem desconhecidos, não zero."
                        )
                    reference_min, reference_max = fetch_one(
                        connection.execute(
                            "SELECT min(occurred_on), max(occurred_on) FROM analytics.acidentes"
                        )
                    )
                    if (
                        previous_start < reference_min
                        or previous_end - timedelta(days=1) > reference_max
                    ):
                        comparison_partial = True
                        warnings.append(
                            "O período de referência ultrapassa as datas observadas no snapshot; "
                            "não é possível concluir uma variação completa entre períodos."
                        )
                row_count = fetch_one(
                    connection.execute(f"SELECT count(*) FROM ({grouped})", parameters)
                )[0]
                result = connection.execute(
                    f"{grouped} ORDER BY {order} LIMIT ? OFFSET ?",
                    [*parameters, spec.limit, spec.offset],
                ).fetchall()
                rows = [
                    {"key": str(row[0]), "label": str(row[1]), "value": _scalar(row[2])}
                    for row in result
                ]
                columns = self._aggregate_columns()
                if spec.operation == "comparison":
                    for row, result_row in zip(rows, result, strict=True):
                        row["previous_value"] = _scalar(result_row[3])
                        row["delta_pct"] = _scalar(result_row[4])
                    columns.extend(
                        [
                            Column(
                                key="previous_value",
                                label="Período anterior",
                                data_type="number",
                                format="number",
                            ),
                            Column(
                                key="delta_pct",
                                label="Variação (%)",
                                data_type="number",
                                format="number",
                            ),
                        ]
                    )
            # Only geography/concession selectors constrain expected sources. A
            # source without severe crashes must not be described as missing data.
            coverage_clauses = []
            coverage_parameters: list[object] = []
            for attribute in ("roads", "ufs", "concessions"):
                values = getattr(filters, attribute)
                if values:
                    coverage_clauses.append(
                        f"{FILTER_COLUMNS[attribute]} IN ({','.join('?' for _ in values)})"
                    )
                    coverage_parameters.extend(values)
            coverage_where = " WHERE " + " AND ".join(coverage_clauses) if coverage_clauses else ""
            coverage_rows = connection.execute(
                "SELECT _resource_id, concession, min(occurred_on), max(occurred_on), "
                "count(DISTINCT date_trunc('month', occurred_on)) "
                f"FROM analytics.acidentes{coverage_where} GROUP BY ALL "
                "ORDER BY _resource_id, concession",
                coverage_parameters,
            ).fetchall()
            # Comparison has a second set of parameters solely inside its CTE.
            _, current_parameters = self._where(spec)
            missing_counts = fetch_one(
                connection.execute(
                    f"SELECT count(*) FILTER (WHERE gravemente_feridos IS NULL), "
                    "count(*) FILTER (WHERE mortos IS NULL), "
                    "count(*) FILTER (WHERE levemente_feridos IS NULL "
                    "OR moderadamente_feridos IS NULL OR gravemente_feridos IS NULL) "
                    f"FROM {source} WHERE {where}",
                    current_parameters,
                )
            )
            months = connection.execute(
                "SELECT _resource_id, month FROM analytics.coverage "
                "WHERE month >= date_trunc('month', ?::DATE) AND month < ?",
                [start_date, end_date],
            ).fetchall()
            valid_resource_ids = {
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT _resource_id FROM analytics.acidentes"
                ).fetchall()
            }
        active_sources = _active_sources(manifest)
        expected_ids = {row[0] for row in coverage_rows}
        missing_sources = [
            source
            for source in active_sources
            if source["resource_id"] not in valid_resource_ids
            and (not filters.concessions or source["concession"] in filters.concessions)
        ]
        expected_ids.update(str(source["resource_id"]) for source in missing_sources)
        partial = bool(missing_sources) or comparison_partial or bool(spatial_excluded)
        for descriptor in missing_sources:
            warnings.append(
                f"{descriptor['concession']}: recurso ativo sem registros com data válida; "
                "cobertura desconhecida."
            )
        observed_months: dict[str, set[date]] = {}
        for resource_id, month in months:
            observed_months.setdefault(resource_id, set()).add(month)
        for resource_id, concession, minimum, maximum, _ in coverage_rows:
            if minimum > start_date or maximum < end_date - timedelta(days=1):
                partial = True
                if len(warnings) < 12:
                    warnings.append(
                        f"{concession}: registros observados de {minimum} a {maximum}; "
                        "cobertura parcial do período solicitado."
                    )
            first = max(minimum.replace(day=1), start_date.replace(day=1))
            last = min(maximum.replace(day=1), (end_date - timedelta(days=1)).replace(day=1))
            missing_months = []
            while first <= last:
                if first not in observed_months.get(resource_id, set()):
                    missing_months.append(first.isoformat()[:7])
                first = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
            if missing_months:
                partial = True
                if len(warnings) < 12:
                    warnings.append(
                        f"{concession}: {len(missing_months)} meses sem registros observados "
                        f"no período ({', '.join(missing_months[:5])})."
                    )
        if partial:
            warnings.append(
                "Datas sem registros podem refletir ausência de reporte; "
                "não são automaticamente zero acidentes."
            )
        if (
            spec.metric in ("severe_injuries", "accidents_with_severe", "injuries")
            and missing_counts[0]
        ):
            partial = True
            warnings.append(
                f"{missing_counts[0]} ocorrências sem contagem de vítimas graves; "
                "o valor conhecido é um mínimo confirmado e pode subestimar a gravidade."
            )
        if spec.metric == "deaths" and missing_counts[1]:
            partial = True
            warnings.append("Há ocorrências sem contagem de óbitos; a soma pode estar incompleta.")
        if spec.metric == "injuries" and missing_counts[2]:
            partial = True
            warnings.append(
                "A soma de feridos considera apenas ocorrências com contagens leves, "
                "moderadas e graves conhecidas; valores ausentes não são zero."
            )
        if vehicle_breakdown:
            warnings.append(
                "Categorias veiculares podem compartilhar a mesma ocorrência; "
                "não some as barras como total de acidentes."
            )
        if spec.operation == "timeseries" and spec.group_by in ("month", "year"):
            by_key = {str(row["key"]): row for row in rows}
            last_day = end_date - timedelta(days=1)
            if spec.group_by == "month":
                first_index = start_date.year * 12 + start_date.month - 1
                row_count = (last_day.year * 12 + last_day.month - 1) - first_index + 1
                keys = [
                    f"{(first_index + i) // 12:04}-{(first_index + i) % 12 + 1:02}"
                    for i in range(min(row_count, 100))
                ]
            else:
                row_count = last_day.year - start_date.year + 1
                keys = [str(start_date.year + i) for i in range(min(row_count, 100))]
            rows = [by_key.get(key, {"key": key, "label": key, "value": None}) for key in keys]
            if any(row["value"] is None for row in rows):
                warnings.append(
                    "Lacunas temporais são exibidas como desconhecidas (null), "
                    "sem preencher ausência de observações com zero."
                )
        if row_count > len(rows):
            warnings.append(
                f"Exibidos {len(rows)} de {row_count} resultados; há paginação ou limite aplicado."
            )
        if spec.operation != "detail":
            row_count = len(rows)
        coverage_status: Literal["observed", "partial", "none"] = (
            "none" if not matched else "partial" if partial else "observed"
        )
        if spec.operation != "detail" and not any(
            isinstance(row.get("value"), (int, float)) for row in rows
        ):
            coverage_status = "none"
            warnings.append(
                "A métrica solicitada não tem valores conhecidos suficientes neste recorte."
            )
        evidence = Evidence(
            snapshot_id=identifier,
            source="DADOS SINTÉTICOS DE DEMONSTRAÇÃO"
            if manifest.get("synthetic")
            else "ANTT — Acidentes em rodovias federais concedidas",
            start_date=str(filters.start_date),
            end_date=str(filters.end_date),
            metric=spec.metric,
            definition=definition,
            matched_rows=matched,
            resources_with_records=resources,
            resources_total=len(expected_ids),
            coverage=coverage_status,
            warnings=warnings,
        )
        digest = hashlib.sha256((identifier + spec.model_dump_json()).encode()).hexdigest()[:20]
        return Dataset(
            id=f"dataset_{digest}",
            snapshot_id=identifier,
            title=title,
            columns=columns,
            rows=rows,
            row_count=row_count,
            query=spec,
            evidence=evidence,
        )

    @staticmethod
    def _aggregate_columns() -> list[Column]:
        return [
            Column(key="key", label="Identificador"),
            Column(key="label", label="Categoria"),
            Column(key="value", label="Valor", data_type="number", format="number"),
        ]

    def geography(self) -> dict[str, object]:
        path = self.data_dir / GEOGRAPHY_PATH
        if not path.is_file():
            raise DataUnavailableError(
                "Execute road-safety geography para baixar a malha de UFs do IBGE."
            )
        result = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or result.get("type") != "FeatureCollection":
            raise DataUnavailableError("Malha geográfica inválida.")
        return result
