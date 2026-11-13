"""Source-file builders for synthetic, network-independent pipeline tests."""

import csv
import hashlib
import io
from pathlib import Path

from road_safety.data.models import CSV_COLUMNS, SourceFile


def source(
    root: Path,
    rows: list[dict[str, str]],
    *,
    identifier: str = "fixture",
    family: str = "fixture",
    modified: str = "2026-01-01T00:00:00",
) -> SourceFile:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, delimiter=";")
    writer.writeheader()
    for index, overrides in enumerate(rows):
        row = dict.fromkeys(CSV_COLUMNS, "0")
        row.update(
            {
                "data": "30/09/2026",
                "horario": "12:30:00",
                "n_da_ocorrencia": str(index + 1),
                "tipo_de_ocorrencia": "sem vítima",
                "trecho": "BR-101/ES",
                "km": "10,000",
                "tipo_de_acidente": "Colisão traseira",
                "sentido": "Norte",
                "tipo_de_pista": "Principal",
                "automovel": "1",
                "ilesos": "2",
                **overrides,
            }
        )
        writer.writerow(row)
    content = stream.getvalue().encode("cp1252")
    digest = hashlib.sha256(content).hexdigest()
    relative = Path("raw") / identifier / f"{digest}.csv"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return SourceFile(
        resource_id=identifier,
        name=identifier,
        concession=identifier,
        family=family,
        url=f"https://dados.antt.gov.br/{identifier}.csv",
        modified_at=modified,
        sha256=digest,
        path=relative.as_posix(),
        encoding="cp1252",
        downloaded_at="2026-11-09T12:00:00+00:00",
    )
