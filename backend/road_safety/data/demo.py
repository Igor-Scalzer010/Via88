"""Explicitly synthetic deterministic data for offline interface verification."""

import csv
import hashlib
import io
from datetime import UTC, datetime
from pathlib import Path

from road_safety.data.ingestion import build_snapshot
from road_safety.data.models import CSV_COLUMNS, SourceFile


def create_demo(data_dir: Path) -> str:
    """Publish synthetic accidents, visibly labelled in every catalog and evidence."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, delimiter=";")
    writer.writeheader()
    roads = ("BR-101/ES", "BR-116/SP", "BR-381/MG", "BR-376/PR", "BR-101/SC", "BR-040/MG")
    occurrence = 0
    for month_index in range(48):
        year, month = divmod(2022 * 12 + 9 + month_index, 12)
        for road_index, road in enumerate(roads):
            for index in range(13 - road_index + month_index % 4):
                occurrence += 1
                row = dict.fromkeys(CSV_COLUMNS, "0")
                row.update(
                    {
                        "data": f"{1 + index % 28:02}/{month + 1:02}/{year}",
                        "horario": f"{(index * 3 + road_index) % 24:02}:30:00",
                        "n_da_ocorrencia": str(occurrence),
                        "tipo_de_ocorrencia": "com vítima" if index % 3 == 0 else "sem vítima",
                        "km": f"{100 + road_index * 20 + index % 3 * 10},500",
                        "trecho": road,
                        "sentido": "norte" if index % 2 else "sul",
                        "tipo_de_acidente": ("colisão traseira", "saída de pista", "tombamento")[
                            index % 3
                        ],
                        "tipo_de_pista": "principal",
                        "automovel": "1",
                        "caminhao": str(index % 2),
                        "moto": str(index % 5 == 0 and index % 2 == 0)
                        .replace("True", "1")
                        .replace("False", "0"),
                        "ilesos": "2",
                        "levemente_feridos": str(index % 3 == 0)
                        .replace("True", "1")
                        .replace("False", "0"),
                        "gravemente_feridos": str(1 + index % 2) if index % 6 == 0 else "0",
                        "mortos": "1" if occurrence % 71 == 0 else "0",
                    }
                )
                writer.writerow(row)
    content = stream.getvalue().encode("cp1252")
    digest = hashlib.sha256(content).hexdigest()
    relative = Path("raw") / "synthetic-demo" / f"{digest}.csv"
    path = data_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(content)
    source = SourceFile(
        resource_id="synthetic-demo",
        name="DEMONSTRAÇÃO SINTÉTICA",
        concession="DEMONSTRAÇÃO SINTÉTICA",
        family="synthetic-demo",
        url="synthetic://local-demo",
        modified_at="2026-09-30T00:00:00",
        sha256=digest,
        path=relative.as_posix(),
        encoding="cp1252",
        downloaded_at=datetime.now(UTC).isoformat(),
    )
    return build_snapshot(data_dir, [source], synthetic=True)
