"""Lecture des 3 fichiers sources BottleNeck (étape 1 du pipeline).

Aucun nettoyage ici : on charge tel quel. Les règles métier (dédup,
filtre sku NaN…) sont dans clean_data.py.

Fichiers attendus dans data/raw/bottleneck/ :
    Fichier_erp.xlsx       — catalogue, prix, stock     (~825 lignes)
    Fichier_web.xlsx       — export WooCommerce, ventes (~1 513 lignes)
    fichier_liaison.xlsx   — table de jointure          (~825 lignes)
"""

import logging
import warnings
from pathlib import Path
from typing import Optional

import pandas as pd


# logger plutôt que print() : capté par Kestra, filtrable par niveau.
logger = logging.getLogger(__name__)

# pathlib.Path et non str -> portable Windows/Linux.
BOTTLENECK_DIR = Path("data/raw/bottleneck")

# Noms exacts des 3 fichiers attendus. Centralisés pour que ce soit
# facile à modifier si Stéphane renomme un fichier.
ERP_FILENAME = "Fichier_erp.xlsx"
WEB_FILENAME = "Fichier_web.xlsx"
LIAISON_FILENAME = "fichier_liaison.xlsx"

# Extensions reconnues pour la découverte automatique de fichiers.
SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".txt"}


def list_source_files(directory: Path = BOTTLENECK_DIR) -> list:
    """Liste triée des fichiers sources présents (utile pour debug/tests).

    Ignore les fichiers cachés (.gitkeep…) et les extensions non supportées.

    Raises:
        FileNotFoundError: si le dossier n'existe pas.
    """
    directory = Path(directory)
    if not directory.exists():
        raise FileNotFoundError(f"Répertoire introuvable : {directory}")

    files = []
    # rglob('*') = récursif (parcourt aussi les sous-dossiers).
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(path)

    # sorted() pour avoir un ordre stable entre exécutions.
    return sorted(files)


def _read_excel_silent(path: Path, **kwargs) -> pd.DataFrame:
    """read_excel sans le spam openpyxl 'Unknown extension'.

    Le fichier WEB contient des extensions XML WordPress (<wp:terms>...)
    qu'openpyxl ne connaît pas : ~50 warnings par run sans impact réel.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Unknown extension is not supported",
            category=UserWarning,
        )
        return pd.read_excel(path, **kwargs)


def read_file(path: Path) -> pd.DataFrame:
    """Lit un fichier et retourne un DataFrame, selon son extension.

        .csv  -> pandas.read_csv (séparateur auto-détecté)
        .xlsx -> pandas.read_excel (engine openpyxl)
        .xls  -> pandas.read_excel (engine xlrd, format legacy)
        .txt  -> pandas.read_csv avec séparateur tabulation

    Raises:
        ValueError: si l'extension n'est pas prise en charge.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    logger.info(f"Lecture de {path}")

    if suffix == ".csv":
        # sep=None + engine='python' : détecte automatiquement , ; ou \t.
        return pd.read_csv(path, sep=None, engine="python", encoding="utf-8")
    if suffix == ".xlsx":
        return _read_excel_silent(path, engine="openpyxl")
    if suffix == ".xls":
        return _read_excel_silent(path, engine="xlrd")
    if suffix == ".txt":
        return pd.read_csv(path, sep="\t", engine="python", encoding="utf-8")

    raise ValueError(f"Extension non prise en charge : {suffix}")


def read_bottleneck_sources(directory: Optional[Path] = None) -> dict:
    """Lit les 3 fichiers BottleNeck et renvoie {'erp', 'web', 'liaison'}.

    Fonction d'entrée publique du module : tout le reste du pipeline
    appelle celle-ci pour récupérer les données brutes.

    Raises:
        FileNotFoundError: si un ou plusieurs fichiers sont absents. Le
            message liste TOUS les fichiers manquants d'un coup (plus
            pratique pour debugger qu'un échec un par un).
    """
    # Si pas de dossier fourni, on utilise le chemin par défaut.
    # Sinon, on s'assure que c'est bien un objet Path (et pas juste une str).
    if directory is None:
        directory = BOTTLENECK_DIR
    else:
        directory = Path(directory)

    # Alias 'erp'/'web'/'liaison' : convention utilisée partout aval.
    expected = {
        "erp": directory / ERP_FILENAME,
        "web": directory / WEB_FILENAME,
        "liaison": directory / LIAISON_FILENAME,
    }

    # On collecte TOUS les manquants avant de lever (un seul message clair).
    missing = [str(p) for p in expected.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Fichier(s) BottleNeck manquant(s) :\n  - " + "\n  - ".join(missing)
        )

    # On lit chaque fichier et on range le DataFrame sous sa clé.
    sources = {}
    for key, path in expected.items():
        sources[key] = read_file(path)

    # Log de volumétrie : repère immédiatement un fichier tronqué ou
    # un mauvais onglet sélectionné (attendu 825, on en lit 12 -> alerte).
    for key, df in sources.items():
        logger.info(f"Source '{key}' chargée : {len(df)} lignes")

    return sources


if __name__ == "__main__":
    # Exécuté uniquement via `python -m scripts.python.extract_files`.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    sources = read_bottleneck_sources()
    for name, df in sources.items():
        print(f"\n{name.upper()} : {len(df)} lignes, {len(df.columns)} colonnes")
        print(df.head(3))
