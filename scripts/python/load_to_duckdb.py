"""Chargement Pandas -> DuckDB avec gestion des pannes.

Tolerance aux pannes :
    - Retry automatique 3 fois en cas d'erreur de connexion DuckDB
    - Backoff exponentiel : 1s, 5s, 15s
    - Fallback : si DuckDB reste indisponible apres 3 tentatives, on ecrit
      un CSV dans data/processed/_fallback/ et on leve une exception
      (l'orchestrateur peut decider de continuer ou non)
"""

from __future__ import annotations

import logging
import os
import time
from functools import wraps
from pathlib import Path
from typing import Callable

import duckdb
import pandas as pd


logger = logging.getLogger(__name__)


# Le chemin peut etre surcharge par DUCKDB_PATH (variable d'env)
DEFAULT_DUCKDB_PATH = Path(os.environ.get("DUCKDB_PATH", "duckdb/bottlerock.db"))

FALLBACK_DIR = Path("data/processed/_fallback")

# Backoff : delais en secondes entre les essais
RETRY_DELAYS = (1, 5, 15)


class DuckDBUnavailable(RuntimeError):
    """Exception levee quand DuckDB reste indisponible apres tous les retries."""


def _with_retry(operation_name: str):
    """Decorateur qui retry une operation DuckDB avec backoff exponentiel."""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt, delay in enumerate([0, *RETRY_DELAYS], start=0):
                if delay:
                    logger.warning(
                        "[%s] tentative %d apres %ds (precedente erreur : %s)",
                        operation_name, attempt + 1, delay, last_exc,
                    )
                    time.sleep(delay)
                try:
                    return func(*args, **kwargs)
                except (duckdb.IOException, duckdb.ConnectionException, OSError) as exc:
                    last_exc = exc
                    logger.error("[%s] echec tentative %d : %s",
                                 operation_name, attempt + 1, exc)
            raise DuckDBUnavailable(
                f"[{operation_name}] DuckDB indisponible apres "
                f"{len(RETRY_DELAYS) + 1} tentatives. Derniere erreur : {last_exc}"
            ) from last_exc
        return wrapper
    return decorator


@_with_retry("get_connection")
def get_connection(path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    """Ouvre une connexion DuckDB (avec retry).

    Args:
        path: Chemin du fichier .db. Passer ':memory:' pour une base ephemere.
    """
    target = path if path is not None else DEFAULT_DUCKDB_PATH
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    logger.info("Connexion DuckDB -> %s", target)
    return duckdb.connect(str(target))


def write_table(
    df: pd.DataFrame,
    table_name: str,
    mode: str = "replace",
    conn: duckdb.DuckDBPyConnection | None = None,
    fallback: bool = True,
) -> int:
    """Ecrit un DataFrame dans une table DuckDB avec fallback CSV.

    Args:
        df: DataFrame a ecrire.
        table_name: Nom de la table.
        mode: 'replace' ou 'append'.
        conn: Connexion existante (sinon on en ouvre une).
        fallback: Si True et que DuckDB est indisponible, on ecrit un CSV
                  dans data/processed/_fallback/ avant de re-lever l'exception.

    Returns:
        Nombre de lignes ecrites.
    """
    if mode not in {"replace", "append"}:
        raise ValueError(f"mode doit etre 'replace' ou 'append', recu : {mode}")

    try:
        return _write_table_inner(df, table_name, mode, conn)
    except DuckDBUnavailable:
        if fallback:
            FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
            csv_path = FALLBACK_DIR / f"{table_name}.csv"
            df.to_csv(csv_path, index=False)
            logger.warning(
                "[%s] DuckDB KO, fallback CSV ecrit : %s",
                table_name, csv_path,
            )
        raise


@_with_retry("write_table")
def _write_table_inner(
    df: pd.DataFrame,
    table_name: str,
    mode: str,
    conn: duckdb.DuckDBPyConnection | None,
) -> int:
    """Ecriture proprement dite, decoree avec retry."""
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        conn.register("_df_to_load", df)
        if mode == "replace":
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM _df_to_load")
        else:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} AS "
                f"SELECT * FROM _df_to_load WHERE 1=0"
            )
            conn.execute(f"INSERT INTO {table_name} SELECT * FROM _df_to_load")
        conn.unregister("_df_to_load")
        logger.info("write_table %s (%s) : %d lignes", table_name, mode, len(df))
        return len(df)
    finally:
        if own_conn:
            conn.close()


@_with_retry("execute_sql_file")
def execute_sql_file(
    sql_path: Path | str,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> None:
    """Execute toutes les instructions d'un fichier .sql."""
    sql_path = Path(sql_path)
    sql = sql_path.read_text(encoding="utf-8")
    logger.info("Execution SQL : %s", sql_path)
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        conn.execute(sql)
    finally:
        if own_conn:
            conn.close()


@_with_retry("query")
def query(sql: str, conn: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    """Execute une requete et retourne un DataFrame."""
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        return conn.execute(sql).df()
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    demo = pd.DataFrame({"x": [1, 2, 3]})
    with get_connection(":memory:") as conn:
        write_table(demo, "demo", conn=conn)
        print(query("SELECT COUNT(*) AS n FROM demo", conn=conn))
