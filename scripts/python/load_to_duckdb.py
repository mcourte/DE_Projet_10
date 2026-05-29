"""Chargement Pandas -> DuckDB avec retry et fallback CSV.

DuckDB = base analytique embarquée (un seul fichier .db, pas de serveur).

Tolérance aux pannes (exigée par l'énoncé OpenClassrooms) :
    - On retry 3 fois avec attente croissante : 1s, 5s, 15s.
    - Si DuckDB reste KO : on écrit un CSV de secours dans
      data/processed/_fallback/ puis on lève RuntimeError pour
      que Kestra puisse alerter.
"""

import logging
import os
import time
from pathlib import Path

import duckdb
import pandas as pd


logger = logging.getLogger(__name__)

# Chemin du fichier DuckDB. En prod, on peut le changer via une variable
# d'environnement DUCKDB_PATH (utile pour Kestra).
DEFAULT_DUCKDB_PATH = Path(os.environ.get("DUCKDB_PATH", "duckdb/bottlerock.db"))

# Dossier où on écrit le CSV de secours si DuckDB est KO.
FALLBACK_DIR = Path("data/processed/_fallback")

# Délais entre les tentatives de retry (en secondes).
RETRY_DELAYS = [1, 5, 15]

# Erreurs qu'on considère "transitoires" (problème d'I/O passager) : on retry.
# Une erreur SQL n'est PAS retryée parce qu'elle se reproduirait à l'identique.
_RETRYABLE_ERRORS = (duckdb.IOException, duckdb.ConnectionException, OSError)


def _with_retry(operation_name, func):
    """Appelle `func()` jusqu'à 4 fois : tout de suite, puis 1s, 5s, 15s.

    Si toutes les tentatives échouent, on lève RuntimeError.
    """
    last_error = None
    # On met 0 en tête de la liste : 1re tentative immédiate, puis 1s, 5s, 15s.
    for attempt, delay in enumerate([0] + RETRY_DELAYS, start=1):
        if delay:
            logger.warning(f"[{operation_name}] retry n°{attempt} dans {delay}s")
            time.sleep(delay)
        try:
            return func()
        except _RETRYABLE_ERRORS as exc:
            last_error = exc
            logger.error(f"[{operation_name}] tentative {attempt} échouée : {exc}")

    raise RuntimeError(
        f"[{operation_name}] DuckDB indisponible après 4 tentatives : {last_error}"
    )




def get_connection(path=None):
    """Ouvre une connexion DuckDB sur un fichier .db. Retry si erreur d'I/O.

    Sans argument, utilise le chemin par défaut (duckdb/bottlerock.db).
    """
    if path is None:
        path = DEFAULT_DUCKDB_PATH

    # On crée le dossier parent si besoin (Path.parent renvoie le dossier
    # qui contient le fichier ; ex: pour "duckdb/bottlerock.db" -> "duckdb").
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    # On enveloppe l'appel à duckdb.connect dans une petite fonction pour
    # pouvoir le retry via _with_retry.
    def _open():
        logger.info(f"Connexion DuckDB -> {path}")
        return duckdb.connect(str(path))

    return _with_retry("get_connection", _open)


def write_table(df, table_name, mode="replace", conn=None, fallback=True):
    """Écrit un DataFrame dans DuckDB, avec retry et fallback CSV.

    Si `conn` n'est pas fournie, on en ouvre une qu'on fermera à la fin.
    Si DuckDB reste KO après 4 tentatives :
      - on écrit un CSV de secours dans data/processed/_fallback/
      - on lève RuntimeError
    """
    if mode not in ("replace", "append"):
        raise ValueError(f"mode doit être 'replace' ou 'append', reçu : {mode}")

    # Si pas de connexion fournie, on en ouvre une temporaire ici.
    own_conn = (conn is None)
    if own_conn:
        conn = get_connection()

    # Fonction interne qui fait l'écriture proprement dite (sans retry).
    # _with_retry l'appellera jusqu'à 4 fois en cas d'erreur d'I/O.
    def _do_write():
        # register() expose le DataFrame à SQL comme une table virtuelle.
        conn.register("_df_to_load", df)
        if mode == "replace":
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM _df_to_load")
        else:  # mode == "append"
            # WHERE 1=0 crée juste le schéma vide si la table n'existe pas.
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} AS "
                f"SELECT * FROM _df_to_load WHERE 1=0"
            )
            conn.execute(f"INSERT INTO {table_name} SELECT * FROM _df_to_load")
        conn.unregister("_df_to_load")
        logger.info(f"write_table {table_name} ({mode}) : {len(df)} lignes")
        return len(df)

    try:
        return _with_retry("write_table", _do_write)
    except RuntimeError:
        # On écrit le CSV de secours AVANT de re-lever : comme ça les données
        # ne sont pas perdues même si DuckDB reste KO.
        if fallback:
            FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
            csv_path = FALLBACK_DIR / f"{table_name}.csv"
            df.to_csv(csv_path, index=False)
            logger.warning(f"[{table_name}] DuckDB KO, fallback CSV écrit : {csv_path}")
        raise
    finally:
        # On ne ferme la connexion que si on l'a ouverte nous-mêmes.
        if own_conn:
            conn.close()


def query(sql, conn=None):
    """Exécute une requête SQL et renvoie un DataFrame pandas, avec retry."""
    own_conn = (conn is None)
    if own_conn:
        conn = get_connection()
    try:
        # .df() est un raccourci DuckDB qui convertit le résultat en
        # DataFrame pandas directement (très pratique pour la suite).
        return _with_retry("query", lambda: conn.execute(sql).df())
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    # Démo rapide : on écrit 3 lignes dans une base de démo (duckdb/demo.db).
    demo_df = pd.DataFrame({"x": [1, 2, 3]})
    with get_connection("duckdb/demo.db") as conn:
        write_table(demo_df, "demo", conn=conn)
        print(query("SELECT COUNT(*) AS n FROM demo", conn=conn))
