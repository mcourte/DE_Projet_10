"""Génération des livrables BottleNeck (rapport Excel + 2 CSV).

3 fichiers produits dans `data/processed/` :

    1. rapport_BottleNeck_YYYY-MM.xlsx — 4 onglets :
         CA_par_produit, CA_total, Vins_premium, Vins_ordinaires
    2. vins_millesimes_YYYY-MM.csv    — ~30 vins premium
    3. vins_ordinaires_YYYY-MM.csv    — ~684 vins ordinaires

CSV : séparateur `;` + encodage `utf-8-sig` (Excel FR ouvre direct avec
accents corrects, sans étape de conversion).
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from scripts.python.calculate_revenue import (
    add_revenue_column,
    revenue_per_product,
    total_revenue,
)
from scripts.python.identify_wines import split_premium_ordinary


logger = logging.getLogger(__name__)

# Dossier de sortie centralisé pour tous les rapports générés. 
PROCESSED_DIR = Path("data/processed")

# Colonnes conservées dans les onglets et CSV détaillés (ordre voulu).
_DETAIL_COLUMNS = (
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


def _prepare_segments(classified_products_df: pd.DataFrame):
    """Ajoute la colonne `ca`, sépare premium/ordinary, trie par CA desc.

    Mutualisé entre le rapport Excel et l'export CSV : la logique de
    découpe et de tri est strictement la même pour les deux livrables.
    """
    products_with_revenue = add_revenue_column(classified_products_df)
    premium_df, ordinary_df = split_premium_ordinary(products_with_revenue)
    available_columns = [
        c for c in _DETAIL_COLUMNS if c in products_with_revenue.columns
    ]
    premium_df = premium_df[available_columns].sort_values("ca", ascending=False)
    ordinary_df = ordinary_df[available_columns].sort_values("ca", ascending=False)
    return premium_df, ordinary_df


def generate_excel_report(
    classified_products_df: pd.DataFrame,
    output_path: Optional[Path] = None,
    date: Optional[datetime] = None,
) -> Path:
    """Écrit le rapport Excel à 4 onglets.

    Raises:
        ValueError: si la colonne 'segment' est absente (= classify_wines
                    n'a pas été appelé en amont).
    """
    if "segment" not in classified_products_df.columns:
        raise ValueError(
            "Le DataFrame doit contenir une colonne 'segment'. "
            "Appelez identify_wines.classify_wines() avant."
        )

    # Chemin par défaut : un fichier par mois (historisation naturelle).
    date = date or datetime.now()
    output_path = Path(output_path) if output_path else (
        PROCESSED_DIR / f"rapport_BottleNeck_{date:%Y-%m}.xlsx"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Onglet 1 : CA par produit (trié par ventes décroissantes).
    revenue_by_product_df = revenue_per_product(classified_products_df)

    # Onglet 2 : KPI haut niveau (1 ligne : CA total, nb produits, date).
    ca_total_kpi_df = pd.DataFrame({
        "indicateur": ["CA total"],
        "valeur_eur": [round(total_revenue(classified_products_df), 2)],
        "nb_produits": [len(classified_products_df)],
        "date_generation": [datetime.now().strftime("%Y-%m-%d %H:%M")],
    })

    # Onglets 3 et 4 : millésimés / ordinaires.
    premium_df, ordinary_df = _prepare_segments(classified_products_df)

    # `with pd.ExcelWriter(...)` : ferme le fichier même si exception.
    logger.info(f"Écriture du rapport Excel : {output_path}")
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        revenue_by_product_df.to_excel(writer, sheet_name="CA_par_produit", index=False)
        ca_total_kpi_df.to_excel(writer, sheet_name="CA_total", index=False)
        premium_df.to_excel(writer, sheet_name="Vins_premium", index=False)
        ordinary_df.to_excel(writer, sheet_name="Vins_ordinaires", index=False)

    taille_ko = output_path.stat().st_size // 1024
    logger.info(f"Rapport écrit ({taille_ko} Ko)")
    return output_path


def export_wines_csv(
    classified_products_df: pd.DataFrame,
    millesimes_path: Optional[Path] = None,
    ordinaires_path: Optional[Path] = None,
    date: Optional[datetime] = None,
):
    """Exporte 2 CSV séparés (millésimés / ordinaires).

    Raises:
        ValueError: si la colonne 'segment' est absente.
    """
    if "segment" not in classified_products_df.columns:
        raise ValueError("Le DataFrame doit contenir une colonne 'segment'.")

    date = date or datetime.now()
    millesimes_path = Path(millesimes_path) if millesimes_path else (
        PROCESSED_DIR / f"vins_millesimes_{date:%Y-%m}.csv"
    )
    ordinaires_path = Path(ordinaires_path) if ordinaires_path else (
        PROCESSED_DIR / f"vins_ordinaires_{date:%Y-%m}.csv"
    )
    millesimes_path.parent.mkdir(parents=True, exist_ok=True)

    premium_df, ordinary_df = _prepare_segments(classified_products_df)

    # sep=';' + utf-8-sig : Excel FR ouvre direct avec accents corrects.
    premium_df.to_csv(millesimes_path, sep=";", index=False, encoding="utf-8-sig")
    ordinary_df.to_csv(ordinaires_path, sep=";", index=False, encoding="utf-8-sig")

    logger.info(f"CSV millésimes écrit : {millesimes_path} ({len(premium_df)} lignes)")
    logger.info(f"CSV ordinaires écrit : {ordinaires_path} ({len(ordinary_df)} lignes)")
    return millesimes_path, ordinaires_path


def generate_all_reports(
    classified_products_df: pd.DataFrame,
    date: Optional[datetime] = None,
) -> dict:
    """Génère les 3 livrables (Excel + 2 CSV). Appelée par run_pipeline."""
    excel_path = generate_excel_report(classified_products_df, date=date)
    csv_millesimes_path, csv_ordinaires_path = export_wines_csv(
        classified_products_df, date=date,
    )
    return {
        "excel": excel_path,
        "csv_millesimes": csv_millesimes_path,
        "csv_ordinaires": csv_ordinaires_path,
    }


if __name__ == "__main__":
    # Démo : on lance le pipeline complet jusqu'à la génération des livrables.
    import sys

    sys.path.insert(0, ".")
    from scripts.python.extract_files import read_bottleneck_sources
    from scripts.python.clean_data import clean_erp, clean_web, clean_liaison
    from scripts.python.join_data import join_sources
    from scripts.python.identify_wines import classify_wines

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    bottleneck_sources = read_bottleneck_sources()
    classified_products_df = classify_wines(join_sources(
        clean_erp(bottleneck_sources["erp"]),
        clean_web(bottleneck_sources["web"]),
        clean_liaison(bottleneck_sources["liaison"]),
    ))
    output_paths = generate_all_reports(classified_products_df)
    for label, path in output_paths.items():
        print(f"  {label:18s} : {path}")
