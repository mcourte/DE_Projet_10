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
        f"Jointure : ERP={len(erp_clean_df)}, "
        f"WEB={len(web_clean_df)}, LIAISON={len(liaison_clean_df)}"
    )

    # Étape 1 : ERP LEFT JOIN LIAISON sur product_id.
    # how='left' = SQL LEFT JOIN : on garde tous les produits ERP, même
    # ceux sans pendant LIAISON (ils auront id_web=NaN).
    erp_liaison_df = erp_clean_df.merge(liaison_clean_df, on="product_id", how="left")
    logger.info(f"Après ERP+LIAISON (left) : {len(erp_liaison_df)} lignes")

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
    logger.info(f"Après + WEB (inner) : {len(consolidated_products_df)} lignes")

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
    """Compte les produits orphelins (sans correspondance) pour le journal de bord.

    Renvoie un dict avec 3 compteurs :
        - erp_sans_id_web      : produits ERP qui n'ont pas d'id_web en LIAISON
        - erp_id_web_orphelins : id_web ERP qui n'existent pas dans WEB.sku
        - web_sans_pendant_erp : sku WEB qui n'ont aucun pendant ERP via LIAISON

    Utile pour détecter une dérive (passage de 5 à 200 orphelins -> alerte).
    """
    # Étape 1 : on refait la jointure ERP <- LIAISON pour récupérer l'id_web
    # associé à chaque produit ERP. Les produits ERP sans pendant LIAISON
    # auront id_web vide.
    erp_liaison_df = erp_clean_df.merge(liaison_clean_df, on="product_id", how="left")

    # clean_liaison a converti les NaN en chaîne "nan" (à cause du cast str).
    # On considère qu'un id_web est "vide" si c'est NaN, la chaîne "nan",
    # ou une chaîne vide. On crée un booléen pour repérer ces cas.
    id_web_lower = erp_liaison_df["id_web"].astype(str).str.lower()
    est_vide = id_web_lower.isin(["nan", ""])

    # Compteur 1 : nombre de produits ERP sans id_web.
    erp_sans_id_web = int(est_vide.sum())

    # Étape 2 : on construit 2 ensembles (set) de sku pour pouvoir comparer.
    # Côté ERP : on garde seulement les id_web non vides (~ = NOT en pandas).
    # Côté WEB : tous les sku, convertis en str pour la comparaison.
    erp_ids = set(id_web_lower[~est_vide])
    web_skus = set(web_clean_df["sku"].astype(str))

    # Compteurs 2 et 3 : différence d'ensembles = équivalent du NOT IN en SQL.
    return {
        "erp_sans_id_web": erp_sans_id_web,
        "erp_id_web_orphelins": len(erp_ids - web_skus),  # en ERP, pas en WEB
        "web_sans_pendant_erp": len(web_skus - erp_ids),  # en WEB, pas en ERP
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
