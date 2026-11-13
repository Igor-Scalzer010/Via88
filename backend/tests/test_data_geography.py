"""The cached map must contain every UF and preserve its previous valid contents."""

import json
from pathlib import Path

import pytest

from road_safety.data.geography import STATES, download_geography
from road_safety.data.service import DataService


def test_ibge_cache_normalizes_all_states_and_rejects_partial_replacement(tmp_path: Path) -> None:
    features = [
        {
            "type": "Feature",
            "properties": {"codarea": code},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-40, -20], [-41, -20], [-40, -21], [-40, -20]]],
            },
        }
        for code in STATES
    ]
    payload = {"type": "FeatureCollection", "features": features}
    path = download_geography(tmp_path, download=lambda _: json.dumps(payload).encode())
    original = path.read_bytes()
    assert {
        feature["properties"]["uf"] for feature in DataService(tmp_path).geography()["features"]
    } == {value[0] for value in STATES.values()}
    with pytest.raises(ValueError, match="27 UFs"):
        download_geography(
            tmp_path, download=lambda _: b'{"type":"FeatureCollection","features":[]}'
        )
    assert path.read_bytes() == original
