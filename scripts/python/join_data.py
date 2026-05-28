"""Jointure des 3 sources BottleNeck (étape 3 du pipeline).

Schéma des clés :

    ERP.product_id   ──>  LIAISON.product_id
                          LIAISON.id_web   ──>  WEB.sku

LIAISON est la table pivot entre product_id ERP et sku WEB.

On fait LEFT puis INNER (plutôt que INNER+INNER) pour pouvoir compter
les orphelins (cf. report_orphans : combien de produits ERP n'ont pas
de pendant WEB). Info précieuse pour le journal de bord.

Cible : 714 produits consolidés.
"""

import logging

import pandas as pd


logger = logging.getLogger(__name__)


# Colonnes finales conservées. Tout le reste (champs WordPress techniques,
# IDs internes WooCommerce…) est inutile pour le calcul du CA et la
# classification, donc on jette ici.
OUTPUT_COLUMNS = [
    "product_id",
    "id_web",
    "sku",
    "post_title",
    "price",
    "stock_quantity",
    "stock_status",
    "total_sales",
    "post_date",
]


def join_sources(
    erp_clean_df: pd.DataFrame,
    web_clean_df: pd.DataFrame,
    liaison_clean_df: pd.DataFrame,
) -> pd.DataFrame:
    """Double jointure ERP ⟕ LIAISON ⟕ WEB. Cible : 714 lignes."""
    logger.info(
        "Jointure : ERP=%d, WEB=%d, LIAISON=%d",
        len(erp_clean_df), len(web_clean_df), len(liaison_clean_df),
    )

    # Étape 1 : ERP LEFT JOIN LIAISON sur product_id.
    # how='left' = SQL LEFT JOIN : on garde tous les produits ERP, même
    # ceux sans pendant LIAISON (ils auront id_web=NaN).
    erp_liaison_df = erp_clean_df.merge(liaison_clean_df, on="product_id", how="left")
    logger.info("Après ERP+LIAISON (left) : %d lignes", len(erp_liaison_df))

    # Avant la 2e jointure, on homogénéise les types des clés.
    # Piège classique : si id_web est int et sku est str, pandas renvoie
    # 0 ligne SANS warning. On force tout en str + strip pour l'éviter.
    erp_liaison_df["id_web"] = erp_liaison_df["id_web"].astype(str).str.strip()
    web_for_join_df = web_clean_df.copy()  # copy() pour ne pas modifier l'appelant
    web_for_join_df["sku"] = web_for_join_df["sku"].astype(str).str.strip()

    # Étape 2 : (ERP+LIAISON) INNER JOIN WEB sur id_web=sku.
    # how='inner' = on ne garde QUE les lignes avec correspondance des
    # deux côtés. Les NaN d'id_web disparaissent ici.
    # left_on / right_on : les colonnes ont des noms différents.
    consolidated_products_df = erp_liaison_df.merge(
        web_for_join_df,
        left_on="id_web",
        right_on="sku",
        how="inner",
    )
    logger.info("Après + WEB (inner) : %d lignes", len(consolidated_products_df))

    # On ne garde que les colonnes utiles. Le filtre defensif évite un
    # KeyError si une colonne attendue manquait dans la source.
    available_columns = [
        c for c in OUTPUT_COLUMNS if c in consolidated_products_df.columns
    ]
    return consolidated_products_df[available_columns].copy().reset_index(drop=True)


def report_orphans(
    erp_clean_df: pd.DataFrame,
    web_clean_df: pd.DataFrame,
    liaison_clean_df: pd.DataFrame,
) -> dict:
    """Diagnostique les produits orphelins (sans correspondance).

    Returns:
        dict avec :
            erp_sans_id_web      : produits ERP sans id_web en LIAISON
            erp_id_web_orphelins : id_web ERP qui n'existent pas en WEB
            web_sans_pendant_erp : sku WEB qui n'ont aucun pendant ERP

    Sert au journal de bord, à la présentation client, et à détecter
    une dérive future (passage de 5 à 200 orphelins -> alerte).
    """
    # On refait la 1re jointure pour pouvoir compter les NaN d'id_web.
    erp_liaison_df = erp_clean_df.merge(liaison_clean_df, on="product_id", how="left")

    # On compte les id_web "vides" : NaN réels + chaîne 'nan' (issue
    # d'un cast str sur un NaN). On somme les deux pour être robuste.
    nb_sans_id_web = erp_liaison_df["id_web"].isna().sum() + (
        erp_liaison_df["id_web"].astype(str).str.lower() == "nan"
    ).sum()

    # Set arithmetic = équivalent rapide du NOT IN en SQL.
    erp_skus = set(erp_liaison_df["id_web"].astype(str).str.strip().dropna().tolist())
    web_skus = set(web_clean_df["sku"].astype(str).str.strip().tolist())

    # only_erp = id_web connus en ERP mais absents en WEB.
    # On retire 'nan' et '' (pas de vrais sku, juste des artefacts du cast).
    only_in_erp = erp_skus - web_skus - {"nan", ""}
    only_in_web = web_skus - erp_skus

    return {
        "erp_sans_id_web": int(nb_sans_id_web),
        "erp_id_web_orphelins": len(only_in_erp),
        "web_sans_pendant_erp": len(only_in_web),
    }


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from scripts.python.extract_files import read_bottleneck_sources
    from scripts.python.clean_data import clean_erp, clean_web, clean_liaison

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    bottleneck_sources = read_bottleneck_sources()
    erp_clean_df = clean_erp(bottleneck_sources["erp"])
    web_clean_df = clean_web(bottleneck_sources["web"])
    liaison_clean_df = clean_liaison(bottleneck_sources["liaison"])

    consolidated_products_df = join_sources(erp_clean_df, web_clean_df, liaison_clean_df)
    print(f"\nProduits consolidés : {len(consolidated_products_df)} (cible : 714)")
    print(consolidated_products_df.head(3))

    print("\nOrphelins :", report_orphans(erp_clean_df, web_clean_df, liaison_clean_df))
