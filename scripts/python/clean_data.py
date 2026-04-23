"""Nettoyage et dedoublonnage des donnees.

Chiffres cibles (donnes par Stephane) :
    - 621 lignes apres dedoublonnage des commandes
    - 1428 lignes apres nettoyage des commandes
"""

import pandas as pd


def deduplicate(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Supprime les doublons sur les colonnes cles."""
    # TODO
    raise NotImplementedError


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Nettoyage : trim, casse, formats de date, valeurs aberrantes."""
    # TODO
    raise NotImplementedError


if __name__ == "__main__":
    pass
