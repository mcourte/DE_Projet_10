"""Jointure des 3 sources BottleNeck.

----------------------------------------------------------------------------
ROLE DE CE MODULE :
    3e etape du pipeline. On reunit les 3 DataFrames (ERP, WEB, LIAISON)
    en UNE seule table consolidee, exploitable pour la classification
    des vins et le calcul du CA.

SCHEMA DES CLES :

    ERP.product_id   ------>  LIAISON.product_id
                              LIAISON.id_web   ------>  WEB.sku

    Autrement dit, LIAISON est la table de pivot qui permet de relier
    un product_id ERP a un sku WEB.

STRATEGIE EN 2 ETAPES :

    1. ERP LEFT JOIN LIAISON sur product_id
       -> on conserve TOUS les produits ERP, meme ceux sans correspondance
          web. Ceux-la auront un id_web NaN apres la jointure.

    2. Le resultat INNER JOIN WEB sur id_web=sku
       -> on ne garde que les produits qui ont effectivement un pendant
          web exploitable. Les NaN d'id_web disparaissent ici.

POURQUOI LEFT puis INNER, et pas directement INNER+INNER ?
    Pour pouvoir compter les orphelins (cf. report_orphans).
    Avec INNER+INNER on n'aurait jamais l'info "produit ERP sans pendant
    web". Cette info est precieuse pour le journal de bord.

CIBLE : 714 produits consolides.
----------------------------------------------------------------------------
"""

import logging

import pandas as pd


logger = logging.getLogger(__name__)


# Colonnes finales conservees pour les analyses aval. Tout le reste
# (champs WordPress techniques, IDs internes WooCommerce, ...) est jete
# ici parce qu'inutile pour le calcul du CA et la classification.
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
    erp: pd.DataFrame,
    web_clean: pd.DataFrame,
    liaison: pd.DataFrame,
) -> pd.DataFrame:
    """Realise la double jointure ERP-LIAISON-WEB.

    Args:
        erp:       DataFrame ERP nettoye (cf. clean_data.clean_erp).
        web_clean: DataFrame WEB nettoye (cf. clean_data.clean_web).
        liaison:   DataFrame LIAISON nettoye (cf. clean_data.clean_liaison).

    Returns:
        DataFrame consolide avec uniquement les colonnes OUTPUT_COLUMNS.
    """
    logger.info(
        "Jointure : ERP=%d, WEB=%d, LIAISON=%d",
        len(erp), len(web_clean), len(liaison),
    )

    # ====================================================================
    # ETAPE 1 : ERP LEFT JOIN LIAISON sur product_id
    # ====================================================================
    # `merge` est l'equivalent pandas du JOIN SQL.
    # how='left' = SQL LEFT JOIN : on garde toutes les lignes de la "gauche"
    # (erp), meme celles qui n'ont pas de correspondance dans liaison.
    # Les colonnes manquantes a droite seront a NaN.
    erp_liaison = erp.merge(liaison, on="product_id", how="left")
    logger.info("Apres ERP+LIAISON (left) : %d lignes", len(erp_liaison))

    # ====================================================================
    # PREPARATION : homogeneiser les types des cles avant la 2e jointure
    # ====================================================================
    # Si id_web est int et sku est str (ou inversement), pandas ne fera PAS
    # la jointure (elle renverra 0 lignes sans warning explicite).
    # On force tout en str + strip pour eliminer ce piege.
    erp_liaison["id_web"] = erp_liaison["id_web"].astype(str).str.strip()
    web_clean = web_clean.copy()  # copy() pour ne pas modifier le DataFrame de l'appelant
    web_clean["sku"] = web_clean["sku"].astype(str).str.strip()

    # ====================================================================
    # ETAPE 2 : (ERP+LIAISON) INNER JOIN WEB sur id_web=sku
    # ====================================================================
    # how='inner' = SQL INNER JOIN : on ne garde QUE les lignes qui ont une
    # correspondance des deux cotes. Les ERP sans pendant Web disparaissent.
    # left_on / right_on : les noms de colonnes sont differents (id_web vs sku),
    # on doit donc dire explicitement quelle colonne utiliser de chaque cote.
    full = erp_liaison.merge(
        web_clean,
        left_on="id_web",
        right_on="sku",
        how="inner",
    )
    logger.info("Apres + WEB (inner) : %d lignes", len(full))

    # On ne garde que les colonnes utiles, dans l'ordre attendu.
    # `[c for c in OUTPUT_COLUMNS if c in full.columns]` : on filtre defensivement
    # pour eviter un KeyError si une colonne attendue manquait dans la source.
    available = [c for c in OUTPUT_COLUMNS if c in full.columns]
    out = full[available].copy()

    return out.reset_index(drop=True)


def report_orphans(
    erp: pd.DataFrame,
    web_clean: pd.DataFrame,
    liaison: pd.DataFrame,
) -> dict:
    """Diagnostique les produits 'orphelins' (sans correspondance).

    Renvoie un dict avec :
        - erp_sans_id_web      : nombre de produits ERP sans id_web en LIAISON
        - erp_id_web_orphelins : id_web ERP qui n'existent pas dans WEB
        - web_sans_pendant_erp : sku WEB qui n'ont aucun pendant en ERP

    Utile pour :
        - le journal de bord (combien de produits perdus a chaque etape).
        - la presentation client (justifier les chiffres).
        - detecter une derive (ex: si demain on passe de 5 a 200 orphelins,
          il y a eu un probleme dans l'export).
    """
    # On reprend la 1re jointure pour pouvoir compter les NaN d'id_web.
    erp_liaison = erp.merge(liaison, on="product_id", how="left")

    # On compte les id_web "vides" : NaN reels + chaine "nan" (issue d'un
    # cast str sur un NaN). On somme les deux pour etre robuste.
    sans_id_web = erp_liaison["id_web"].isna().sum() + (
        erp_liaison["id_web"].astype(str).str.lower() == "nan"
    ).sum()

    # Set arithmetic : moyen tres rapide de calculer "presents d'un cote
    # mais pas de l'autre" (equivalent a NOT IN en SQL).
    erp_skus = set(erp_liaison["id_web"].astype(str).str.strip().dropna().tolist())
    web_skus = set(web_clean["sku"].astype(str).str.strip().tolist())

    # only_erp = id_web que l'ERP connait mais que WEB ne connait pas.
    # On retire 'nan' et '' (qui ne sont pas de vrais sku, juste des artefacts).
    only_erp = erp_skus - web_skus - {"nan", ""}
    only_web = web_skus - erp_skus

    return {
        "erp_sans_id_web": int(sans_id_web),
        "erp_id_web_orphelins": len(only_erp),
        "web_sans_pendant_erp": len(only_web),
    }


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from scripts.python.extract_files import read_bottleneck_sources
    from scripts.python.clean_data import clean_erp, clean_web, clean_liaison

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    src = read_bottleneck_sources()
    erp = clean_erp(src["erp"])
    web = clean_web(src["web"])
    liaison = clean_liaison(src["liaison"])

    full = join_sources(erp, web, liaison)
    print(f"\nProduits consolides : {len(full)} (cible : 714)")
    print(full.head(3))

    print("\nOrphelins :", report_orphans(erp, web, liaison))
