"""Nettoyage des données BottleNeck (étape 2 du pipeline).

Règles métier de Stéphane et cibles volumétriques :

    ERP     : dédup sur product_id                  -> 825 lignes
    LIAISON : dédup sur product_id (NaN conservés)  -> 825 lignes
    WEB     : 2 étapes
              1) drop sku NaN                       -> 1 428 lignes
              2) dédup sur sku, priorité 'product'  ->   714 lignes

Pourquoi 2 étapes pour WEB ?
    L'export WooCommerce contient les fiches produits (post_type='product')
    ET les images attachées (post_type='attachment') qui héritent parfois
    du sku de leur produit parent. Un dédup naïf perdrait la fiche produit
    si l'attachment apparaît avant. On trie donc par post_type='product'
    en tête AVANT de dédupliquer.
"""

import logging

import pandas as pd


logger = logging.getLogger(__name__)


def _strip_strings(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Normalise les colonnes texte : strip + espaces multiples -> 1 espace.

    Les exports Excel contiennent souvent des espaces parasites
    ('  Vin Rouge ', 'Vin\\trouge'). Sans normalisation, deux noms
    identiques à l'œil seraient vus comme distincts (dédup, merge).
    """
    stripped_df = raw_df.copy()
    text_columns = stripped_df.select_dtypes(include=["object", "string"]).columns
    for col in text_columns:
        stripped_df[col] = (
            stripped_df[col]
            .astype("string")
            .str.strip()
            .str.replace(r"\s+", " ", regex=True)
        )
    return stripped_df


def _drop_duplicates_with_log(
    input_df: pd.DataFrame, source: str, key: str,
) -> pd.DataFrame:
    """Dédup sur `key` + log si on a effectivement retiré des lignes."""
    rows_before = len(input_df)
    deduplicated_df = input_df.drop_duplicates(subset=key, keep="first")
    if rows_before != len(deduplicated_df):
        logger.warning(
            "%s : %d doublon(s) %s retiré(s)",
            source, rows_before - len(deduplicated_df), key,
        )
    return deduplicated_df


# --- ERP --------------------------------------------------------------------


def clean_erp(erp_raw_df: pd.DataFrame) -> pd.DataFrame:
    """Nettoyage du fichier ERP. Cible : 825 lignes.

    - Strip des chaînes.
    - to_numeric(errors='coerce') sur price et stock_quantity : convertit
      en nombre, met NaN si non convertible (ex: "N/A", "n.c.").
      On NE remplit PAS les NaN par 0 ici : un prix manquant est une info
      métier qu'on veut détecter en aval.
    - Dédup sur product_id.
    """
    erp_clean_df = _strip_strings(erp_raw_df)
    erp_clean_df["price"] = pd.to_numeric(erp_clean_df["price"], errors="coerce")
    erp_clean_df["stock_quantity"] = pd.to_numeric(
        erp_clean_df["stock_quantity"], errors="coerce",
    )
    erp_clean_df = _drop_duplicates_with_log(erp_clean_df, "ERP", "product_id")
    logger.info("ERP nettoyé : %d lignes (cible : 825)", len(erp_clean_df))
    return erp_clean_df.reset_index(drop=True)


# --- WEB --------------------------------------------------------------------


def clean_web(web_raw_df: pd.DataFrame) -> pd.DataFrame:
    """Nettoyage + dédup du fichier WEB (logique de Stéphane).

    Étape 1 : drop sku NaN          -> ~1 428 lignes
    Étape 2 : dédup sku, priorité   -> ~  714 lignes
              post_type='product'

    Retourne le DataFrame final (~714 lignes).
    """
    web_clean_df = _strip_strings(web_raw_df)

    # Étape 1 : on retire les lignes sans sku. On cible explicitement 'sku'
    # parce que des NaN ailleurs sont légitimes (post_excerpt vide, etc.).
    rows_before = len(web_clean_df)
    web_clean_df = web_clean_df.dropna(subset=["sku"])
    logger.info(
        "WEB drop sku NaN : %d -> %d lignes (cible : 1428)",
        rows_before, len(web_clean_df),
    )

    # Étape 2 : dédup en gardant en priorité les lignes post_type='product'.
    # Astuce : on crée une colonne `_priority` (1 pour 'product', 0 sinon),
    # on trie DESC dessus -> les 'product' passent devant -> drop_duplicates
    # avec keep='first' conserve forcément le 'product' s'il existe.
    web_clean_df["sku"] = web_clean_df["sku"].astype(str).str.strip()
    web_clean_df["_priority"] = (web_clean_df["post_type"] == "product").astype(int)
    web_clean_df = (
        web_clean_df.sort_values("_priority", ascending=False)
        .drop_duplicates(subset="sku", keep="first")
        .drop(columns="_priority")
    )
    logger.info("WEB dédup sku : %d lignes (cible : 714)", len(web_clean_df))

    # total_sales numérique pour le calcul du CA aval. fillna(0) légitime
    # ici : un produit sans vente -> 0 vente (pas une absence d'info).
    web_clean_df["total_sales"] = pd.to_numeric(
        web_clean_df["total_sales"], errors="coerce",
    ).fillna(0)

    return web_clean_df.reset_index(drop=True)


def count_web_after_cleaning(web_raw_df: pd.DataFrame) -> int:
    """Compteur intermédiaire WEB après l'étape 1 seule (drop sku NaN).

    Permet au pipeline de contrôler la cible 1428 sans relancer clean_web.
    Cible : 1428 lignes.
    """
    return len(web_raw_df.dropna(subset=["sku"]))


# --- LIAISON ----------------------------------------------------------------


def clean_liaison(liaison_raw_df: pd.DataFrame) -> pd.DataFrame:
    """Nettoyage de la table de liaison. Cible : 825 lignes.

    Point important : les id_web NaN sont CONSERVÉS à ce stade.
    La jointure inner avec WEB les filtrera naturellement, et on garde
    ainsi l'info "X produits ERP n'ont pas de pendant Web" (cf. report_orphans).
    """
    liaison_clean_df = _strip_strings(liaison_raw_df)

    # Cast id_web en str pour homogénéiser avec sku de WEB (les NaN
    # deviennent 'nan' en str — pas un souci, la jointure inner les vire).
    liaison_clean_df["id_web"] = liaison_clean_df["id_web"].astype(str).str.strip()

    liaison_clean_df = _drop_duplicates_with_log(
        liaison_clean_df, "LIAISON", "product_id",
    )
    logger.info("LIAISON nettoyé : %d lignes (cible : 825)", len(liaison_clean_df))
    return liaison_clean_df.reset_index(drop=True)


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from scripts.python.extract_files import read_bottleneck_sources

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    bottleneck_sources = read_bottleneck_sources()
    erp_clean_df = clean_erp(bottleneck_sources["erp"])
    web_clean_df = clean_web(bottleneck_sources["web"])
    liaison_clean_df = clean_liaison(bottleneck_sources["liaison"])

    print("\n=== Cibles attendues par Stéphane ===")
    print(f"ERP          : {len(erp_clean_df):>5} lignes  (cible : 825)")
    print(f"LIAISON      : {len(liaison_clean_df):>5} lignes  (cible : 825)")
    print(
        f"WEB cleaning : "
        f"{count_web_after_cleaning(bottleneck_sources['web']):>5} lignes  (cible : 1428)"
    )
    print(f"WEB dédup    : {len(web_clean_df):>5} lignes  (cible : 714)")
