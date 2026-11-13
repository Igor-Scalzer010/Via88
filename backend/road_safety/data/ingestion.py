"""Download original ANTT CSVs and publish a validated DuckDB snapshot atomically."""

import csv
import hashlib
import io
import json
import os
import re
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import duckdb
import httpx

from road_safety.data.db import fetch_one
from road_safety.data.models import (
    API_URL,
    CSV_COLUMNS,
    FAMILIES,
    NAME_FAMILIES,
    PEOPLE,
    SUCCESSORS,
    UF_CODES,
    VEHICLES,
    SourceFile,
)

Download = Callable[[str], bytes]


def atomic_json(path: Path, value: object) -> None:
    """Replace a JSON pointer only after its entire new contents reach disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def download_bytes(url: str) -> bytes:
    """Retry temporary HTTP failures; a permanent failure never publishes data."""
    with httpx.Client(follow_redirects=True, timeout=90) as client:
        for attempt in range(3):
            try:
                response = client.get(url)
                response.raise_for_status()
                return response.content
            except httpx.HTTPStatusError as error:
                if (
                    error.response.status_code not in (408, 429)
                    and error.response.status_code < 500
                ):
                    raise
                if attempt == 2:
                    raise
            except httpx.TransportError:
                if attempt == 2:
                    raise
            time.sleep(0.5 * 2**attempt)
    raise RuntimeError("Download retry loop exhausted")


def _name(value: str) -> str:
    value = re.sub(r"^demonstrativos? de acidentes\s*[-_]?\s*", "", value, flags=re.I)
    return " ".join(value.replace("_", " ").split()).strip()


def _family(resource_id: str, concession: str) -> str:
    normalized = unicodedata.normalize("NFKD", concession.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return FAMILIES.get(resource_id, NAME_FAMILIES.get(normalized, resource_id))


def _decode(content: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "cp1252", "latin1"):
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV encoding could not be decoded")


def select_active_sources(sources: Sequence[SourceFile]) -> list[SourceFile]:
    """Prefer verified successors; CKAN metadata refreshes cannot restore old history."""
    by_family: dict[str, list[SourceFile]] = {}
    for source in sources:
        by_family.setdefault(source.family, []).append(source)
    winners = {
        max(
            members,
            key=lambda item: (
                item.resource_id == SUCCESSORS.get(item.family),
                item.modified_at,
                item.resource_id,
            ),
        ).resource_id
        for members in by_family.values()
    }
    return [replace(source, active=source.resource_id in winners) for source in sources]


def fetch_sources(
    data_dir: Path, *, download: Download = download_bytes, force: bool = False
) -> list[SourceFile]:
    """Store exact original bytes and enough metadata to reproduce each snapshot."""
    response = json.loads(download(API_URL))
    if not isinstance(response, dict) or response.get("success") is not True:
        raise ValueError("ANTT did not return a successful resource catalog")
    resources = response.get("result", {}).get("resources", [])
    if not isinstance(resources, list):
        raise ValueError("ANTT resource catalog is invalid")
    cached: dict[str, SourceFile] = {}
    pointer = data_dir / "active.json"
    if pointer.exists():
        snapshot_id = str(json.loads(pointer.read_text(encoding="utf-8"))["snapshot_id"])
        if re.fullmatch(r"[a-zA-Z0-9_-]+", snapshot_id):
            manifest_path = data_dir / "snapshots" / snapshot_id / "manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                cached = {
                    item["resource_id"]: SourceFile(**item) for item in manifest.get("sources", [])
                }
    sources: list[SourceFile] = []
    for resource in resources:
        if str(resource.get("format", "")).upper() != "CSV":
            continue
        resource_id = str(resource["id"])
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", resource_id):
            raise ValueError("Invalid resource identifier in ANTT catalog")
        url = str(resource["url"])
        # CKAN controls these addresses; reject unrelated download hosts explicitly.
        if not url.startswith("https://dados.antt.gov.br/"):
            raise ValueError("Resource URL is outside the ANTT host")
        modified = str(resource.get("last_modified") or "")
        previous = cached.get(resource_id)
        if (
            not force
            and previous
            and previous.modified_at == modified
            and previous.url == url
            and (data_dir / previous.path).is_file()
            and hashlib.sha256((data_dir / previous.path).read_bytes()).hexdigest()
            == previous.sha256
        ):
            sources.append(previous)
            continue
        content = download(url)
        if not content:
            raise ValueError(f"Empty CSV: {resource_id}")
        _, encoding = _decode(content)
        digest = hashlib.sha256(content).hexdigest()
        relative = Path("raw") / resource_id / f"{digest}.csv"
        raw_path = data_dir / relative
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if not raw_path.exists():
            temporary = raw_path.with_suffix(f".{uuid4().hex}.tmp")
            temporary.write_bytes(content)
            os.replace(temporary, raw_path)
        concession = _name(str(resource.get("name") or resource_id))
        sources.append(
            SourceFile(
                resource_id=resource_id,
                name=str(resource.get("name") or resource_id),
                concession=concession,
                family=_family(resource_id, concession),
                url=url,
                modified_at=modified,
                sha256=digest,
                path=relative.as_posix(),
                encoding=encoding,
                downloaded_at=datetime.now(UTC).isoformat(),
            )
        )
    if not sources:
        raise ValueError("ANTT catalog contains no CSV resources")
    return select_active_sources(sources)


def _count_expression(column: str) -> str:
    value = f"trim(replace(\"{column}\", ',', '.'))"
    return (
        f"CASE WHEN regexp_full_match({value}, '[+]?[0-9]+([.]0+)?') "
        f'THEN try_cast({value} AS BIGINT) END AS "{column}"'
    )


def _reference_csv(text: str, canonical_path: Path) -> tuple[int, int, list[str], list[str]]:
    """Parse legacy CSV once and write an unambiguous, fully quoted UTF-8 intermediate."""
    total = valid_dates = 0
    first: list[str] = []
    last: list[str] = []
    date_validity: dict[str, bool] = {}
    with canonical_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(
            stream, delimiter=";", quoting=csv.QUOTE_ALL, doublequote=True, lineterminator="\n"
        )
        writer.writerow(CSV_COLUMNS)
        for row in csv.DictReader(io.StringIO(text), delimiter=";"):
            if None in row or any(
                row.get(column) is None for column in CSV_COLUMNS if column != "tipo_de_pista"
            ):
                raise ValueError("CSV row has an unexpected number of fields")
            total += 1
            values = [row.get(column) or "" for column in CSV_COLUMNS]
            writer.writerow(values)
            if total == 1:
                first = values
            last = values
            raw_date = (row.get("data") or "").strip()
            if raw_date not in date_validity:
                date_validity[raw_date] = False
                for format_string in ("%d/%m/%Y", "%d/%m/%y"):
                    try:
                        datetime.strptime(raw_date, format_string)
                        date_validity[raw_date] = True
                        break
                    except ValueError:
                        continue
            valid_dates += date_validity[raw_date]
    return total, valid_dates, first, last


def _build_database(
    build: Path, data_dir: Path, sources: Sequence[SourceFile]
) -> dict[str, object]:
    database = build / "road_safety.duckdb"
    with duckdb.connect(str(database)) as connection:
        # The database is unpublished. One transaction avoids flushing the WAL
        # after every large CSV INSERT; failures roll back before activation.
        connection.execute("BEGIN TRANSACTION")
        connection.execute("CREATE SCHEMA raw; CREATE SCHEMA staging; CREATE SCHEMA analytics")
        raw_columns = ", ".join(f'"{column}" VARCHAR' for column in CSV_COLUMNS)
        connection.execute(
            f"CREATE TABLE raw.acidentes_csv ({raw_columns}, "
            "_resource_id VARCHAR, _family VARCHAR, _concession VARCHAR, "
            "_source_row BIGINT, _sha256 VARCHAR, _is_active BOOLEAN)"
        )
        expected_profiles: dict[str, tuple[int, int, list[str], list[str]]] = {}
        for source in sources:
            original = data_dir / source.path
            content = original.read_bytes()
            if hashlib.sha256(content).hexdigest() != source.sha256:
                raise ValueError(f"Raw file checksum mismatch: {source.resource_id}")
            text = content.decode(source.encoding).lstrip("\ufeff")
            header = next(csv.reader(io.StringIO(text), delimiter=";"), [])
            required = set(CSV_COLUMNS) - {"tipo_de_pista"}
            if not required.issubset(header) or len(header) != len(set(header)):
                raise ValueError(f"Unexpected CSV columns in {source.resource_id}")
            unknown = set(header) - set(CSV_COLUMNS) - {"concessionaria"}
            if unknown:
                raise ValueError(f"Unmapped CSV columns in {source.resource_id}: {sorted(unknown)}")
            utf8 = build / f"{source.resource_id}.csv"
            expected_profiles[source.resource_id] = _reference_csv(text, utf8)
            columns = ", ".join(
                f'"{column}"' if column in header else f'NULL AS "{column}"'
                for column in CSV_COLUMNS
            )
            reader_columns = ", ".join(f"'{column}': 'VARCHAR'" for column in CSV_COLUMNS)
            connection.execute(
                f"INSERT INTO raw.acidentes_csv SELECT {columns}, ?, ?, ?, "
                "row_number() OVER (), ?, ? FROM read_csv(?, auto_detect=false, "
                "delim=';', header=true, quote='\"', escape='\"', "
                f"columns={{{reader_columns}}}, strict_mode=true)",
                [
                    source.resource_id,
                    source.family,
                    source.concession,
                    source.sha256,
                    source.active,
                    str(utf8),
                ],
            )
            # CSV auto-sniffing can otherwise select an empty quote character for
            # ANTT's mixture of quoted text and unquoted numeric columns.
            expected_count, _, first, last = expected_profiles[source.resource_id]
            sample_columns = ", ".join(f'"{column}"' for column in CSV_COLUMNS)
            for row_number, expected in ((1, first), (expected_count, last)):
                if not expected_count:
                    continue
                actual = fetch_one(
                    connection.execute(
                        f"SELECT {sample_columns} FROM raw.acidentes_csv "
                        "WHERE _resource_id = ? AND _source_row = ?",
                        [source.resource_id, row_number],
                    )
                )
                if [value or "" for value in actual] != expected:
                    raise ValueError(f"CSV parser field mismatch: {source.resource_id}")
            utf8.unlink()
        count_fields = ",\n".join(_count_expression(column) for column in (*VEHICLES, *PEOPLE))
        valid_ufs = ", ".join(f"'{uf}'" for uf in UF_CODES)
        connection.execute(f"""
            CREATE TABLE staging.acidentes AS
            SELECT *,
                regexp_extract(road_uf, '^([A-Z]{{2}}-[0-9]{{3}})/([A-Z]{{2}})$', 1) AS road,
                CASE WHEN regexp_extract(road_uf,
                    '^([A-Z]{{2}}-[0-9]{{3}})/([A-Z]{{2}})$', 2) IN ({valid_ufs})
                    THEN regexp_extract(road_uf,
                    '^([A-Z]{{2}}-[0-9]{{3}})/([A-Z]{{2}})$', 2) END AS uf,
                CASE WHEN km_value >= 0 AND isfinite(km_value) THEN km_value END AS kilometer
            FROM (
                SELECT
                    CASE WHEN regexp_full_match(trim(data), '[0-9]{{1,2}}/[0-9]{{1,2}}/[0-9]{{2}}')
                        THEN try_strptime(trim(data), '%d/%m/%y')::DATE
                        ELSE try_strptime(trim(data), '%d/%m/%Y')::DATE END AS occurred_on,
                    try_cast(trim(horario) AS TIME) AS occurred_at,
                    regexp_replace(trim(n_da_ocorrencia), '[.]0+$', '') AS occurrence_number,
                    upper(regexp_replace(trim(trecho), '\\s+', '', 'g')) AS road_uf,
                    try_cast(replace(trim(km), ',', '.') AS DOUBLE) AS km_value,
                    nullif(lower(trim(tipo_de_ocorrencia)), '') AS occurrence_type,
                    nullif(lower(trim(tipo_de_acidente)), '') AS accident_type,
                    nullif(lower(trim(sentido)), '') AS direction,
                    nullif(lower(trim(tipo_de_pista)), '') AS track_type,
                    {count_fields},
                    _resource_id, _family, _concession AS concession, _source_row, _sha256
                FROM raw.acidentes_csv WHERE _is_active
            )
        """)
        actual_raw_counts = dict(
            connection.execute(
                "SELECT _resource_id, count(*) FROM raw.acidentes_csv GROUP BY ALL"
            ).fetchall()
        )
        actual_valid_counts = dict(
            connection.execute(
                "SELECT _resource_id, count(*) FILTER (WHERE occurred_on IS NOT NULL) "
                "FROM staging.acidentes GROUP BY ALL"
            ).fetchall()
        )
        for source in sources:
            expected_count, expected_valid_dates, _, _ = expected_profiles[source.resource_id]
            if actual_raw_counts.get(source.resource_id, 0) != expected_count:
                raise ValueError(f"CSV parser row-count mismatch: {source.resource_id}")
            if (
                source.active
                and actual_valid_counts.get(source.resource_id, 0) != expected_valid_dates
            ):
                raise ValueError(
                    f"CSV parser date-count mismatch: {source.resource_id}; "
                    "previous snapshot remains active"
                )
        identity_columns = [
            "occurred_on",
            "occurred_at",
            "occurrence_number",
            "road_uf",
            "km_value",
            "occurrence_type",
            "accident_type",
            "direction",
            "track_type",
            *VEHICLES,
            *PEOPLE,
            "_resource_id",
            "_family",
            "concession",
            "road",
            "uf",
            "kilometer",
        ]
        partition = ", ".join(f'"{column}"' for column in identity_columns)
        suspicious = fetch_one(
            connection.execute("""
            SELECT count(*) FROM (
                SELECT occurred_on, occurred_at, occurrence_number, road_uf, kilometer
                FROM staging.acidentes WHERE occurred_on IS NOT NULL
                    AND occurrence_number IS NOT NULL
                GROUP BY ALL HAVING count(DISTINCT _family) > 1
            )
        """)
        )[0]
        if suspicious:
            raise ValueError(
                f"{suspicious} possible cross-resource overlaps require an explicit alias family; "
                "previous snapshot remains active"
            )
        connection.execute("""
            CREATE TABLE staging.rejected AS
            SELECT *, 'invalid_date' AS rejection_reason
            FROM staging.acidentes WHERE occurred_on IS NULL
        """)
        # Exact duplicates are removed deterministically. Conflicting business keys
        # remain visible and are reported; silently picking a row would hide evidence.
        connection.execute(f"""
            CREATE TABLE analytics.acidentes AS
            SELECT * EXCLUDE (_duplicate_order),
                sha256(concat_ws('|', _family, occurred_on::VARCHAR,
                    coalesce(occurrence_number, ''), coalesce(occurred_at::VARCHAR, ''),
                    road_uf, coalesce(kilometer::VARCHAR, ''),
                    _source_row::VARCHAR)) AS accident_id,
                floor(kilometer / 10)::BIGINT * 10 AS segment_start,
                concat(road_uf, '|', (floor(kilometer / 10)::BIGINT * 10)::VARCHAR)
                    AS segment_key
            FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY {partition}
                    ORDER BY _source_row
                ) AS _duplicate_order
                FROM staging.acidentes WHERE occurred_on IS NOT NULL
            ) WHERE _duplicate_order = 1
        """)
        connection.execute("""
            CREATE TABLE analytics.coverage AS
            SELECT _resource_id, _family, concession,
                date_trunc('month', occurred_on)::DATE AS month, count(*) AS records
            FROM analytics.acidentes GROUP BY ALL
        """)
        row_count = int(
            fetch_one(connection.execute("SELECT count(*) FROM analytics.acidentes"))[0]
        )
        if not row_count:
            raise ValueError("No valid accident records; previous snapshot remains active")
        rejected = int(fetch_one(connection.execute("SELECT count(*) FROM staging.rejected"))[0])
        active_rows = int(
            fetch_one(connection.execute("SELECT count(*) FROM staging.acidentes"))[0]
        )
        collisions = int(
            fetch_one(
                connection.execute("""
            SELECT count(*) FROM (
                SELECT _family, occurred_on, occurrence_number FROM analytics.acidentes
                WHERE occurrence_number IS NOT NULL
                GROUP BY ALL HAVING count(*) > 1
            )
        """)
            )[0]
        )
        invalid_counts = {
            column: int(
                fetch_one(
                    connection.execute(
                        f'SELECT count(*) FROM staging.acidentes WHERE "{column}" IS NULL'
                    )
                )[0]
            )
            for column in (*VEHICLES, *PEOPLE)
        }
        invalid_km = int(
            fetch_one(
                connection.execute("SELECT count(*) FROM staging.acidentes WHERE kilometer IS NULL")
            )[0]
        )
        unknown_roads = int(
            fetch_one(
                connection.execute(
                    "SELECT count(*) FROM staging.acidentes "
                    "WHERE coalesce(road, '') = '' OR coalesce(uf, '') = ''"
                )
            )[0]
        )
        connection.execute("COMMIT")
        connection.execute("CHECKPOINT")
    return {
        "records": row_count,
        "rejected_dates": rejected,
        "exact_duplicates": active_rows - rejected - row_count,
        "business_key_collisions": collisions,
        "missing_or_invalid_counts": invalid_counts,
        "missing_or_invalid_km": invalid_km,
        "unknown_road_uf": unknown_roads,
    }


def build_snapshot(
    data_dir: Path,
    sources: Sequence[SourceFile],
    *,
    synthetic: bool = False,
    publish: Callable[[Path, object], None] = atomic_json,
) -> str:
    """Publish a complete immutable database, keeping the previous pointer on failure."""
    sources = select_active_sources(sources)
    snapshot_id = (
        f"{'demo' if synthetic else 'antt'}_{datetime.now(UTC):%Y%m%dT%H%M%S}_{uuid4().hex[:8]}"
    )
    snapshots = data_dir / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    build = snapshots / f".build-{snapshot_id}"
    build.mkdir()
    quality = _build_database(build, data_dir, sources)
    atomic_json(
        build / "manifest.json",
        {
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "created_at": datetime.now(UTC).isoformat(),
            "synthetic": synthetic,
            "source_url": API_URL,
            "sources": [source.as_dict() for source in sources],
            "quality": quality,
        },
    )
    destination = snapshots / snapshot_id
    os.replace(build, destination)
    publish(data_dir / "active.json", {"snapshot_id": snapshot_id})
    return snapshot_id


def ingest(data_dir: Path, *, download: Download = download_bytes, force: bool = False) -> str:
    """Fetch all originals, validate transformations, then atomically activate a snapshot."""
    data_dir.mkdir(parents=True, exist_ok=True)
    return build_snapshot(data_dir, fetch_sources(data_dir, download=download, force=force))
