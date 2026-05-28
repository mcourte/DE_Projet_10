"""Chargement Pandas -> DuckDB avec retry et fallback CSV.

DuckDB = base analytique embarquée (un seul fichier .db, pas de serveur).

Tolérance aux pannes (exigée par l'énoncé OpenClassrooms) :
    - Retry 3 fois avec attente croissante : 1s, 5s, 15s.
    - Si DuckDB reste KO : on écrit un CSV de secours dans
      data/processed/_fallback/ puis on lève DuckDBUnavailable
      pour que Kestra puisse alerter.
"""

import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd


logger = logging.getLogger(__name__)

# Chemin du fichier DuckDB, modifiable via la variable d'env DUCKDB_PATH
# (utile pour que Kestra pointe ailleurs en prod sans toucher au code).
DEFAULT_DUCKDB_PATH = Path(os.environ.get("DUCKDB_PATH", "duckdb/bottlerock.db"))

# Dossier où on écrit le CSV de secours si DuckDB est KO.
FALLBACK_DIR = Path("data/processed/_fallback")

# Délais entre les tentatives de retry (backoff exponentiel).
RETRY_DELAYS = (1, 5, 15)

# Erreurs DuckDB considérées comme "transitoires" : on les retry.
# Une erreur SQL n'est PAS retryée (elle se reproduira à l'identique).
_RETRYABLE_ERRORS = (duckdb.IOException, duckdb.ConnectionException, OSError)


class DuckDBUnavailable(RuntimeError):
    """Levée quand DuckDB reste KO après tous les retries."""


def _with_retry(operation_name: str, func, *args, **kwargs):
    """Appelle `func` jusqu'à 4 fois : tout de suite, puis 1s, 5s, 15s plus tard.

    Si toutes les tentatives échouent, on lève DuckDBUnavailable.
    """
    last_error = None
    # On met 0 en tête : 1ère tentative immédiate, puis on attend.
    for attempt, delay in enumerate((0,) + RETRY_DELAYS, start=1):
        if delay:
            logger.warning(
                "[%s] nouvelle tentative n°%d dans %ds (erreur précédente : %s)",
                operation_name, attempt, delay, last_error,
            )
            time.sleep(delay)
        try:
            return func(*args, **kwargs)
        except _RETRYABLE_ERRORS as exc:
            last_error = exc
            logger.error("[%s] tentative %d échouée : %s", operation_name, attempt, exc)

    raise DuckDBUnavailable(
        f"[{operation_name}] DuckDB indisponible après 4 tentatives. "
        f"Dernière erreur : {last_error}"
    ) from last_error


def _open(path) -> duckdb.DuckDBPyConnection:
    """Ouvre une connexion DuckDB (et crée le dossier parent si besoin)."""
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    logger.info("Connexion DuckDB -> %s", path)
    return duckdb.connect(str(path))


def get_connection(path: Optional[Path] = None) -> duckdb.DuckDBPyConnection:
    """Ouvre une connexion DuckDB avec retry sur erreurs transitoires.

    `path=":memory:"` ouvre une base éphémère en RAM (utile pour les tests).
    """
    target = path if path is not None else DEFAULT_DUCKDB_PATH
    return _with_retry("get_connection", _open, target)


@contextmanager
def _use_connection(conn: Optional[duckdb.DuckDBPyConnection]):
    """Petit utilitaire pour mutualiser le pattern :
        - si `conn` est fournie par l'appelant, on l'utilise telle quelle
          (et on NE la ferme PAS, c'est à lui de gérer son cycle de vie) ;
        - sinon, on en ouvre une et on la ferme à la sortie.
    """
    if conn is not None:
        yield conn
    else:
        owned = get_connection()
        try:
            yield owned
        finally:
            owned.close()


def _write_table_inner(df: pd.DataFrame, table_name: str, mode: str, conn) -> int:
    """Écriture brute dans DuckDB, sans retry.

    Volontairement séparée de `write_table` pour qu'un test puisse la
    monkeypatcher (simuler une panne) sans court-circuiter le retry.
    """
    with _use_connection(conn) as c:
        # register() expose le DataFrame à SQL comme une table virtuelle.
        c.register("_df_to_load", df)
        if mode == "replace":
            c.execute(f"DROP TABLE IF EXISTS {table_name}")
            c.execute(f"CREATE TABLE {table_name} AS SELECT * FROM _df_to_load")
        else:  # mode == "append"
            # WHERE 1=0 crée juste le schéma vide si la table n'existe pas.
            c.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} AS "
                f"SELECT * FROM _df_to_load WHERE 1=0"
            )
            c.execute(f"INSERT INTO {table_name} SELECT * FROM _df_to_load")
        c.unregister("_df_to_load")
    logger.info("write_table %s (%s) : %d lignes", table_name, mode, len(df))
    return len(df)


def write_table(
    df: pd.DataFrame,
    table_name: str,
    mode: str = "replace",
    conn: Optional[duckdb.DuckDBPyConnection] = None,
    fallback: bool = True,
) -> int:
    """Écrit un DataFrame dans DuckDB, avec retry + fallback CSV.

    Args:
        mode: 'replace' (écrase la table) ou 'append' (ajoute des lignes).
        fallback: si True et que DuckDB reste KO, on écrit un CSV de secours
                  dans FALLBACK_DIR avant de relever l'exception.

    Raises:
        ValueError: si `mode` n'est pas valide (erreur de programmation).
        DuckDBUnavailable: si DuckDB est KO après tous les essais.
    """
    if mode not in {"replace", "append"}:
        raise ValueError(f"mode doit être 'replace' ou 'append', reçu : {mode}")

    try:
        return _with_retry(
            "write_table", _write_table_inner, df, table_name, mode, conn,
        )
    except DuckDBUnavailable:
        # On écrit le CSV AVANT de relever : les données ne sont pas perdues,
        # l'appelant est juste prévenu que la base est KO.
        if fallback:
            FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
            csv_path = FALLBACK_DIR / f"{table_name}.csv"
            df.to_csv(csv_path, index=False)
            logger.warning("[%s] DuckDB KO, fallback CSV écrit : %s", table_name, csv_path)
        raise


def execute_sql_file(sql_path, conn: Optional[duckdb.DuckDBPyConnection] = None) -> None:
    """Exécute un fichier .sql complet, avec retry."""
    sql = Path(sql_path).read_text(encoding="utf-8")
    logger.info("Exécution SQL : %s", sql_path)

    def _run():
        with _use_connection(conn) as c:
            c.execute(sql)

    _with_retry("execute_sql_file", _run)


def query(sql: str, conn: Optional[duckdb.DuckDBPyConnection] = None) -> pd.DataFrame:
    """Exécute une requête SQL et renvoie un DataFrame pandas, avec retry."""
    def _run():
        with _use_connection(conn) as c:
            return c.execute(sql).df()

    return _with_retry("query", _run)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    # Démo rapide : on écrit 3 lignes en RAM et on les recompte.
    demo = pd.DataFrame({"x": [1, 2, 3]})
    with get_connection(":memory:") as conn:
        write_table(demo, "demo", conn=conn)
        print(query("SELECT COUNT(*) AS n FROM demo", conn=conn))
