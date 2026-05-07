"""Chargement Pandas -> DuckDB avec gestion simple des pannes.

----------------------------------------------------------------------------
ROLE DE CE MODULE :
    Persistance des resultats du pipeline dans une base analytique DuckDB.
    DuckDB est un SGBD analytique embarque (comme SQLite, mais optimise
    pour les requetes analytiques sur de gros volumes).

POURQUOI DUCKDB ICI :
    - Zero serveur a installer : c'est un fichier .db local.
    - Excellent pour les jointures et agregations (colonnaire).
    - Lit/ecrit directement les DataFrames pandas (pas de conversion ETL).
    - Imposes par l'enonce du livrable.

TOLERANCE AUX PANNES (exigence du livrable Option B) :

    Si DuckDB est temporairement indisponible (fichier verrouille, disque
    plein, ...), on doit pouvoir reagir sans perdre les donnees du run :

        1. Retry 3 fois en cas d'erreur de connexion DuckDB.
        2. Backoff exponentiel : 1s, 5s, 15s entre les tentatives.
        3. Fallback : si DuckDB reste KO apres 3 essais, on ecrit un CSV
           dans data/processed/_fallback/ et on leve DuckDBUnavailable.
           L'orchestrateur Kestra peut alors decider de continuer le run
           (rapport Excel quand meme, alerte) ou de planter completement.

ARCHITECTURE INTERNE :

    `_run_with_retry()` : helper generique qui retry une fonction donnee.
    `_open_connection()` : ouvre une connexion DuckDB (sans retry).
    `_write_table_inner()` : ecriture brute (sans retry, sans fallback).
    `write_table()` : ecriture publique (avec retry + fallback CSV).

    Cette structure est volontairement explicite : un decorateur paramretre
    serait plus compact mais moins lisible pour relecture / debug. Le test
    d'integration `test_fallback_writes_csv_on_failure` monkeypatche
    `_write_table_inner`, c'est pour ca qu'il est expose.
----------------------------------------------------------------------------
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd


logger = logging.getLogger(__name__)


# Chemin par defaut, surchargeable via la variable d'environnement DUCKDB_PATH.
# Cela permet a Kestra de pointer vers un autre fichier en prod sans
# modifier le code, juste avec une env var.
DEFAULT_DUCKDB_PATH = Path(os.environ.get("DUCKDB_PATH", "duckdb/bottlerock.db"))

# Ou se range le CSV de secours si DuckDB tombe.
FALLBACK_DIR = Path("data/processed/_fallback")

# Delais (en secondes) entre les tentatives de retry.
# Pattern "exponential backoff" : on attend de plus en plus longtemps
# entre les tentatives pour laisser le temps au probleme de se resoudre.
RETRY_DELAYS = (1, 5, 15)

# Erreurs DuckDB considerees comme "transitoires" (donc retryables).
# Une erreur logique (mauvais SQL) ne doit PAS etre retryee : elle se
# reproduira a chaque tentative. On retry uniquement ce qui est I/O.
_RETRYABLE_ERRORS = (duckdb.IOException, duckdb.ConnectionException, OSError)


class DuckDBUnavailable(RuntimeError):
    """Levee quand DuckDB reste indisponible apres tous les retries.

    On herite de RuntimeError plutot que de Exception directement :
    c'est plus precis sur la nature du probleme (erreur d'execution,
    pas une erreur de programmation).
    """


def _run_with_retry(operation_name: str, func, *args, **kwargs):
    """Execute `func(*args, **kwargs)` avec retry + backoff exponentiel.

    On essaie une 1re fois immediatement (delai=0), puis on retry selon
    RETRY_DELAYS. Si toutes les tentatives echouent, on convertit la
    derniere erreur en DuckDBUnavailable (couche d'abstraction propre :
    l'appelant n'a pas a connaitre les exceptions specifiques de duckdb).

    Args:
        operation_name: Nom logique de l'operation, pour les logs.
        func:           La fonction a appeler.
        *args, **kwargs: Arguments transmis a `func`.

    Returns:
        Ce que retourne `func` en cas de succes.

    Raises:
        DuckDBUnavailable: si toutes les tentatives ont echoue.
    """
    last_exc = None
    # On insere 0 en tete : 1re tentative immediate, puis 1s, 5s, 15s.
    delays = (0,) + RETRY_DELAYS

    # `enumerate(..., start=1)` : numerote les tentatives a partir de 1
    # pour avoir des messages d'erreur lisibles ("tentative 2 sur 4").
    for attempt, delay in enumerate(delays, start=1):
        if delay:
            logger.warning(
                "[%s] tentative %d apres %ds (precedente erreur : %s)",
                operation_name, attempt, delay, last_exc,
            )
            time.sleep(delay)
        try:
            return func(*args, **kwargs)
        except _RETRYABLE_ERRORS as exc:
            last_exc = exc
            logger.error(
                "[%s] echec tentative %d : %s",
                operation_name, attempt, exc,
            )

    # Toutes les tentatives ont echoue. On enrobe la derniere exception
    # dans une exception "domaine" plus parlante pour l'appelant.
    # `raise ... from last_exc` chaine les exceptions (la traceback Python
    # affichera "While handling ..., another exception occurred").
    raise DuckDBUnavailable(
        f"[{operation_name}] DuckDB indisponible apres {len(delays)} tentatives. "
        f"Derniere erreur : {last_exc}"
    ) from last_exc


def _open_connection(path) -> duckdb.DuckDBPyConnection:
    """Ouvre une connexion DuckDB (sans retry).

    Cree le dossier parent si besoin (sauf pour ':memory:' qui n'est
    pas un fichier sur disque, c'est une base ephemere en RAM).
    """
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    logger.info("Connexion DuckDB -> %s", path)
    return duckdb.connect(str(path))


def get_connection(path: Optional[Path] = None) -> duckdb.DuckDBPyConnection:
    """Ouvre une connexion DuckDB, avec retry sur les erreurs transitoires.

    Args:
        path: Chemin du fichier .db. Passer ':memory:' pour une base
              ephemere (utile pour les tests).
    """
    target = path if path is not None else DEFAULT_DUCKDB_PATH
    return _run_with_retry("get_connection", _open_connection, target)


def _write_table_inner(
    df: pd.DataFrame,
    table_name: str,
    mode: str,
    conn: Optional[duckdb.DuckDBPyConnection],
) -> int:
    """Ecriture proprement dite (sans retry).

    Cette fonction est volontairement separee de `write_table` :
        - `write_table` gere le retry et le fallback CSV (haut niveau).
        - `_write_table_inner` fait JUSTE l'ecriture (bas niveau).
    Cela permet aux tests de monkeypatcher l'une sans toucher a l'autre.

    DETAIL DES OPERATIONS DUCKDB :
        - conn.register('alias', df) : expose le DataFrame pandas a SQL
          comme une table virtuelle nommee 'alias'.
        - mode='replace' : DROP + CREATE AS SELECT * FROM alias.
        - mode='append'  : CREATE IF NOT EXISTS + INSERT INTO ... SELECT *.
        - conn.unregister('alias') : libere l'alias une fois fini.
    """
    # Si pas de connexion fournie, on en ouvre une et on s'engage a la fermer.
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        conn.register("_df_to_load", df)
        if mode == "replace":
            # DROP TABLE IF EXISTS : evite d'echouer si la table existe deja.
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM _df_to_load")
        else:
            # mode == "append"
            # CREATE IF NOT EXISTS avec WHERE 1=0 : cree juste le schema vide
            # si la table n'existe pas (utilise comme template de colonnes).
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} AS "
                f"SELECT * FROM _df_to_load WHERE 1=0"
            )
            conn.execute(f"INSERT INTO {table_name} SELECT * FROM _df_to_load")
        conn.unregister("_df_to_load")
        logger.info("write_table %s (%s) : %d lignes", table_name, mode, len(df))
        return len(df)
    finally:
        # On ferme la connexion UNIQUEMENT si on l'a ouverte nous-memes.
        # Si l'appelant nous a passe une connexion, c'est a lui de la fermer.
        if own_conn:
            conn.close()


def write_table(
    df: pd.DataFrame,
    table_name: str,
    mode: str = "replace",
    conn: Optional[duckdb.DuckDBPyConnection] = None,
    fallback: bool = True,
) -> int:
    """Ecrit un DataFrame dans une table DuckDB, avec retry et fallback CSV.

    C'est la fonction d'entree publique pour ecrire dans DuckDB. C'est
    elle qui apporte la tolerance aux pannes.

    Args:
        df:         DataFrame a ecrire.
        table_name: Nom de la table cible.
        mode:       'replace' (defaut, ecrase) ou 'append' (ajoute).
        conn:       Connexion existante (sinon on en ouvre une).
        fallback:   Si True et que DuckDB reste KO, on ecrit un CSV dans
                    FALLBACK_DIR avant de re-lever DuckDBUnavailable.

    Returns:
        Nombre de lignes ecrites en cas de succes.

    Raises:
        ValueError: si `mode` est invalide (echec immediat, pas un retry).
        DuckDBUnavailable: si DuckDB reste KO apres tous les essais.
    """
    if mode not in {"replace", "append"}:
        # Erreur de programmation, pas une panne -> on echoue tot.
        raise ValueError(f"mode doit etre 'replace' ou 'append', recu : {mode}")

    try:
        return _run_with_retry(
            "write_table", _write_table_inner, df, table_name, mode, conn,
        )
    except DuckDBUnavailable:
        # DuckDB est definitivement KO : on ecrit le CSV de secours
        # AVANT de re-lever, pour que l'appelant puisse decider de la suite
        # mais en sachant que les donnees ne sont pas perdues.
        if fallback:
            FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
            csv_path = FALLBACK_DIR / f"{table_name}.csv"
            df.to_csv(csv_path, index=False)
            logger.warning(
                "[%s] DuckDB KO, fallback CSV ecrit : %s",
                table_name, csv_path,
            )
        raise  # re-leve DuckDBUnavailable pour signaler le probleme


def execute_sql_file(
    sql_path: Path,
    conn: Optional[duckdb.DuckDBPyConnection] = None,
) -> None:
    """Execute toutes les instructions d'un fichier .sql, avec retry.

    Utile pour appliquer un fichier de migration ou de tests SQL stocke
    dans scripts/sql/. On lit le fichier en UTF-8 et on l'envoie a DuckDB.
    """
    sql_path = Path(sql_path)
    sql = sql_path.read_text(encoding="utf-8")
    logger.info("Execution SQL : %s", sql_path)

    # Closure : on capture sql_path et conn dans la fonction interne pour
    # pouvoir la passer telle quelle a `_run_with_retry`. Plus simple
    # que de passer 5 arguments separes.
    def _run():
        own = conn is None
        c = conn or get_connection()
        try:
            c.execute(sql)
        finally:
            if own:
                c.close()

    _run_with_retry("execute_sql_file", _run)


def query(
    sql: str,
    conn: Optional[duckdb.DuckDBPyConnection] = None,
) -> pd.DataFrame:
    """Execute une requete SQL et retourne un DataFrame, avec retry.

    .df() est un raccourci DuckDB qui transforme le resultset en
    DataFrame pandas (tres pratique pour la suite du pipeline).
    """
    def _run():
        own = conn is None
        c = conn or get_connection()
        try:
            return c.execute(sql).df()
        finally:
            if own:
                c.close()

    return _run_with_retry("query", _run)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    # Demo rapide : on cree une table "demo" en RAM, on y met 3 lignes,
    # on les recompte. Sert juste a verifier que tout fonctionne.
    demo = pd.DataFrame({"x": [1, 2, 3]})
    with get_connection(":memory:") as conn:
        write_table(demo, "demo", conn=conn)
        print(query("SELECT COUNT(*) AS n FROM demo", conn=conn))
