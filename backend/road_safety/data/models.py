"""Internal metadata for immutable source files and analytical snapshots."""

from dataclasses import asdict, dataclass
from typing import Any

API_URL = "https://dados.antt.gov.br/api/3/action/package_show?id=acidentes-rodovias"
UF_CODES = (
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
)

# The successor files contain corrected historical occurrences. Concatenating both
# resources keeps old versions of the same accident even after exact deduplication.
FAMILIES: dict[str, str] = {
    "6e184bbe-d81d-4de3-830a-19fc0af4e697": "capixaba",
    "14875e46-9ec5-4b8a-b420-7afa33999a81": "capixaba",
    "7c3a9f7a-21fe-4a50-b1a9-93d0b76f3f00": "via-mineira",
    "db0bc5a1-f3a3-458e-8347-0909d52f333c": "via-mineira",
    "d280c523-eaef-4d4d-9c08-1b8b6267ddcf": "motiva-parana",
    "e5f18f0f-785c-4c81-a144-2dfad8b4ab92": "motiva-parana",
}
SUCCESSORS = {
    "capixaba": "14875e46-9ec5-4b8a-b420-7afa33999a81",
    "via-mineira": "db0bc5a1-f3a3-458e-8347-0909d52f333c",
    "motiva-parana": "e5f18f0f-785c-4c81-a144-2dfad8b4ab92",
}
NAME_FAMILIES = {
    "eco101": "capixaba",
    "ecovias capixaba": "capixaba",
    "via mineira": "via-mineira",
    "epr via mineira": "via-mineira",
    "prvias": "motiva-parana",
    "motiva parana": "motiva-parana",
}
VEHICLES = (
    "automovel",
    "bicicleta",
    "caminhao",
    "moto",
    "onibus",
    "outros",
    "tracao_animal",
    "transporte_de_cargas_especiais",
    "trator_maquinas",
    "utilitarios",
)
PEOPLE = ("ilesos", "levemente_feridos", "moderadamente_feridos", "gravemente_feridos", "mortos")
CSV_COLUMNS = (
    "data",
    "horario",
    "n_da_ocorrencia",
    "tipo_de_ocorrencia",
    "km",
    "trecho",
    "sentido",
    "tipo_de_acidente",
    *VEHICLES,
    *PEOPLE,
    "tipo_de_pista",
)


@dataclass(frozen=True)
class SourceFile:
    """A downloaded resource; its raw file is addressed by its content hash."""

    resource_id: str
    name: str
    concession: str
    family: str
    url: str
    modified_at: str
    sha256: str
    path: str
    encoding: str
    downloaded_at: str
    active: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
