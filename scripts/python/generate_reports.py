"""Generation des livrables BottleNeck.

----------------------------------------------------------------------------
ROLE DE CE MODULE :
    Avant-derniere etape du pipeline. On materialise les resultats dans
    des fichiers que Stephane et Laurent (le manager) peuvent ouvrir
    dans Excel sans avoir Python ni DuckDB d'installe.

TROIS LIVRABLES :

    1. **Rapport Excel** -> data/processed/rapport_BottleNeck_YYYY-MM.xlsx
       Un seul fichier .xlsx, 4 onglets pour faciliter la consultation :
           - CA_par_produit  : sku, post_title, price, total_sales, ca
                                (trie decroissant, le top vendeur en haut)
           - CA_total        : une seule ligne d'indicateurs avec la date
           - Vins_premium    : produits classes 'premium' (= millesimes)
           - Vins_ordinaires : produits classes 'ordinary'

    2. **CSV vins millesimes** -> data/processed/vins_millesimes_YYYY-MM.csv
       Liste des ~30 vins classes 'premium', tries par CA decroissant.

    3. **CSV vins ordinaires** -> data/processed/vins_ordinaires_YYYY-MM.csv
       Liste des ~684 vins classes 'ordinary', tries par CA decroissant.

POURQUOI 2 FORMATS (XLSX ET CSV) :
    - L'Excel est facile a consulter visuellement, multi-onglets.
    - Les CSV sont l'archive "donnees brutes" qu'on peut reimporter dans
      n'importe quel autre outil (PowerBI, Tableau, autre Python...).

CONFIGURATION CSV :
    sep=';' + encoding='utf-8-sig'.
    - `;` car Excel FR utilise par defaut `;` comme separateur (`,` est
      reserve aux decimales).
    - `utf-8-sig` ajoute un BOM (byte-order mark) en debut de fichier qui
      indique a Excel que le fichier est en UTF-8 -> les accents
      s'affichent correctement.
----------------------------------------------------------------------------
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


# Repertoire de sortie centralise. Si on veut changer l'emplacement
# des livrables, on modifie cette constante a un seul endroit.
PROCESSED_DIR = Path("data/processed")


def _build_report_path(date: Optional[datetime] = None) -> Path:
    """Construit le chemin du rapport Excel selon la date du run.

    Format : `rapport_BottleNeck_YYYY-MM.xlsx` (un fichier par mois).
    Avec le pipeline mensuel, ca evite d'ecraser le rapport precedent
    et ca permet l'historisation naturelle.
    """
    date = date or datetime.now()
    return PROCESSED_DIR / f"rapport_BottleNeck_{date:%Y-%m}.xlsx"


def _build_csv_paths(date: Optional[datetime] = None):
    """Retourne (chemin_csv_millesimes, chemin_csv_ordinaires)."""
    date = date or datetime.now()
    return (
        PROCESSED_DIR / f"vins_millesimes_{date:%Y-%m}.csv",
        PROCESSED_DIR / f"vins_ordinaires_{date:%Y-%m}.csv",
    )


# Colonnes conservees dans les onglets / CSV detail (dans l'ordre).
# On centralise pour que rapport Excel et CSV aient la MEME structure.
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


def _detail_columns_present(df: pd.DataFrame) -> list:
    """Retourne la liste des colonnes detail effectivement presentes dans df.

    Utile pour eviter un KeyError si une colonne est absente (par exemple
    `segment_threshold` n'existe pas dans les fixtures de test).
    """
    return [c for c in _DETAIL_COLUMNS if c in df.columns]


def generate_excel_report(
    df_classified: pd.DataFrame,
    output_path: Optional[Path] = None,
    date: Optional[datetime] = None,
) -> Path:
    """Ecrit le rapport Excel multi-onglets.

    Args:
        df_classified: DataFrame consolide ET classifie (colonne 'segment').
        output_path:   Chemin de sortie. Defaut = data/processed/rapport_BottleNeck_YYYY-MM.xlsx.
        date:          Date utilisee pour le nom auto (defaut = maintenant).

    Returns:
        Le chemin du fichier ecrit.

    Raises:
        ValueError: si la colonne 'segment' est absente du DataFrame
                    (= classify_wines n'a pas ete appele en amont).
    """
    if "segment" not in df_classified.columns:
        raise ValueError(
            "Le DataFrame doit contenir une colonne 'segment'. "
            "Appelez identify_wines.classify_wines() avant."
        )

    output_path = Path(output_path) if output_path else _build_report_path(date)
    # mkdir(parents=True, exist_ok=True) :
    #   - parents=True : cree aussi les dossiers parents si besoin
    #   - exist_ok=True : ne plante pas si le dossier existe deja (idempotence)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ====================================================================
    # ONGLET 1 : CA par produit (le plus consulte)
    # ====================================================================
    ca_par_produit = revenue_per_product(df_classified)

    # ====================================================================
    # ONGLET 2 : CA total (KPI haut niveau)
    # ====================================================================
    # Une seule ligne avec les indicateurs cles + la date de generation.
    # La date est utile pour savoir quand le rapport a ete produit.
    ca_total_value = total_revenue(df_classified)
    ca_total_df = pd.DataFrame({
        "indicateur": ["CA total"],
        "valeur_eur": [round(ca_total_value, 2)],
        "nb_produits": [len(df_classified)],
        "date_generation": [datetime.now().strftime("%Y-%m-%d %H:%M")],
    })

    # ====================================================================
    # ONGLETS 3 et 4 : Premium / Ordinary
    # ====================================================================
    # On enrichit avec la colonne `ca` pour pouvoir trier par CA decroissant.
    df_with_ca = add_revenue_column(df_classified)
    premium, ordinary = split_premium_ordinary(df_with_ca)

    keep_cols = _detail_columns_present(df_with_ca)
    premium = premium[keep_cols].sort_values("ca", ascending=False)
    ordinary = ordinary[keep_cols].sort_values("ca", ascending=False)

    # ====================================================================
    # ECRITURE MULTI-ONGLETS
    # ====================================================================
    # `pd.ExcelWriter` en context manager (`with`) gere proprement la
    # fermeture du fichier meme en cas d'exception.
    # `engine='openpyxl'` est l'engine recommande pour les .xlsx modernes.
    logger.info("Ecriture du rapport Excel : %s", output_path)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        ca_par_produit.to_excel(writer, sheet_name="CA_par_produit", index=False)
        ca_total_df.to_excel(writer, sheet_name="CA_total", index=False)
        premium.to_excel(writer, sheet_name="Vins_premium", index=False)
        ordinary.to_excel(writer, sheet_name="Vins_ordinaires", index=False)

    # Petit log de fin pour confirmer que le fichier a bien ete cree.
    # `// 1024` convertit les octets en kilo-octets (lecture humaine).
    logger.info("Rapport ecrit (%d Ko)", output_path.stat().st_size // 1024)
    return output_path


def export_wines_csv(
    df_classified: pd.DataFrame,
    millesimes_path: Optional[Path] = None,
    ordinaires_path: Optional[Path] = None,
    date: Optional[datetime] = None,
):
    """Exporte 2 CSV separes pour les vins millesimes et ordinaires.

    Format : separateur `;` + encodage `utf-8-sig` (compat Excel FR avec
    accents corrects).

    Returns:
        (chemin_millesimes, chemin_ordinaires) : tuple de Path.

    Raises:
        ValueError: si la colonne 'segment' est absente.
    """
    if "segment" not in df_classified.columns:
        raise ValueError("Le DataFrame doit contenir une colonne 'segment'.")

    # Construction des chemins par defaut si non fournis.
    default_milles, default_ord = _build_csv_paths(date)
    millesimes_path = Path(millesimes_path) if millesimes_path else default_milles
    ordinaires_path = Path(ordinaires_path) if ordinaires_path else default_ord
    millesimes_path.parent.mkdir(parents=True, exist_ok=True)

    # On ajoute la colonne `ca` puis on split par segment, comme pour l'Excel.
    df_with_ca = add_revenue_column(df_classified)
    premium, ordinary = split_premium_ordinary(df_with_ca)

    keep_cols = _detail_columns_present(df_with_ca)
    premium = premium[keep_cols].sort_values("ca", ascending=False)
    ordinary = ordinary[keep_cols].sort_values("ca", ascending=False)

    # to_csv(sep=';', encoding='utf-8-sig') : voir docstring du module
    # pour la justification de ces parametres.
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
    date: Optional[datetime] = None,
) -> dict:
    """Genere les 3 livrables : Excel + 2 CSV.

    C'est la fonction d'entree publique du module : run_pipeline n'a
    qu'a appeler celle-ci pour produire tous les fichiers attendus.

    Returns:
        dict avec les cles 'excel', 'csv_millesimes', 'csv_ordinaires'
        (utile pour logger les chemins ou les retourner a Kestra).
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
