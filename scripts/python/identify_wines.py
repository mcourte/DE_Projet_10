"""Classification des vins : millesimes (premium) vs ordinaires.

----------------------------------------------------------------------------
ROLE DE CE MODULE :
    4e etape du pipeline. On prend la table consolidee (sortie de join_data)
    et on attribue a chaque produit un segment 'premium' ou 'ordinary'
    en fonction de son prix.

METHODE STATISTIQUE RETENUE PAR STEPHANE : Z-SCORE SUR LE PRIX

    Le Z-score d'une valeur mesure de combien d'ecarts-type elle s'eloigne
    de la moyenne du dataset :

        z_score(prix) = (prix - moyenne) / ecart_type

    Plus le Z-score est eleve, plus le produit est "atypique" par rapport
    a la masse. On considere un vin comme MILLESIME (premium) si :

        z_score > 1.96

    Le seuil 1.96 correspond au quantile 97.5% de la loi normale, soit le
    seuil classique du test bilateral a 5% de risque d'erreur. En pratique :
    "ce produit est dans les 2.5% les plus chers, c'est statistiquement un
    cas particulier". Lecture metier : c'est un millesime.

EQUIVALENCE PRATIQUE :
    Verifier `z_score > 1.96` revient a verifier `prix > mean + 1.96 * std`.
    C'est ce qu'on calcule dans `compute_zscore_thresholds()` -> upper.

SUR LE DATASET BOTTLENECK REEL :
    moyenne     ~ 32.49 EUR
    ecart-type  ~ 32 EUR
    seuil upper ~ 95 EUR
    -> 30 vins millesimes / 684 vins ordinaires.

ALTERNATIVE : METHODE IQR (boxplot)
    Conservee comme option (parametre method='iqr') pour comparaison.
    Plus permissive : detecte un peu plus de "outliers superieurs" que
    le Z-score 1.96. On garde le code pour la flexibilite, mais
    par defaut on utilise Z-score (cible Stephane).
----------------------------------------------------------------------------
"""

import logging
from typing import NamedTuple, Optional

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


# Seuil par defaut pour Z-score : 1.96 = quantile 97.5% de la loi normale.
DEFAULT_Z_THRESHOLD = 1.96


# NamedTuple = mini-classe immuable avec acces par .attribut.
# C'est plus simple qu'une @dataclass et ca documente bien les valeurs
# qu'une fonction renvoie (au lieu d'un tuple anonyme ou d'un dict).
# Utilisation : `t = compute_iqr_thresholds(prices); t.q1, t.upper, ...`.
class IQRThresholds(NamedTuple):
    """Seuils calcules par la methode IQR (boxplot)."""
    q1: float       # 1er quartile (25%)
    q3: float       # 3e quartile (75%)
    iqr: float      # IQR = Q3 - Q1
    lower: float    # Q1 - multiplier * IQR (seuil bas, outliers inferieurs)
    upper: float    # Q3 + multiplier * IQR (seuil haut, outliers superieurs)


class ZScoreThresholds(NamedTuple):
    """Seuils calcules par la methode Z-score."""
    mean: float        # moyenne du dataset
    std: float         # ecart-type
    threshold: float   # le z-score seuil (typiquement 1.96)
    upper: float       # = mean + threshold * std (le prix limite)


def compute_iqr_thresholds(
    prices: pd.Series, multiplier: float = 1.5
) -> IQRThresholds:
    """Calcule les seuils IQR (boxplot) pour une serie de prix.

    METHODE :
        Q1 = quantile 25%, Q3 = quantile 75%, IQR = Q3 - Q1.
        Une valeur est outlier si :
            - inferieur a Q1 - multiplier * IQR (outlier bas)
            - superieur a Q3 + multiplier * IQR (outlier haut)
        Le multiplier standard est 1.5 (boxplot classique de Tukey).
    """
    q1 = float(prices.quantile(0.25))
    q3 = float(prices.quantile(0.75))
    iqr = q3 - q1
    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr
    return IQRThresholds(q1=q1, q3=q3, iqr=iqr, lower=lower, upper=upper)


def compute_zscore_thresholds(
    prices: pd.Series, threshold: float = DEFAULT_Z_THRESHOLD
) -> ZScoreThresholds:
    """Calcule les seuils Z-score pour une serie de prix.

    METHODE :
        On calcule la moyenne et l'ecart-type. Un prix sera outlier
        superieur s'il depasse mean + threshold*std.

        Equivalent a `(prix - mean) / std > threshold`.
    """
    mean = float(prices.mean())
    std = float(prices.std())
    upper = mean + threshold * std
    return ZScoreThresholds(mean=mean, std=std, threshold=threshold, upper=upper)


