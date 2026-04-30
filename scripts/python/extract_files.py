"""Lecture des fichiers sources BottleNeck (3 fichiers Excel).

Usage :
    python -m scripts.python.extract_files

Source par defaut : data/raw/bottleneck/
    - Fichier_erp.xlsx
    - Fichier_web.xlsx
    - fichier_liaison.xlsx
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import pandas as pd


logger = logging.getLogger(__name__)

# Repertoire des fichiers bruts BottleNeck
BOTTLENECK_DIR = Path("data/raw/bottleneck")

# Noms attendus des fichiers
ERP_FILENAME = "Fichier_erp.xlsx"
WEB_FILENAME = "Fichier_web.xlsx"
LIAISON_FILENAME = "fichier_liaison.xlsx"

# Extensions prises en charge (pour la decouverte de fichiers)
SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".txt"}


def list_source_files(directory: Path | str = BOTTLENECK_DIR) -> list[Path]:
    """Retourne la liste triee des fichiers sources presents dans `directory`.

    Args:
        directory: Chemin du dossier a explorer (recursif).

    Returns:
        Liste de Path triee, fichiers caches et .gitkeep ignores.

    Raises:
        FileNotFoundError: Si le dossier n'existe pas.
    """
    directory = Path(directory)
    if not directory.exists():
        raise FileNotFoundError(f"Repertoire introuvable : {directory}")

    files: list[Path] = []
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(path)

    return sorted(files)


def _read_excel_silent(path: Path | str, **kwargs) -> pd.DataFrame:
    """Wrapper read_excel qui ignore le warning openpyxl 'Unknown extension'.

    Le fichier Web BottleNeck contient des extensions XML inconnues d'openpyxl,
    elles sont sans impact mais polluent la sortie.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Unknown extension is not supported",
            category=UserWarning,
        )
        return pd.read_excel(path, **kwargs)


def read_file(path: Path | str) -> pd.DataFrame:
    """Lit un fichier source et retourne un DataFrame.

    Le format est determine par l'extension :
        - .csv  -> pandas.read_csv (auto-detection separateur)
        - .xlsx -> pandas.read_excel (engine openpyxl)
        - .xls  -> pandas.read_excel (engine xlrd)
        - .txt  -> pandas.read_csv (separateur tabulation)

    Raises:
        ValueError: Si l'extension n'est pas prise en charge.
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


def read_bottleneck_sources(
    directory: Path | str = BOTTLENECK_DIR,
) -> dict[str, pd.DataFrame]:
    """Lit les 3 fichiers sources BottleNeck et retourne un dict.

    Returns:
        {
            'erp': DataFrame,        # 825 lignes
            'web': DataFrame,        # 1513 lignes
            'liaison': DataFrame,    # 825 lignes
        }

    Raises:
        FileNotFoundError: Si l'un des 3 fichiers est manquant.
    """
    directory = Path(directory)

    expected = {
        "erp": directory / ERP_FILENAME,
        "web": directory / WEB_FILENAME,
        "liaison": directory / LIAISON_FILENAME,
    }

    missing = [str(p) for p in expected.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Fichier(s) BottleNeck manquant(s) :\n  - " + "\n  - ".join(missing)
        )

    sources = {key: read_file(path) for key, path in expected.items()}

    for key, df in sources.items():
        logger.info("Source '%s' chargee : %d lignes", key, len(df))

    return sources


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    sources = read_bottleneck_sources()
    for name, df in sources.items():
        print(f"\n{name.upper()} : {len(df)} lignes, {len(df.columns)} colonnes")
        print(df.head(3))
