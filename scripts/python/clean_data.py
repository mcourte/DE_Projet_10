"""Nettoyage des donnees BottleNeck.

----------------------------------------------------------------------------
ROLE DE CE MODULE :
    2e etape du pipeline. On prend les DataFrames bruts d'extract_files
    et on applique les regles metier de Stephane (Data Analyst).

CIBLES VOLUMETRIQUES (validees par Stephane sur le dataset reel) :

    ERP        : pas de nettoyage particulier, juste un dedup sur product_id.
                 Cible : 825 lignes.

    LIAISON    : pas de nettoyage particulier, juste un dedup sur product_id.
                 Les eventuels id_web NaN sont CONSERVES a ce stade : ils
                 seront filtres naturellement par la jointure inner avec WEB
                 dans join_data.py.
                 Cible : 825 lignes.

    WEB        : nettoyage en 2 etapes (logique de Stephane) :
                    1) drop sku NaN          : 1 513 -> 1 428 lignes.
                    2) dedup sur sku, en gardant la ligne post_type='product'
                       si un sku apparait a la fois en 'product' et
                       en 'attachment'       : 1 428 -> 714 lignes.

POURQUOI 2 ETAPES POUR WEB :
    L'export WooCommerce contient les fiches produits (post_type='product')
    ET les images attachees (post_type='attachment'). Les attachments
    "heritent" parfois du sku de leur produit parent. Un dedup naif perdrait
    la fiche produit si l'attachment apparait avant. D'ou le tri par
    `post_type=='product' first` avant le drop_duplicates.

    On expose `count_web_after_cleaning()` pour permettre au pipeline de
    verifier la cible intermediaire 1428 sans relancer toute l'etape 2.
----------------------------------------------------------------------------
"""

import logging

import pandas as pd


logger = logging.getLogger(__name__)


def _strip_strings(df: pd.DataFrame) -> pd.DataFrame:
    """Retire les espaces de debut/fin sur les colonnes texte.

    DETAIL :
        - select_dtypes(include=["object", "string"]) : on cible UNIQUEMENT
          les colonnes texte (les colonnes numeriques restent intactes).
        - astype("string") : on convertit en pandas.StringDtype pour pouvoir
          utiliser .str.strip() / .str.replace() proprement, meme s'il y a
          des NaN dans la colonne.
        - .str.strip()  : retire les espaces de debut et de fin.
        - .str.replace(r"\\s+", " ", regex=True) : remplace toute sequence
          d'espaces multiples (ou tabulations) par un espace unique.

    POURQUOI :
        Les exports Excel contiennent souvent des espaces parasites
        ("  Vin Rouge ", "Vin\\trouge"). Sans normalisation, deux noms qui
        paraissent identiques a l'oeil seraient consideres comme distincts
        par pandas (ex: lors d'un dedup ou d'un merge).
    """
    out = df.copy()
    # `include=["object", "string"]` evite le Pandas4Warning sur 'object' seul
    # (a partir de pandas 4, les types 'string' ne seront plus inclus
    # automatiquement quand on demande 'object').
    text_cols = out.select_dtypes(include=["object", "string"]).columns
    for col in text_cols:
        out[col] = (
            out[col]
            .astype("string")
            .str.strip()
            .str.replace(r"\s+", " ", regex=True)
        )
    return out


# --- ERP --------------------------------------------------------------------


def clean_erp(df: pd.DataFrame) -> pd.DataFrame:
    """Nettoyage du fichier ERP.

    Etapes :
        1) Strip des chaines (espaces parasites).
        2) Conversions numeriques de `price` et `stock_quantity` :
           - to_numeric(errors='coerce') tente de convertir, et met NaN
             pour les valeurs non convertibles (ex: "N/A", " ", "n.c.").
           - On NE fait PAS fillna(0) ici : un prix manquant est une donnee
             metier importante, on prefere garder NaN pour le detecter aval.
        3) drop_duplicates(subset='product_id', keep='first') :
           si un product_id apparait plusieurs fois, on garde la 1re ligne.

    Cible : 825 lignes.
    """
    out = _strip_strings(df)

    # to_numeric(errors='coerce') :
    #   - convertit "10.5" -> 10.5
    #   - convertit "N/A" -> NaN (au lieu de planter avec une exception)
    out["price"] = pd.to_numeric(out["price"], errors="coerce")
    out["stock_quantity"] = pd.to_numeric(out["stock_quantity"], errors="coerce")

    # Dedup avec un log si on en retire (utile pour le journal de bord).
    before = len(out)
    out = out.drop_duplicates(subset="product_id", keep="first")
    if before != len(out):
        logger.warning("ERP : %d doublon(s) product_id retire(s)", before - len(out))

    logger.info("ERP nettoye : %d lignes (cible : 825)", len(out))
    # reset_index(drop=True) : reindex 0..N-1 et abandonne l'ancien index.
    # `drop=True` evite que l'ancien index ne devienne une colonne 'index'.
    return out.reset_index(drop=True)


