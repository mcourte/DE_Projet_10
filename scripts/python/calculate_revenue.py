"""Calcul du chiffre d'affaires par produit et total.

Definition retenue :
    CA produit = price * total_sales
    CA total   = somme des CA produits

Cibles :
    CA total ~ 70 568 EUR (sur le dataset BottleNeck reel).
"""

from __future__ import annotations

import logging

import pandas as pd


logger = logging.getLogger(__name__)


def add_revenue_column(
    df: pd.DataFrame,
    price_column: str = "price",
    sales_column: str = "total_sales",
    revenue_column: str = "ca",
) -> pd.DataFrame:
    """Ajoute une colonne 'ca' = price * total_sales."""
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
    """Retourne le CA par produit, tri decroissant.

    Colonnes de sortie :
        sku, post_title, price, total_sales, ca
    """
    work = add_revenue_column(df, price_column, sales_column)
    cols = [c for c in (sku_column, title_column, price_column, sales_column, "ca")
            if c in work.columns]
    out = work[cols].sort_values("ca", ascending=False).reset_index(drop=True)
    logger.info("CA par produit : %d lignes", len(out))
    return out


def total_revenue(
    df: pd.DataFrame,
    price_column: str = "price",
    sales_column: str = "total_sales",
) -> float:
    """Retourne le CA total (float)."""
    work = add_revenue_column(df, price_column, sales_column)
    total = float(work["ca"].sum())
    logger.info("CA total : %.2f EUR", total)
    return total


def revenue_summary(
    df: pd.DataFrame,
    segment_column: str = "segment",
) -> pd.DataFrame:
    """Retourne un resume du CA par segment (premium / ordinary).

    Colonnes : segment, nb_produits, ca_segment, part_pct
    """
    work = add_revenue_column(df)
    if segment_column not in work.columns:
        raise ValueError(f"Colonne '{segment_column}' manquante")

    grouped = (
        work.groupby(segment_column)
        .agg(nb_produits=("ca", "size"), ca_segment=("ca", "sum"))
        .reset_index()
    )
    total = grouped["ca_segment"].sum()
    grouped["part_pct"] = (grouped["ca_segment"] / total * 100).round(2) if total else 0.0
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
