"""Classification des vins : millesimes (premium) vs ordinaires.

Methode statistique retenue par Stephane : **Z-score sur le prix**.

    z_score(prix) = (prix - moyenne) / ecart_type

    Un vin est considere comme MILLESIME (premium) si z_score > 1.96
    (seuil correspondant au quantile 97.5% de la loi normale, soit
    le test bilateral classique a 5% de risque d'erreur).

Sur le dataset BottleNeck :
    moyenne   = 32.49 EUR
    ecart-type = ~32 EUR
    seuil     = mean + 1.96 * std
    -> 30 vins millesimes / 684 vins ordinaires

Note : la methode IQR (boxplot) est conservee comme alternative, accessible
via le parametre `method='iqr'`. Elle donne 32 outliers superieurs sur ce
dataset, soit un peu plus large que le Z-score 1.96.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


# Seuil par defaut (Z-score) -- 1.96 = quantile 97.5% de la loi normale
DEFAULT_Z_THRESHOLD = 1.96


@dataclass
class IQRThresholds:
    """Seuils calcules par la methode IQR sur la colonne prix."""

    q1: float
    q3: float
    iqr: float
    lower: float
    upper: float


@dataclass
class ZScoreThresholds:
    """Seuils calcules par la methode Z-score."""

    mean: float
    std: float
    threshold: float
    upper: float  # mean + threshold * std


def compute_iqr_thresholds(
    prices: pd.Series, multiplier: float = 1.5
) -> IQRThresholds:
    """Calcule les seuils IQR pour une serie de prix."""
    q1 = float(prices.quantile(0.25))
    q3 = float(prices.quantile(0.75))
    iqr = q3 - q1
    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr
    return IQRThresholds(q1=q1, q3=q3, iqr=iqr, lower=lower, upper=upper)


def compute_zscore_thresholds(
    prices: pd.Series, threshold: float = DEFAULT_Z_THRESHOLD
) -> ZScoreThresholds:
    """Calcule les seuils Z-score pour une serie de prix."""
    mean = float(prices.mean())
    std = float(prices.std())
    upper = mean + threshold * std
    return ZScoreThresholds(mean=mean, std=std, threshold=threshold, upper=upper)


def classify_wines(
    df: pd.DataFrame,
    price_column: str = "price",
    method: Literal["zscore", "iqr"] = "zscore",
    threshold: float | None = None,
) -> pd.DataFrame:
    """Ajoute une colonne 'segment' au DataFrame de produits.

    Args:
        df: DataFrame consolide.
        price_column: Nom de la colonne prix.
        method: 'zscore' (defaut, methode Stephane) ou 'iqr'.
        threshold: Seuil personnalise. Defaut :
            - 'zscore' -> 1.96 (95% de confiance)
            - 'iqr'    -> 1.5  (boxplot standard)

    Returns:
        Copie de df avec :
            - segment : 'premium' (= vin millesime) ou 'ordinary'
            - segment_threshold : valeur du prix seuil utilisee
    """
    if price_column not in df.columns:
        raise ValueError(f"Colonne '{price_column}' introuvable")

    out = df.copy()
    prices = out[price_column].dropna()

    if method == "zscore":
        thr = threshold if threshold is not None else DEFAULT_Z_THRESHOLD
        zt = compute_zscore_thresholds(prices, threshold=thr)
        upper = zt.upper
        logger.info(
            "Seuils Z-score : mean=%.2f std=%.2f z=%.2f -> upper=%.2f",
            zt.mean, zt.std, zt.threshold, upper,
        )
    elif method == "iqr":
        mult = threshold if threshold is not None else 1.5
        iqr_t = compute_iqr_thresholds(prices, multiplier=mult)
        upper = iqr_t.upper
        logger.info(
            "Seuils IQR : Q1=%.2f Q3=%.2f IQR=%.2f -> upper=%.2f",
            iqr_t.q1, iqr_t.q3, iqr_t.iqr, upper,
        )
    else:
        raise ValueError(f"method doit etre 'zscore' ou 'iqr', recu : {method}")

    out["segment"] = np.where(
        out[price_column] > upper, "premium", "ordinary"
    )
    out["segment_threshold"] = upper

    counts = out["segment"].value_counts()
    n_p = int(counts.get("premium", 0))
    n_o = int(counts.get("ordinary", 0))
    logger.info("Classification (%s) : %d premium / %d ordinary", method, n_p, n_o)

    return out


def split_premium_ordinary(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Decoupe le DataFrame en deux selon la colonne 'segment'."""
    if "segment" not in df.columns:
        raise ValueError("La colonne 'segment' est manquante. "
                         "Appelez classify_wines() d'abord.")
    premium = df[df["segment"] == "premium"].reset_index(drop=True)
    ordinary = df[df["segment"] == "ordinary"].reset_index(drop=True)
    return premium, ordinary


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from scripts.python.extract_files import read_bottleneck_sources
    from scripts.python.clean_data import clean_erp, clean_web, clean_liaison
    from scripts.python.join_data import join_sources

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    src = read_bottleneck_sources()
    full = join_sources(
        clean_erp(src["erp"]),
        clean_web(src["web"]),
        clean_liaison(src["liaison"]),
    )
    classified = classify_wines(full)  # methode Z-score par defaut
    premium, ordinary = split_premium_ordinary(classified)
    print(f"\nMillesimes (premium) : {len(premium)} vins (cible : 30)")
    print(f"Ordinaires            : {len(ordinary)} vins (cible : 684)")