# --- WEB --------------------------------------------------------------------


def clean_web(df: pd.DataFrame) -> pd.DataFrame:
    """Nettoyage + dedoublonnage du fichier WEB selon la logique de Stephane.

    Voir le docstring du module pour le detail metier.

    Returns:
        DataFrame final (~714 lignes apres les 2 etapes).
    """
    out = _strip_strings(df)

    # ====================================================================
    # ETAPE 1 - NETTOYAGE : on drop les lignes sans sku
    # ====================================================================
    # dropna(subset=['sku']) : retire les lignes ou la colonne sku est NaN.
    # On cible explicitement 'sku' parce qu'on accepte des NaN ailleurs
    # (ex: post_excerpt vide est legitime).
    before = len(out)
    out = out.dropna(subset=["sku"])
    logger.info(
        "WEB nettoyage (drop sku NaN) : %d -> %d lignes (cible : 1428)",
        before, len(out),
    )

    # ====================================================================
    # ETAPE 2 - DEDOUBLONNAGE : dedup sku avec priorite post_type='product'
    # ====================================================================
    # Astuce : on cree une colonne temporaire `_priority` qui vaut 1 pour
    # les lignes 'product' et 0 pour les autres. En triant DECROISSANT sur
    # cette colonne, les 'product' passent devant les 'attachment'.
    # Ensuite drop_duplicates(keep='first') garde la 1re occurrence -> on
    # conserve forcement le 'product' quand il y a le choix.
    out["sku"] = out["sku"].astype(str).str.strip()
    out["_priority"] = (out["post_type"] == "product").astype(int)
    out = (
        out.sort_values("_priority", ascending=False)  # 'product' d'abord
        .drop_duplicates(subset="sku", keep="first")    # 1 ligne par sku
        .drop(columns="_priority")                      # menage : on retire la colonne tempo
    )
    logger.info("WEB dedoublonnage (sku) : %d lignes (cible : 714)", len(out))

    # Conversion numerique pour la suite (calcul du CA = price * total_sales).
    # fillna(0) ici est legitime : un produit sans vente -> 0 vente, pas NaN.
    out["total_sales"] = pd.to_numeric(out["total_sales"], errors="coerce").fillna(0)

    return out.reset_index(drop=True)


def count_web_after_cleaning(df: pd.DataFrame) -> int:
    """Compteur intermediaire WEB apres l'etape 1 uniquement (drop sku NaN).

    Pourquoi cette fonction separee ?
        Pour permettre au pipeline d'afficher le compteur 1428 (cible
        intermediaire de Stephane) sans avoir a relancer tout `clean_web`.
        C'est aussi pratique pour les tests : on peut tester etape 1
        independamment d'etape 2.

    Cible : 1428 lignes.
    """
    return len(df.dropna(subset=["sku"]))


# --- LIAISON ----------------------------------------------------------------


def clean_liaison(df: pd.DataFrame) -> pd.DataFrame:
    """Nettoyage de la table de liaison.

    Logique de Stephane : juste un dedoublonnage sur product_id.

    POINT IMPORTANT : les id_web NaN sont CONSERVES a ce stade.
        Pourquoi ? Parce que la jointure aval avec WEB est un INNER JOIN.
        Les lignes sans id_web seront naturellement filtrees a ce moment-la.
        Si on les droppait ici, on perdrait l'info "X produits ERP n'ont
        pas de pendant Web" (utile pour `report_orphans`).

    Cible : 825 lignes.
    """
    out = _strip_strings(df)

    # Cast id_web en str pour homogeneiser avec la colonne sku de WEB.
    # Important : les NaN deviennent la chaine 'nan' apres astype(str).
    # Cela ne pose pas probleme car la jointure inner les filtrera.
    out["id_web"] = out["id_web"].astype(str).str.strip()

    before = len(out)
    out = out.drop_duplicates(subset="product_id", keep="first")
    if before != len(out):
        logger.warning("LIAISON : %d doublon(s) product_id retire(s)", before - len(out))

    logger.info("LIAISON nettoye : %d lignes (cible : 825)", len(out))
    return out.reset_index(drop=True)


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from scripts.python.extract_files import read_bottleneck_sources

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    src = read_bottleneck_sources()
    erp = clean_erp(src["erp"])
    web = clean_web(src["web"])
    liaison = clean_liaison(src["liaison"])

    print("\n=== Cibles attendues par Stephane ===")
    print(f"ERP          : {len(erp):>5} lignes  (cible : 825)")
    print(f"LIAISON      : {len(liaison):>5} lignes  (cible : 825)")
    print(f"WEB cleaning : {count_web_after_cleaning(src['web']):>5} lignes  (cible : 1428)")
    print(f"WEB dedup    : {len(web):>5} lignes  (cible : 714)")
