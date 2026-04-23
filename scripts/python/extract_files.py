"""Lecture des fichiers sources (CSV, Excel, TXT) des 7 systemes ERP."""

from pathlib import Path


RAW_DIR = Path("data/raw")


def list_source_files(directory: Path) -> list[Path]:
    """Retourne la liste des fichiers sources a traiter."""
    # TODO : parcourir directory et retourner les CSV/XLSX/TXT
    raise NotImplementedError


def read_file(path: Path):
    """Lit un fichier selon son extension et retourne un DataFrame."""
    # TODO : dispatcher selon l'extension (pandas.read_csv / read_excel / ...)
    raise NotImplementedError


if __name__ == "__main__":
    files = list_source_files(RAW_DIR)
    print(f"{len(files)} fichiers detectes")
