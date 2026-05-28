"""Calcul du chiffre d'affaires (étape 5 du pipeline).

Définition retenue avec Stéphane :
    CA produit = price * total_sales
    CA total   = somme des CA produits

`price` vient de l'ERP (prix unitaire HT), `total_sales` de WooCommerce
(nb d'unités vendues à vie).

Cible sur le dataset BottleNeck réel : CA total = 70 568,60 EUR.
"""

import logging

import pandas as pd


logger = logging.getLogger(__name__)


def add_revenue_column(
    products_df: pd.DataFrame,
    price_column: str = "price",
    sales_column: str = "total_sales",
    revenue_column: str = "ca",
) -> pd.DataFrame:
    """Ajoute (ou écrase) une colonne `ca` = price * total_sales.

    Protection contre les valeurs non numériques :
        - to_numeric(errors='coerce') : convertit ce qui est convertible,
          met NaN ailleurs (au lieu de planter).
        - fillna(0) : on traite les NaN comme 0 (hypothèse métier :
          "pas de prix ou pas de ventes connues -> CA contributif = 0").

    Factorisée parce qu'utilisée par revenue_per_product, total_revenue,
    revenue_summary et generate_reports.
    """
    products_with_revenue = products_df.copy()
    products_with_revenue[revenue_column] = (
        pd.to_numeric(products_with_revenue[price_column], errors="coerce").fillna(0)
        * pd.to_numeric(products_with_revenue[sales_column], errors="coerce").fillna(0)
    )
    return products_with_revenue


def revenue_per_product(
    products_df: pd.DataFrame,
    title_column: str = "post_title",
    sku_column: str = "sku",
    price_column: str = "price",
    sales_column: str = "total_sales",
) -> pd.DataFrame:
    """Retourne le CA par produit, trié décroissant.

    Colonnes (selon disponibilité) : sku, post_title, price, total_sales, ca.
    Utilisé pour l'onglet `CA_par_produit` du rapport Excel.
    """
    products_with_revenue = add_revenue_column(products_df, price_column, sales_column)

    # Filtre défensif : évite KeyError si une colonne manque
    # (cas des fixtures de test sans post_title par exemple).
    available_columns = [
        c for c in (sku_column, title_column, price_column, sales_column, "ca")
        if c in products_with_revenue.columns
    ]

    revenue_by_product_df = (
        products_with_revenue[available_columns]
        .sort_values("ca", ascending=False)
        .reset_index(drop=True)
    )
    logger.info("CA par produit : %d lignes", len(revenue_by_product_df))
    return revenue_by_product_df


def total_revenue(
    products_df: pd.DataFrame,
    price_column: str = "price",
    sales_column: str = "total_sales",
) -> float:
    """Retourne le CA total en float"""
    products_with_revenue = add_revenue_column(products_df, price_column, sales_column)
    total_ca = float(products_with_revenue["ca"].sum())
    logger.info("CA total : %.2f EUR", total_ca)
    return total_ca


def revenue_summary(
    products_df: pd.DataFrame,
    segment_column: str = "segment",
) -> pd.DataFrame:
    """CA agrégé par segment (premium / ordinary).

    Colonnes : segment, nb_produits, ca_segment, part_pct.
    Utile pour le pitch "les 30 millésimés représentent X % du CA".

    Raises:
        ValueError: si la colonne `segment` est manquante.
    """
    products_with_revenue = add_revenue_column(products_df)
    if segment_column not in products_with_revenue.columns:
        raise ValueError(f"Colonne '{segment_column}' manquante")

    # groupby().agg() = équivalent du GROUP BY SQL.
    # size = COUNT(*), sum = SUM(ca).
    revenue_by_segment_df = (
        products_with_revenue.groupby(segment_column)
        .agg(nb_produits=("ca", "size"), ca_segment=("ca", "sum"))
        .reset_index()
    )

    # Pourcentage avec garde-fou contre division par 0.
    total_ca = revenue_by_segment_df["ca_segment"].sum()
    revenue_by_segment_df["part_pct"] = (
        (revenue_by_segment_df["ca_segment"] / total_ca * 100).round(2)
        if total_ca else 0.0
    )
    return revenue_by_segment_df


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from scripts.python.extract_files import read_bottleneck_sources
    from scripts.python.clean_data import clean_erp, clean_web, clean_liaison
    from scripts.python.join_data import join_sources
    from scripts.python.identify_wines import classify_wines

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    bottleneck_sources = read_bottleneck_sources()
    consolidated_products = classify_wines(join_sources(
        clean_erp(bottleneck_sources["erp"]),
        clean_web(bottleneck_sources["web"]),
        clean_liaison(bottleneck_sources["liaison"]),
    ))
    print(f"\nCA total : {total_revenue(consolidated_products):,.2f} EUR")
    print(f"\nTop 5 produits :\n{revenue_per_product(consolidated_products).head(5)}")
    print(f"\nRésumé par segment :\n{revenue_summary(consolidated_products)}")
