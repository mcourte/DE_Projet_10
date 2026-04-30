"""Generation des rapports BottleNeck.

Trois livrables :

1. **Rapport Excel** (data/processed/rapport_BottleNeck_YYYY-MM.xlsx)
    Contient 4 onglets pour faciliter la consultation par Stephane :
        - CA_par_produit  : sku, post_title, price, total_sales, ca (trie decroissant)
        - CA_total        : une seule ligne avec le total et la date
        - Vins_premium    : produits classes 'premium' (= millesimes)
        - Vins_ordinaires : produits classes 'ordinary'

2. **CSV vins millesimes** (data/processed/vins_millesimes_YYYY-MM.csv)
    Liste des 30 vins classes 'premium', tries par CA decroissant.

3. **CSV vins ordinaires** (data/processed/vins_ordinaires_YYYY-MM.csv)
    Liste des 684 vins classes 'ordinary', tries par CA decroissant.

Les CSV utilisent le separateur `;` (compatible Excel FR) et l'encodage utf-8-sig
(BOM pour qu'Excel ouvre les accents correctement).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from scripts.python.calculate_revenue import (
    add_revenue_column,
    revenue_per_product,
    total_revenue,
)
from scripts.python.identify_wines import split_premium_ordinary


logger = logging.getLogger(__name__)


PROCESSED_DIR = Path("data/processed")


def _build_report_path(date: datetime | None = None) -> Path:
    """Construit le chemin du rapport Excel selon la date."""
    date = date or datetime.now()
    return PROCESSED_DIR / f"rapport_BottleNeck_{date:%Y-%m}.xlsx"


def _build_csv_paths(date: datetime | None = None) -> tuple[Path, Path]:
    """Retourne (chemin_csv_millesimes, chemin_csv_ordinaires)."""
    date = date or datetime.now()
    return (
        PROCESSED_DIR / f"vins_millesimes_{date:%Y-%m}.csv",
        PROCESSED_DIR / f"vins_ordinaires_{date:%Y-%m}.csv",
    )


def generate_excel_report(
    df_classified: pd.DataFrame,
    output_path: Path | str | None = None,
    date: datetime | None = None,
) -> Path:
    """Ecrit le rapport Excel multi-onglets.

    Args:
        df_classified: DataFrame consolide ET classifie (avec colonne 'segment').
        output_path: Chemin de sortie. Si None, defaut = data/processed/rapport_BottleNeck_YYYY-MM.xlsx
        date: Date a utiliser pour le nom (defaut = maintenant).

    Returns:
        Le chemin du fichier ecrit.
    """
    if "segment" not in df_classified.columns:
        raise ValueError(
            "Le DataFrame doit contenir une colonne 'segment'. "
            "Appelez identify_wines.classify_wines() avant."
        )

    output_path = Path(output_path) if output_path else _build_report_path(date)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. CA par produit
    ca_par_produit = revenue_per_product(df_classified)

    # 2. CA total (une ligne)
    ca_total_value = total_revenue(df_classified)
    ca_total_df = pd.DataFrame(
        {
            "indicateur": ["CA total"],
            "valeur_eur": [round(ca_total_value, 2)],
            "nb_produits": [len(df_classified)],
            "date_generation": [datetime.now().strftime("%Y-%m-%d %H:%M")],
        }
    )

    # 3 & 4. Premium / Ordinary
    df_with_ca = add_revenue_column(df_classified)
    premium, ordinary = split_premium_ordinary(df_with_ca)

    keep_cols = [
        c
        for c in (
            "sku",
            "post_title",
            "price",
            "stock_quantity",
            "stock_status",
            "total_sales",
            "ca",
            "segment",
        )
        if c in df_with_ca.columns
    ]
    premium = premium[keep_cols].sort_values("ca", ascending=False)
    ordinary = ordinary[keep_cols].sort_values("ca", ascending=False)

    # Ecriture multi-onglets
    logger.info("Ecriture du rapport Excel : %s", output_path)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        ca_par_produit.to_excel(writer, sheet_name="CA_par_produit", index=False)
        ca_total_df.to_excel(writer, sheet_name="CA_total", index=False)
        premium.to_excel(writer, sheet_name="Vins_premium", index=False)
        ordinary.to_excel(writer, sheet_name="Vins_ordinaires", index=False)

    logger.info("Rapport ecrit (%d Ko)", output_path.stat().st_size // 1024)
    return output_path


def export_wines_csv(
    df_classified: pd.DataFrame,
    millesimes_path: Path | str | None = None,
    ordinaires_path: Path | str | None = None,
    date: datetime | None = None,
) -> tuple[Path, Path]:
    """Exporte 2 CSV separes pour les vins millesimes et ordinaires.

    Format : separateur `;` + encodage `utf-8-sig` (compat Excel FR).

    Args:
        df_classified: DataFrame consolide ET classifie (colonne 'segment').
        millesimes_path: Chemin du CSV millesimes (defaut : auto par date).
        ordinaires_path: Chemin du CSV ordinaires (defaut : auto par date).
        date: Date pour le nommage par defaut.

    Returns:
        (chemin_millesimes, chemin_ordinaires)
    """
    if "segment" not in df_classified.columns:
        raise ValueError("Le DataFrame doit contenir une colonne 'segment'.")

    default_milles, default_ord = _build_csv_paths(date)
    millesimes_path = Path(millesimes_path) if millesimes_path else default_milles
    ordinaires_path = Path(ordinaires_path) if ordinaires_path else default_ord
    millesimes_path.parent.mkdir(parents=True, exist_ok=True)

    # On enrichit avec le CA pour faciliter l'analyse
    df_with_ca = add_revenue_column(df_classified)
    premium, ordinary = split_premium_ordinary(df_with_ca)

    keep_cols = [
        c
        for c in (
            "sku",
            "product_id",
            "post_title",
            "price",
            "stock_quantity",
            "stock_status",
            "total_sales",
            "ca",
            "segment",
            "segment_threshold",
        )
        if c in df_with_ca.columns
    ]
    premium = premium[keep_cols].sort_values("ca", ascending=False)
    ordinary = ordinary[keep_cols].sort_values("ca", ascending=False)

    premium.to_csv(millesimes_path, sep=";", index=False, encoding="utf-8-sig")
    ordinary.to_csv(ordinaires_path, sep=";", index=False, encoding="utf-8-sig")

    logger.info(
        "CSV millesimes ecrit : %s (%d lignes)",
        millesimes_path, len(premium),
    )
    logger.info(
        "CSV ordinaires ecrit : %s (%d lignes)",
        ordinaires_path, len(ordinary),
    )
    return millesimes_path, ordinaires_path


def generate_all_reports(
    df_classified: pd.DataFrame,
    date: datetime | None = None,
) -> dict[str, Path]:
    """Genere les 3 livrables : Excel + 2 CSV.

    Returns:
        dict avec les cles 'excel', 'csv_millesimes', 'csv_ordinaires'.
    """
    excel_path = generate_excel_report(df_classified, date=date)
    csv_milles, csv_ord = export_wines_csv(df_classified, date=date)
    return {
        "excel": excel_path,
        "csv_millesimes": csv_milles,
        "csv_ordinaires": csv_ord,
    }


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from scripts.python.extract_files import read_bottleneck_sources
    from scripts.python.clean_data import clean_erp, clean_web, clean_liaison
    from scripts.python.join_data import join_sources
    from scripts.python.identify_wines import classify_wines

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    src = read_bottleneck_sources()
    full = classify_wines(
        join_sources(
            clean_erp(src["erp"]),
            clean_web(src["web"]),
            clean_liaison(src["liaison"]),
        )
    )
    paths = generate_all_reports(full)
    print(f"Rapport Excel        : {paths['excel']}")
    print(f"CSV vins millesimes  : {paths['csv_millesimes']}")
    print(f"CSV vins ordinaires  : {paths['csv_ordinaires']}")
