"""Nettoyage des donnees BottleNeck.

Regles metier alignees sur l'analyse de Stephane (Data Analyst) :

ERP        : pas de nettoyage particulier, juste dedup product_id (cible : 825).
LIAISON    : pas de nettoyage particulier, juste dedup product_id (cible : 825).
             Les eventuels id_web NaN sont conserves a ce stade.
WEB        : nettoyage = drop des lignes ou sku est NaN (1513 -> 1428).
             dedoublonnage = dedup sur sku, en gardant la ligne post_type='product'
             si le sku apparait a la fois en 'product' et en 'attachment' (1428 -> 714).
"""

from __future__ import annotations

import logging
import re

import pandas as pd


logger = logging.getLogger(__name__)


_WHITESPACE_RE = re.compile(r"\s+")


def _strip_strings(df: pd.DataFrame) -> pd.DataFrame:
    """Retire espaces de debut/fin sur les colonnes texte."""
    out = df.copy()
    for col in out.select_dtypes(include="object").columns:
        out[col] = (
            out[col]
            .astype("string")
            .str.strip()
            .str.replace(_WHITESPACE_RE, " ", regex=True)
        )
    return out


# --- ERP --------------------------------------------------------------------


def clean_erp(df: pd.DataFrame) -> pd.DataFrame:
    """Nettoyage du fichier ERP.

    - Strip
    - Conversions numeriques (price, stock_quantity)
    - Dedup product_id (cible : 825 lignes)
    """
    out = _strip_strings(df)
    out["price"] = pd.to_numeric(out["price"], errors="coerce")
    out["stock_quantity"] = pd.to_numeric(out["stock_quantity"], errors="coerce")

    before = len(out)
    out = out.drop_duplicates(subset="product_id", keep="first")
    if before != len(out):
        logger.warning("ERP : %d doublon(s) product_id retire(s)", before - len(out))

    logger.info("ERP nettoye : %d lignes (cible : 825)", len(out))
    return out.reset_index(drop=True)


# --- WEB --------------------------------------------------------------------


def clean_web(df: pd.DataFrame) -> pd.DataFrame:
    """Nettoyage + dedoublonnage du fichier WEB selon la logique de Stephane.

    Etape 1 (nettoyage)     : drop sku NaN. 1513 -> 1428.
    Etape 2 (dedoublonnage) : dedup sur sku, en privilegiant les lignes
                              post_type='product' sur les 'attachment'.
                              1428 -> 714.

    Retourne le DataFrame final (714 lignes).
    Pour le journal de bord, le compteur intermediaire 1428 est loggue.
    """
    out = _strip_strings(df)

    # ETAPE 1 : nettoyage = drop sku NaN
    before = len(out)
    out = out.dropna(subset=["sku"])
    logger.info("WEB nettoyage (drop sku NaN) : %d -> %d lignes (cible : 1428)",
                before, len(out))

    # ETAPE 2 : dedoublonnage = dedup sku avec priorite post_type='product'
    out["sku"] = out["sku"].astype(str).str.strip()
    out["_priority"] = (out["post_type"] == "product").astype(int)
    out = (
        out.sort_values("_priority", ascending=False)
        .drop_duplicates(subset="sku", keep="first")
        .drop(columns="_priority")
    )
    logger.info("WEB dedoublonnage (sku) : %d lignes (cible : 714)", len(out))

    # Conversion numerique utile pour la suite
    out["total_sales"] = pd.to_numeric(out["total_sales"], errors="coerce").fillna(0)

    return out.reset_index(drop=True)


def count_web_after_cleaning(df: pd.DataFrame) -> int:
    """Retourne uniquement le compteur apres nettoyage (drop sku NaN).

    Utile pour les tests intermediaires sans relancer tout le clean_web.
    Cible : 1428 lignes.
    """
    return len(df.dropna(subset=["sku"]))


# --- LIAISON ----------------------------------------------------------------


def clean_liaison(df: pd.DataFrame) -> pd.DataFrame:
    """Nettoyage de la table de liaison.

    Logique de Stephane : juste un dedoublonnage sur product_id.
    Les id_web NaN sont CONSERVES a ce stade — ils seront filtres
    naturellement par la jointure inner avec WEB.

    Cible : 825 lignes.
    """
    out = _strip_strings(df)
    # Cast des id_web en str pour homogeneiser, mais on garde les "nan" textuels
    out["id_web"] = out["id_web"].astype(str).str.strip()

    before = len(out)
    out = out.drop_duplicates(subset="product_id", keep="first")
    if before != len(out):
        logger.warning("LIAISON : %d doublon(s) product_id retire(s)", before - len(out))

    logger.info("LIAISON nettoye : %d lignes (cible : 825)", len(out))
    return out.reset_index(drop=True)


# --- API generique conservee pour retro-compat ------------------------------


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Nettoyage generique : strip + dropna sur lignes entierement vides."""
    out = _strip_strings(df)
    out = out.dropna(how="all")
    return out.reset_index(drop=True)


def deduplicate(df: pd.DataFrame, keys: list[str] | None = None) -> pd.DataFrame:
    """Supprime les doublons sur une liste de cles (ou globalement)."""
    before = len(df)
    if keys:
        valid = [k for k in keys if k in df.columns]
        if not valid:
            logger.warning("Aucune cle valide dans %s, dedup global", keys)
            out = df.drop_duplicates()
        else:
            out = df.drop_duplicates(subset=valid, keep="first")
    else:
        out = df.drop_duplicates()
    out = out.reset_index(drop=True)
    logger.info("Dedoublonnage : %d -> %d", before, len(out))
    return out


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
    print(f"ERP        : {len(erp):>5} lignes  (cible : 825)")
    print(f"LIAISON    : {len(liaison):>5} lignes  (cible : 825)")
    print(f"WEB cleaning : {count_web_after_cleaning(src['web']):>5} lignes  (cible : 1428)")
    print(f"WEB dedup    : {len(web):>5} lignes  (cible : 714)")
