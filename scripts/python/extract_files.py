"""Lecture des fichiers sources BottleNeck (3 fichiers Excel).

----------------------------------------------------------------------------
ROLE DE CE MODULE :
    Premiere etape du pipeline. C'est lui qui transforme des fichiers sur
    disque en DataFrames pandas exploitables par les modules suivants.

    Aucun nettoyage n'est fait ici : on charge tel quel.
    Les regles metier (dedup, filtre sku NaN, etc.) sont dans clean_data.py.

CONTEXTE METIER :
    Stephane (Data Analyst) recoit chaque mois 3 fichiers Excel :
        - Fichier_erp.xlsx     -> catalogue produits, prix, stock (825 lignes)
        - Fichier_web.xlsx     -> export WooCommerce, ventes (1 513 lignes)
        - fichier_liaison.xlsx -> table de jointure ERP <-> WEB (825 lignes)
    Ces 3 fichiers sont la matiere premiere du pipeline.

USAGE STANDALONE :
    python -m scripts.python.extract_files
    -> affiche un apercu des 3 sources (utile pour debug rapide).
----------------------------------------------------------------------------
"""

import logging
import warnings
from pathlib import Path
from typing import Optional

import pandas as pd


# `logger` permet d'emettre des messages info/warning/error qui seront captes
# par Kestra (ou par run_pipeline.py en local). On evite les `print()` qui
# ne sont pas filtrables et passent mal dans un orchestrateur.
logger = logging.getLogger(__name__)

# Repertoire ou sont stockes les 3 fichiers BottleNeck.
# Note : on utilise pathlib.Path et non des string -> portable Windows/Linux.
BOTTLENECK_DIR = Path("data/raw/bottleneck")

# Noms exacts des 3 fichiers attendus. On les mets en constantes pour qu'ils
# soient faciles a retrouver et a modifier si Stephane renomme un fichier.
ERP_FILENAME = "Fichier_erp.xlsx"
WEB_FILENAME = "Fichier_web.xlsx"
LIAISON_FILENAME = "fichier_liaison.xlsx"

# Extensions reconnues pour la decouverte automatique de fichiers.
# Si on ajoute un .json par exemple, il sera ignore.
SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".txt"}


def list_source_files(directory: Path = BOTTLENECK_DIR) -> list:
    """Retourne la liste triee des fichiers sources presents dans `directory`.

    Cette fonction est utilitaire (pas indispensable au pipeline). Elle sert
    surtout au debug et aux tests : on peut lister rapidement ce qu'il y a
    dans un dossier sans dependre du nom des fichiers.

    Regles d'exclusion :
        - les fichiers caches (.gitkeep, .DS_Store, ...) sont ignores.
        - les extensions hors SUPPORTED_EXTENSIONS sont ignorees.

    Raises:
        FileNotFoundError: si le dossier n'existe pas du tout.
    """
    directory = Path(directory)
    if not directory.exists():
        raise FileNotFoundError(f"Repertoire introuvable : {directory}")

    files = []
    # rglob('*') = recursif (inclut les sous-dossiers).
    # Si on voulait juste le dossier racine, on ferait `glob('*')`.
    for path in directory.rglob("*"):
        if not path.is_file():
            # rglob retourne aussi les dossiers intermediaires : on les saute.
            continue
        if path.name.startswith("."):
            # Fichier cache type .gitkeep -> on saute.
            continue
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(path)

    # sorted() pour avoir un ordre stable d'execution en execution
    # (sinon l'OS peut nous donner les fichiers dans n'importe quel ordre).
    return sorted(files)


