"""Chargement des DataFrames Pandas vers DuckDB."""

from pathlib import Path
import duckdb
import pandas as pd


DUCKDB_PATH = Path("duckdb/bottlerock.db")


def get_connection():
    """Retourne une connexion DuckDB vers le fichier du projet."""
    return duckdb.connect(str(DUCKDB_PATH))


def write_table(df: pd.DataFrame, table_name: str, mode: str = "replace") -> None:
    """Ecrit un DataFrame dans DuckDB (mode = 'replace' ou 'append')."""
    # TODO
    raise NotImplementedError


if __name__ == "__main__":
    pass
