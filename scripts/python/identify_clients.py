"""Identification des clients : premium vs ordinary.

La regle de classification (a confirmer avec Stephane) :
    - un client est "premium" si <TODO : critere>
    - sinon il est "ordinary"
"""

import pandas as pd


def classify(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute une colonne 'segment' avec les valeurs 'premium' / 'ordinary'."""
    # TODO : implementer la regle metier
    raise NotImplementedError


if __name__ == "__main__":
    pass