def _read_excel_silent(path: Path, **kwargs) -> pd.DataFrame:
    """Wrapper read_excel qui ignore le warning openpyxl 'Unknown extension'.

    POURQUOI :
        Le fichier WEB BottleNeck contient des extensions XML inconnues
        d'openpyxl (genre <wp:terms> de WordPress). C'est sans impact sur
        la lecture, mais ca pollue la console avec ~50 warnings par run.

    `with warnings.catch_warnings()` cree un contexte temporaire ou on peut
    masquer un warning precis sans toucher la config globale du programme.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Unknown extension is not supported",
            category=UserWarning,
        )
        return pd.read_excel(path, **kwargs)


def read_file(path: Path) -> pd.DataFrame:
    """Lit un fichier source et retourne un DataFrame pandas.

    Le format est determine par l'extension :
        - .csv  -> pandas.read_csv (separateur auto-detecte par engine='python')
        - .xlsx -> pandas.read_excel (engine openpyxl, format moderne)
        - .xls  -> pandas.read_excel (engine xlrd, format legacy)
        - .txt  -> pandas.read_csv avec separateur tabulation

    POURQUOI sep=None et engine='python' pour le CSV :
        sep=None demande a pandas de detecter automatiquement le separateur
        (`,` ou `;` ou `\\t`). Mais cette detection ne marche qu'avec l'engine
        Python (pas le C, plus rapide mais moins flexible). Pour BottleNeck
        on n'a pas de CSV, mais on garde la fonction generique.

    Raises:
        ValueError: si l'extension n'est pas prise en charge.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    logger.info("Lecture de %s", path)

    if suffix == ".csv":
        return pd.read_csv(path, sep=None, engine="python", encoding="utf-8")
    if suffix == ".xlsx":
        return _read_excel_silent(path, engine="openpyxl")
    if suffix == ".xls":
        return _read_excel_silent(path, engine="xlrd")
    if suffix == ".txt":
        return pd.read_csv(path, sep="\t", engine="python", encoding="utf-8")

    raise ValueError(f"Extension non prise en charge : {suffix}")


def read_bottleneck_sources(directory: Optional[Path] = None) -> dict:
    """Lit les 3 fichiers sources BottleNeck et retourne un dictionnaire.

    C'est LA fonction d'entree publique du module. Tout le reste du pipeline
    appelle celle-ci pour recuperer les donnees brutes.

    On verifie d'abord que les 3 fichiers existent AVANT de les lire :
    si l'un manque, on le signale immediatement et clairement, plutot que
    de planter au milieu de la lecture.

    Returns:
        Un dict avec exactement 3 cles :
            'erp':     DataFrame  (~825 lignes brutes)
            'web':     DataFrame  (~1513 lignes brutes)
            'liaison': DataFrame  (~825 lignes brutes)

    Raises:
        FileNotFoundError: si l'un des 3 fichiers attendus est absent.
            Le message liste tous les fichiers manquants en une fois
            (plus pratique pour debugger qu'un FileNotFoundError par fichier).
    """
    directory = Path(directory) if directory is not None else BOTTLENECK_DIR

    # Construction du dict {alias -> chemin attendu}.
    # Les alias 'erp'/'web'/'liaison' sont la convention utilisee dans
    # tout le reste du pipeline (clean_data, run_pipeline, ...).
    expected = {
        "erp": directory / ERP_FILENAME,
        "web": directory / WEB_FILENAME,
        "liaison": directory / LIAISON_FILENAME,
    }

    # Verification d'existence : on collecte tous les fichiers manquants
    # avant de lever l'exception (mieux que rater 1 a 1 a chaque tentative).
    missing = [str(p) for p in expected.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Fichier(s) BottleNeck manquant(s) :\n  - " + "\n  - ".join(missing)
        )

    # Comprehension de dict : equivalent a `{k: read_file(v) for ...}`.
    # Plus concis qu'une boucle for + dict.update().
    sources = {key: read_file(path) for key, path in expected.items()}

    # Log de volumetrie : tres utile pour reperer un fichier tronque ou
    # un mauvais onglet Excel selectionne. Si on attendait 825 lignes
    # et qu'on en a 12, ca saute aux yeux ici.
    for key, df in sources.items():
        logger.info("Source '%s' chargee : %d lignes", key, len(df))

    return sources


# Bloc execute uniquement si le module est lance directement via :
#   python -m scripts.python.extract_files
# Pas execute si un autre module fait `from scripts.python.extract_files import ...`.
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    sources = read_bottleneck_sources()
    for name, df in sources.items():
        print(f"\n{name.upper()} : {len(df)} lignes, {len(df.columns)} colonnes")
        print(df.head(3))
