"""Classification des vins : millésimés (premium) vs ordinaires.

Méthode retenue par Stéphane : Z-SCORE SUR LE PRIX.

    z_score(prix) = (prix - moyenne) / écart-type

Un vin est classé MILLÉSIMÉ si son z-score > 1.96 (= les 2,5 % les
plus chers, seuil classique du test bilatéral à 5 %). Équivalent à
`prix > moyenne + 1.96 * écart-type` -> c'est ce qu'on calcule comme
seuil `upper`.

Sur le dataset BottleNeck réel :
    moyenne ~ 32,49 €   écart-type ~ 32 €   seuil ~ 87 €
    -> 30 vins millésimés / 684 vins ordinaires.

Méthode alternative testée (IQR / Tukey) : voir le journal de bord —
elle donnait 32 vins, non retenue. Code IQR retiré pour simplifier.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)

# Seuil Z-score par défaut = 1,96 (quantile 97,5 % de la loi normale).
DEFAULT_Z_THRESHOLD = 1.96


def classify_wines(
    products_df: pd.DataFrame,
    price_column: str = "price",
    threshold: Optional[float] = None,
) -> pd.DataFrame:
    """Ajoute les colonnes 'segment' et 'segment_threshold' au DataFrame.

    Args:
        price_column: nom de la colonne prix (défaut : 'price').
        threshold:    seuil z-score personnalisé. Défaut : 1.96.

    Returns:
        Copie de products_df avec :
            - segment           : 'premium' ou 'ordinary'
            - segment_threshold : valeur du prix seuil (pour documenter
                                  la décision dans le rapport)

    Raises:
        ValueError: si la colonne prix est absente.
    """
    if price_column not in products_df.columns:
        raise ValueError(f"Colonne '{price_column}' introuvable")

    classified_products_df = products_df.copy()
    # On retire les NaN AVANT le calcul stat (sinon mean/std seraient NaN).
    prices = classified_products_df[price_column].dropna()

    # Calcul du seuil Z-score : un produit est 'premium' si son prix dépasse
    # mean + threshold × std (équivalent à z-score > threshold).
    z_threshold = threshold if threshold is not None else DEFAULT_Z_THRESHOLD
    mean_price = float(prices.mean())
    std_price = float(prices.std())
    premium_price_threshold = mean_price + z_threshold * std_price
    logger.info(
        f"Seuils Z-score : mean={mean_price:.2f} std={std_price:.2f} "
        f"z={z_threshold:.2f} -> upper={premium_price_threshold:.2f}"
    )

    # np.where(condition, val_si_vrai, val_si_faux) = un IF vectorisé.
    # Bien plus rapide qu'une boucle for sur un gros DataFrame.
    classified_products_df["segment"] = np.where(
        classified_products_df[price_column] > premium_price_threshold,
        "premium",
        "ordinary",
    )
    classified_products_df["segment_threshold"] = premium_price_threshold

    # .get('premium', 0) : 0 si aucun premium, évite un KeyError.
    segment_counts = classified_products_df["segment"].value_counts()
    nb_premium = int(segment_counts.get("premium", 0))
    nb_ordinary = int(segment_counts.get("ordinary", 0))
    logger.info(f"Classification Z-score : {nb_premium} premium / {nb_ordinary} ordinary")

    return classified_products_df


def split_premium_ordinary(classified_products_df: pd.DataFrame):
    """Découpe le DataFrame en deux selon la colonne 'segment'.

    Pratique pour les exports : un onglet Vins_premium, un onglet
    Vins_ordinaires dans le rapport Excel.

    Returns:
        (premium_df, ordinary_df) — tuple de deux DataFrames (déstructurable).

    Raises:
        ValueError: si la colonne 'segment' n'existe pas
                    (= classify_wines n'a pas été appelé en amont).
    """
    if "segment" not in classified_products_df.columns:
        raise ValueError(
            "La colonne 'segment' est manquante. "
            "Appelez classify_wines() d'abord."
        )
    # Boolean indexing : df[df["col"] == val] = équivalent du WHERE SQL.
    premium_df = (
        classified_products_df[classified_products_df["segment"] == "premium"]
        .reset_index(drop=True)
    )
    ordinary_df = (
        classified_products_df[classified_products_df["segment"] == "ordinary"]
        .reset_index(drop=True)
    )
    return premium_df, ordinary_df


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from scripts.python.extract_files import read_bottleneck_sources
    from scripts.python.clean_data import clean_erp, clean_web, clean_liaison
    from scripts.python.join_data import join_sources

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    bottleneck_sources = read_bottleneck_sources()
    consolidated_products_df = join_sources(
        clean_erp(bottleneck_sources["erp"]),
        clean_web(bottleneck_sources["web"]),
        clean_liaison(bottleneck_sources["liaison"]),
    )
    classified_products_df = classify_wines(consolidated_products_df)  # Z-score 1.96
    premium_df, ordinary_df = split_premium_ordinary(classified_products_df)
    print(f"\nMillésimés (premium) : {len(premium_df)} vins (cible : 30)")
    print(f"Ordinaires           : {len(ordinary_df)} vins (cible : 684)")
