"""Calcul du chiffre d'affaires par produit et au total.

----------------------------------------------------------------------------
ROLE DE CE MODULE :
    5e etape du pipeline. On calcule les indicateurs financiers a partir
    de la table consolidee et classifiee.

DEFINITION RETENUE (validee avec Stephane) :

    CA produit = price * total_sales
    CA total   = somme des CA produits

    `price` vient de l'ERP (prix de vente unitaire HT).
    `total_sales` vient de WooCommerce (nombre d'unites vendues a vie).

CIBLE :
    CA total = 70 568,60 EUR (sur le dataset BottleNeck reel).
----------------------------------------------------------------------------
"""

import logging

import pandas as pd


logger = logging.getLogger(__name__)


def add_revenue_column(
    df: pd.DataFrame,
    price_column: str = "price",
    sales_column: str = "total_sales",
    revenue_column: str = "ca",
) -> pd.DataFrame:
    """Ajoute (ou ecrase) une colonne `ca` = price * total_sales.

    PROTECTION CONTRE LES VALEURS NON NUMERIQUES :
        - to_numeric(errors='coerce') : convertit ce qui est convertible,
          met NaN ailleurs (au lieu de planter).
        - fillna(0) : on remplace les NaN par 0 pour qu'ils ne polluent
          pas le total. Hypothese metier : "pas de prix ou pas de ventes
          connues -> CA contributif = 0".

    Cette fonction est utilisee plusieurs fois (par revenue_per_product,
    total_revenue, revenue_summary, generate_reports), donc on la factorise.
    """
    out = df.copy()
    out[revenue_column] = (
        pd.to_numeric(out[price_column], errors="coerce").fillna(0)
        * pd.to_numeric(out[sales_column], errors="coerce").fillna(0)
    )
    return out


def revenue_per_product(
    df: pd.DataFrame,
    title_column: str = "post_title",
    sku_column: str = "sku",
    price_column: str = "price",
    sales_column: str = "total_sales",
) -> pd.DataFrame:
    """Retourne le CA par produit, trie decroissant.

    Colonnes de sortie (selon disponibilite dans `df`) :
        sku, post_title, price, total_sales, ca.

    UTILE POUR :
        - l'onglet `CA_par_produit` du rapport Excel.
        - identifier les top vendeurs en un coup d'oeil.
    """
    work = add_revenue_column(df, price_column, sales_column)

    # On filtre les colonnes qui existent reellement dans le DataFrame.
    # Cela evite un KeyError si l'une d'elles manque (par exemple,
    # `post_title` peut etre absent dans certains tests unitaires).
    cols = [
        c for c in (sku_column, title_column, price_column, sales_column, "ca")
        if c in work.columns
    ]

    # sort_values('ca', ascending=False) -> les meilleurs CA en haut.
    out = work[cols].sort_values("ca", ascending=False).reset_index(drop=True)
    logger.info("CA par produit : %d lignes", len(out))
    return out


def total_revenue(
    df: pd.DataFrame,
    price_column: str = "price",
    sales_column: str = "total_sales",
) -> float:
    """Retourne le CA total (float).

    On reutilise `add_revenue_column` puis on somme la colonne `ca`.
    Le `float(...)` explicite la conversion : sum() retourne un numpy.float64,
    or on prefere un float Python natif pour les logs et les comparaisons.
    """
    work = add_revenue_column(df, price_column, sales_column)
    total = float(work["ca"].sum())
    logger.info("CA total : %.2f EUR", total)
    return total


def revenue_summary(
    df: pd.DataFrame,
    segment_column: str = "segment",
) -> pd.DataFrame:
    """Resume du CA par segment (premium / ordinary).

    Colonnes de sortie :
        segment, nb_produits, ca_segment, part_pct.

    UTILE POUR :
        - savoir quelle part de CA vient des vins millesimes vs ordinaires.
        - le pitch commercial "les 30 millesimes representent X% du CA".
    """
    work = add_revenue_column(df)
    if segment_column not in work.columns:
        raise ValueError(f"Colonne '{segment_column}' manquante")

    # groupby(...).agg(...) : equivalent pandas du GROUP BY SQL.
    # On cree 2 nouvelles colonnes :
    #   - nb_produits = nombre de lignes par segment (size = COUNT(*))
    #   - ca_segment  = somme des CA par segment       (sum)
    grouped = (
        work.groupby(segment_column)
        .agg(nb_produits=("ca", "size"), ca_segment=("ca", "sum"))
        .reset_index()
    )

    # Calcul du pourcentage. On protege contre la division par zero
    # (cas tres improbable mais propre defensivement).
    total = grouped["ca_segment"].sum()
    if total:
        grouped["part_pct"] = (grouped["ca_segment"] / total * 100).round(2)
    else:
        grouped["part_pct"] = 0.0
    return grouped


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from scripts.python.extract_files import read_bottleneck_sources
    from scripts.python.clean_data import clean_erp, clean_web, clean_liaison
    from scripts.python.join_data import join_sources
    from scripts.python.identify_wines import classify_wines

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    src = read_bottleneck_sources()
    full = join_sources(
        clean_erp(src["erp"]),
        clean_web(src["web"]),
        clean_liaison(src["liaison"]),
    )
    full = classify_wines(full)
    print(f"\nCA total : {total_revenue(full):,.2f} EUR")
    print(f"\nTop 5 produits :\n{revenue_per_product(full).head(5)}")
    print(f"\nResume par segment :\n{revenue_summary(full)}")
