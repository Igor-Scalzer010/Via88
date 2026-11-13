"""Local commands for reproducible data ingestion and explicit synthetic QA."""

from pathlib import Path
from typing import Annotated

import typer

from road_safety.config import Settings
from road_safety.data.demo import create_demo
from road_safety.data.geography import download_geography
from road_safety.data.ingestion import ingest as ingest_data
from road_safety.data.service import DataService

app = typer.Typer(no_args_is_help=True, help="Road Safety — dados e snapshots locais")
DataDirectory = Annotated[Path | None, typer.Option("--data-dir", help="Diretório de dados locais")]


def _directory(value: Path | None) -> Path:
    if value is not None:
        return value.resolve()
    return Settings().data_dir.resolve()


@app.command()
def ingest(data_dir: DataDirectory = None, force: bool = False) -> None:
    """Baixar CSVs reais da ANTT e ativar um snapshot validado."""
    directory = _directory(data_dir)
    typer.echo("Consultando ANTT, preservando arquivos originais e validando o snapshot…")
    snapshot_id = ingest_data(directory, force=force)
    catalog = DataService(directory).catalog(snapshot_id)
    typer.echo(
        f"Snapshot {snapshot_id}: {catalog.total_accidents:,} ocorrências; "
        f"{catalog.resources} recursos ativos."
    )
    for warning in catalog.warnings:
        typer.echo(f"Aviso: {warning}")


@app.command()
def demo(data_dir: DataDirectory = None) -> None:
    """Ativar DADOS SINTÉTICOS para QA; não representam acidentes reais."""
    directory = _directory(data_dir)
    snapshot_id = create_demo(directory)
    typer.echo(f"DADOS SINTÉTICOS DE DEMONSTRAÇÃO ativados: {snapshot_id}")
    typer.echo("Use outro --data-dir para manter a demonstração separada dos dados reais.")


@app.command()
def geography(data_dir: DataDirectory = None) -> None:
    """Baixar e validar a malha oficial das 27 UFs do IBGE."""
    path = download_geography(_directory(data_dir))
    typer.echo(f"Malha IBGE (27 UFs) validada e armazenada em {path}")


if __name__ == "__main__":
    app()
