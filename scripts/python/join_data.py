"""Jointure des 3 sources BottleNeck.

Schema des cles :
    ERP.product_id   -->  LIAISON.product_id
    LIAISON.id_web   -->  WEB.sku

Strategie :
    1. ERP LEFT JOIN LIAISON sur product_id
       (on conserve tous les produits ERP, meme ceux sans correspondance web)
    2. Le resultat INNER JOIN WEB sur id_web=sku
       (on ne garde que les produits qui ont un pendant web exploitable)

Cible : 714 produits consolides.

Le DataFrame de sortie contient :
    product_id, id_web, sku, post_title, price, stock_quantity, stock_status,
    total_sales, post_date
"""

from __future__ import annotations

import logging

import pandas as pd


logger = logging.getLogger(__name__)


# Colonnes finales conservees pour les analyses aval
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
    """Realise la double jointure et retourne la table consolidee.

    Args:
        erp: DataFrame ERP nettoye (cf. clean_data.clean_erp).
        web_clean: DataFrame WEB nettoye (cf. clean_data.clean_web).
        liaison: DataFrame LIAISON nettoye (cf. clean_data.clean_liaison).

    Returns:
        DataFrame consolide avec les colonnes OUTPUT_COLUMNS.
    """
    logger.info(
        "Jointure : ERP=%d, WEB=%d, LIAISON=%d",
        len(erp), len(web_clean), len(liaison),
    )

    # 1. ERP <-> LIAISON
    erp_liaison = erp.merge(liaison, on="product_id", how="left")
    logger.info("Apres ERP+LIAISON (left) : %d lignes", len(erp_liaison))

    # On homogeneise les types de cle pour la 2e jointure
    erp_liaison["id_web"] = erp_liaison["id_web"].astype(str).str.strip()
    web_clean = web_clean.copy()
    web_clean["sku"] = web_clean["sku"].astype(str).str.strip()

    # 2. (ERP+LIAISON) <-> WEB
    full = erp_liaison.merge(
        web_clean,
        left_on="id_web",
        right_on="sku",
        how="inner",
    )
    logger.info("Apres + WEB (inner) : %d lignes", len(full))

    # On garde uniquement les colonnes utiles, dans l'ordre attendu
    available = [c for c in OUTPUT_COLUMNS if c in full.columns]
    out = full[available].copy()

    # Reset index pour eviter les surprises en aval
    return out.reset_index(drop=True)


def report_orphans(
    erp: pd.DataFrame,
    web_clean: pd.DataFrame,
    liaison: pd.DataFrame,
) -> dict[str, int]:
    """Diagnostique les produits 'orphelins' (sans correspondance).

    Utile pour le journal de bord et la presentation.
    """
    erp_liaison = erp.merge(liaison, on="product_id", how="left")

    sans_id_web = erp_liaison["id_web"].isna().sum() + (
        erp_liaison["id_web"].astype(str).str.lower() == "nan"
    ).sum()

    erp_skus = set(
        erp_liaison["id_web"].astype(str).str.strip().dropna().tolist()
    )
    web_skus = set(web_clean["sku"].astype(str).str.strip().tolist())

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
