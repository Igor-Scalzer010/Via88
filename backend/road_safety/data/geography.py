"""Cache official IBGE state boundaries without fabricating accident coordinates."""

import json
from pathlib import Path

from road_safety.data.ingestion import Download, atomic_json, download_bytes
from road_safety.data.service import GEOGRAPHY_PATH

IBGE_URL = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
    "?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=UF"
)
STATES = {
    "11": ("RO", "Rondônia"),
    "12": ("AC", "Acre"),
    "13": ("AM", "Amazonas"),
    "14": ("RR", "Roraima"),
    "15": ("PA", "Pará"),
    "16": ("AP", "Amapá"),
    "17": ("TO", "Tocantins"),
    "21": ("MA", "Maranhão"),
    "22": ("PI", "Piauí"),
    "23": ("CE", "Ceará"),
    "24": ("RN", "Rio Grande do Norte"),
    "25": ("PB", "Paraíba"),
    "26": ("PE", "Pernambuco"),
    "27": ("AL", "Alagoas"),
    "28": ("SE", "Sergipe"),
    "29": ("BA", "Bahia"),
    "31": ("MG", "Minas Gerais"),
    "32": ("ES", "Espírito Santo"),
    "33": ("RJ", "Rio de Janeiro"),
    "35": ("SP", "São Paulo"),
    "41": ("PR", "Paraná"),
    "42": ("SC", "Santa Catarina"),
    "43": ("RS", "Rio Grande do Sul"),
    "50": ("MS", "Mato Grosso do Sul"),
    "51": ("MT", "Mato Grosso"),
    "52": ("GO", "Goiás"),
    "53": ("DF", "Distrito Federal"),
}


def download_geography(data_dir: Path, *, download: Download = download_bytes) -> Path:
    """Validate all 27 UFs before replacing the cached FeatureCollection."""
    result = json.loads(download(IBGE_URL))
    if not isinstance(result, dict) or result.get("type") != "FeatureCollection":
        raise ValueError("IBGE did not return a GeoJSON FeatureCollection")
    features = result.get("features")
    if not isinstance(features, list):
        raise ValueError("IBGE geometry has no features")
    observed = set()
    for feature in features:
        properties = feature.get("properties", {})
        code = str(properties.get("codarea", properties.get("CD_UF", "")))
        if code not in STATES or code in observed:
            raise ValueError("IBGE geometry contains an unknown or duplicated UF")
        geometry = feature.get("geometry", {})
        if geometry.get("type") not in ("Polygon", "MultiPolygon") or not geometry.get(
            "coordinates"
        ):
            raise ValueError("IBGE geometry contains an invalid polygon")
        uf, name = STATES[code]
        feature["properties"] = {**properties, "uf": uf, "name": name}
        observed.add(code)
    if observed != set(STATES):
        raise ValueError("IBGE geometry must contain all 27 UFs")
    result["source"] = {"name": "IBGE — Malhas geográficas", "url": IBGE_URL}
    path = data_dir / GEOGRAPHY_PATH
    atomic_json(path, result)
    return path