def classify_wines(
    df: pd.DataFrame,
    price_column: str = "price",
    method: str = "zscore",
    threshold: Optional[float] = None,
) -> pd.DataFrame:
    """Ajoute une colonne 'segment' au DataFrame de produits.

    Args:
        df:           DataFrame consolide.
        price_column: Nom de la colonne prix.
        method:       'zscore' (defaut, methode Stephane) ou 'iqr'.
        threshold:    Seuil personnalise. Defaut :
                          - 'zscore' -> 1.96 (95% de confiance)
                          - 'iqr'    -> 1.5  (boxplot standard)

    Returns:
        Copie de df avec 2 nouvelles colonnes :
            - segment           : 'premium' (= vin millesime) ou 'ordinary'
            - segment_threshold : valeur du prix seuil utilisee (utile pour
                                  documenter la decision dans le rapport)

    Raises:
        ValueError: si la colonne prix est absente ou si method est inconnu.
    """
    # Verifications defensives en debut de fonction : on echoue tot et clairement.
    if price_column not in df.columns:
        raise ValueError(f"Colonne '{price_column}' introuvable")

    if method not in ("zscore", "iqr"):
        raise ValueError(f"method doit etre 'zscore' ou 'iqr', recu : {method}")

    out = df.copy()
    # On retire les NaN AVANT le calcul stat : sinon mean/std pourraient
    # etre faussees ou retourner NaN.
    prices = out[price_column].dropna()

    if method == "zscore":
        thr = threshold if threshold is not None else DEFAULT_Z_THRESHOLD
        zt = compute_zscore_thresholds(prices, threshold=thr)
        upper = zt.upper
        logger.info(
            "Seuils Z-score : mean=%.2f std=%.2f z=%.2f -> upper=%.2f",
            zt.mean, zt.std, zt.threshold, upper,
        )
    else:
        # method == "iqr"
        mult = threshold if threshold is not None else 1.5
        iqr_t = compute_iqr_thresholds(prices, multiplier=mult)
        upper = iqr_t.upper
        logger.info(
            "Seuils IQR : Q1=%.2f Q3=%.2f IQR=%.2f -> upper=%.2f",
            iqr_t.q1, iqr_t.q3, iqr_t.iqr, upper,
        )

    # np.where(condition, valeur_si_vrai, valeur_si_faux) :
    # comparable a un IF vectorise. Plus rapide qu'une boucle for ou
    # qu'une comprehension de liste sur un gros DataFrame.
    out["segment"] = np.where(out[price_column] > upper, "premium", "ordinary")
    out["segment_threshold"] = upper

    # value_counts() retourne le nombre d'occurrences de chaque valeur unique.
    # `.get('premium', 0)` : si aucun premium, on retourne 0 au lieu d'un KeyError.
    counts = out["segment"].value_counts()
    n_p = int(counts.get("premium", 0))
    n_o = int(counts.get("ordinary", 0))
    logger.info(
        "Classification (%s) : %d premium / %d ordinary",
        method, n_p, n_o,
    )

    return out


def split_premium_ordinary(df: pd.DataFrame):
    """Decoupe le DataFrame en deux selon la colonne 'segment'.

    Pratique pour les exports (un onglet Vins_premium et un onglet
    Vins_ordinaires dans le rapport Excel, par exemple).

    Returns:
        (premium, ordinary) : tuple de deux DataFrames (peut etre destructure).

    Raises:
        ValueError: si la colonne 'segment' n'existe pas (= classify_wines
                    n'a pas ete appele en amont).
    """
    if "segment" not in df.columns:
        raise ValueError(
            "La colonne 'segment' est manquante. "
            "Appelez classify_wines() d'abord."
        )
    # Boolean indexing : df[df["segment"] == "premium"] retourne uniquement
    # les lignes ou cette condition est vraie. C'est l'equivalent pandas
    # d'un WHERE en SQL.
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
    classified = classify_wines(full)  # Z-score 1.96 par defaut
    premium, ordinary = split_premium_ordinary(classified)
    print(f"\nMillesimes (premium) : {len(premium)} vins (cible : 30)")
    print(f"Ordinaires           : {len(ordinary)} vins (cible : 684)")
