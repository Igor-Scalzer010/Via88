"""Pipeline invariants: originals, alias corrections, quarantine and atomic publication."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import duckdb
import pytest
from fixtures.data_helpers import source

from road_safety.contracts import Filters, QuerySpec
from road_safety.data import ingestion
from road_safety.data.ingestion import build_snapshot, fetch_sources, select_active_sources
from road_safety.data.models import API_URL
from road_safety.data.service import DataService


def test_alias_successor_replaces_corrected_history(tmp_path: Path) -> None:
    old = source(
        tmp_path, [{"horario": "00:00:00", "ilesos": "0"}], identifier="old", family="alias"
    )
    new = source(
        tmp_path,
        [{"horario": "07:33:00", "ilesos": "1"}],
        identifier="new",
        family="alias",
        modified="2026-10-01",
    )
    snapshot = build_snapshot(tmp_path, [old, new])
    service = DataService(tmp_path)
    assert service.catalog().total_accidents == 1
    dataset = service.query(QuerySpec(operation="detail"))
    assert dataset.rows[0]["horario"] == "07:33:00"
    with duckdb.connect(
        str(tmp_path / "snapshots" / snapshot / "road_safety.duckdb"), read_only=True
    ) as connection:
        assert connection.execute("SELECT count(*) FROM raw.acidentes_csv").fetchone()[0] == 2
    assert (tmp_path / old.path).read_bytes().decode("cp1252").find("00:00:00") > 0


def test_unknown_overlapping_families_abort_publication(tmp_path: Path) -> None:
    previous = build_snapshot(tmp_path, [source(tmp_path, [{}])])
    a = source(tmp_path, [{}], identifier="a", family="a")
    b = source(tmp_path, [{}], identifier="b", family="b")
    with pytest.raises(ValueError, match="cross-resource overlaps"):
        build_snapshot(tmp_path, [a, b])
    assert DataService(tmp_path).catalog().snapshot_id == previous


def test_historical_metadata_refresh_does_not_override_verified_successor(tmp_path: Path) -> None:
    historical = source(
        tmp_path,
        [{}],
        identifier="6e184bbe-d81d-4de3-830a-19fc0af4e697",
        family="capixaba",
        modified="2027-01-01",
    )
    successor = source(
        tmp_path,
        [{}],
        identifier="14875e46-9ec5-4b8a-b420-7afa33999a81",
        family="capixaba",
        modified="2026-01-01",
    )
    selected = select_active_sources([historical, successor])
    assert not selected[0].active and selected[1].active


def test_invalid_counts_stay_null_and_invalid_dates_are_quarantined(tmp_path: Path) -> None:
    inputs = source(
        tmp_path,
        [
            {"gravemente_feridos": "não informado", "mortos": "-1", "km": "-20"},
            {"data": "31/02/2025"},
            {"n_da_ocorrencia": "3", "gravemente_feridos": "0"},
            {"n_da_ocorrencia": "3", "gravemente_feridos": "0"},
        ],
    )
    build_snapshot(tmp_path, [inputs])
    service = DataService(tmp_path)
    assert service.catalog().total_accidents == 2
    detail = service.query(QuerySpec(operation="detail"))
    unknown = next(row for row in detail.rows if row["km"] is None)
    assert unknown["gravemente_feridos"] is None
    assert unknown["mortos"] is None
    warnings = " ".join(service.catalog().warnings)
    assert "data inválida" in warnings
    assert "duplicatas exatas" in warnings


def test_failed_pointer_replacement_keeps_previous_snapshot(tmp_path: Path) -> None:
    first = build_snapshot(tmp_path, [source(tmp_path, [{}])])

    def fail_publish(path: Path, value: object) -> None:
        raise OSError("simulated disk failure")

    with pytest.raises(OSError, match="disk failure"):
        build_snapshot(tmp_path, [source(tmp_path, [{"mortos": "1"}])], publish=fail_publish)
    assert DataService(tmp_path).catalog().snapshot_id == first
    assert json.loads((tmp_path / "active.json").read_text())["snapshot_id"] == first


def test_download_cache_preserves_original_bytes_and_aliases(tmp_path: Path) -> None:
    fixture = source(tmp_path, [{}])
    content = (tmp_path / fixture.path).read_bytes()
    resource_id = "14875e46-9ec5-4b8a-b420-7afa33999a81"
    url = "https://dados.antt.gov.br/fixture.csv"
    catalog = json.dumps(
        {
            "success": True,
            "result": {
                "resources": [
                    {
                        "id": resource_id,
                        "name": "Demonstrativos de Acidentes - ECOVIAS CAPIXABA",
                        "format": "CSV",
                        "url": url,
                        "last_modified": "2026-10-01",
                    }
                ]
            },
        }
    ).encode()
    calls: list[str] = []

    def download(address: str) -> bytes:
        calls.append(address)
        return catalog if address == API_URL else content

    sources = fetch_sources(tmp_path, download=download)
    assert sources[0].family == "capixaba"
    assert sources[0].concession == "ECOVIAS CAPIXABA"
    assert (tmp_path / sources[0].path).read_bytes() == content
    build_snapshot(tmp_path, sources)
    calls.clear()
    fetch_sources(tmp_path, download=download)
    assert calls == [API_URL]


def test_no_success_catalog_or_bad_headers_do_not_publish(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="successful"):
        fetch_sources(tmp_path, download=lambda _: b'{"success":false}')
    with pytest.raises(ValueError, match="after"):
        Filters(start_date="2026-01-01", end_date="2025-01-01")


def test_antt_quoted_text_and_unquoted_numbers_parse_identically(tmp_path: Path) -> None:
    descriptor = source(tmp_path, [{}])
    original = (tmp_path / descriptor.path).read_text(encoding="cp1252")
    header, _ = original.splitlines()
    # Real ANTT resources quote text/date/km columns but leave counts unquoted.
    row = (
        '"30/09/2026";"04:21:00";"18";"sem vítima";"167,500";"BR-393/RJ";'
        '" Norte";"Derrapagem";1;0;0;0;0;0;0;0;0;0;1;0;0;0;0;\n'
    )
    content = (header + "\n" + row).encode("cp1252")
    (tmp_path / descriptor.path).write_bytes(content)
    descriptor = replace(descriptor, sha256=hashlib.sha256(content).hexdigest())
    build_snapshot(tmp_path, [descriptor])
    result = DataService(tmp_path).query(QuerySpec(operation="detail"))
    assert result.rows[0]["data"] == "2026-09-30"
    assert result.rows[0]["horario"] == "04:21:00"
    assert result.rows[0]["trecho"] == "BR-393/RJ"
    assert result.rows[0]["km"] == 167.5


def test_dictionary_two_digit_year_is_not_interpreted_as_year_26(tmp_path: Path) -> None:
    build_snapshot(tmp_path, [source(tmp_path, [{"data": "30/09/26"}])])
    assert DataService(tmp_path).catalog().max_date == "2026-09-30"


def test_python_csv_parity_gate_prevents_silent_parser_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = build_snapshot(tmp_path, [source(tmp_path, [{}])])
    # Simulate a CSV adapter regression: the independent parser sees one valid
    # source date while the SQL transformation would receive an invalid value.
    reference = ingestion._reference_csv

    def incorrect_profile(text: str, canonical_path: Path) -> tuple[int, int, list[str], list[str]]:
        reference(text, canonical_path)
        return 1, 1, ["bad"] * 24, ["bad"] * 24

    monkeypatch.setattr("road_safety.data.ingestion._reference_csv", incorrect_profile)
    with pytest.raises(ValueError, match="parser field mismatch"):
        build_snapshot(tmp_path, [source(tmp_path, [{}])])
    assert DataService(tmp_path).catalog().snapshot_id == first
