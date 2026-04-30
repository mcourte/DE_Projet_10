"""Orchestrateur local du pipeline BottleNeck.

Permet de lancer la chaine complete sans Kestra (pratique pour debugger).

Usage :
    python -m scripts.python.run_pipeline

Etapes :
    1. Extraction des 3 sources Excel
    2. Nettoyage (ERP, WEB, LIAISON) avec test de volumetrie
    3. Jointure avec test de volumetrie
    4. Classification premium/ordinary avec test de coherence
    5. Calcul du CA avec test de plage
    6. Persistance DuckDB (tolerance aux pannes -> fallback CSV)
    7. Generation du rapport Excel

Chaque etape de transformation est suivie d'une 'tache de test' qui valide
le resultat avant de poursuivre, conformement a l'architecture cible.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

# Permet de lancer le module en standalone
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.python.calculate_revenue import revenue_summary, total_revenue  # noqa: E402
from scripts.python.clean_data import clean_erp, clean_liaison, clean_web  # noqa: E402
from scripts.python.extract_files import read_bottleneck_sources  # noqa: E402
from scripts.python.generate_reports import generate_all_reports  # noqa: E402
from scripts.python.identify_wines import classify_wines, split_premium_ordinary  # noqa: E402
from scripts.python.join_data import join_sources  # noqa: E402
from scripts.python.load_to_duckdb import (  # noqa: E402
    DuckDBUnavailable,
    get_connection,
    write_table,
)


logger = logging.getLogger(__name__)


# --- Taches de tests intermediaires -----------------------------------------


class PipelineTestFailed(AssertionError):
    """Erreur levee quand un test intermediaire echoue."""


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise PipelineTestFailed(message)


def test_erp_volumetrie(df) -> None:
    """Cible Stephane : 825 lignes apres dedoublonnage."""
    _assert(len(df) == 825, f"ERP attendu 825 lignes, obtenu {len(df)}")
    logger.info("[TEST] ERP OK (%d lignes)", len(df))


def test_liaison_volumetrie(df) -> None:
    """Cible Stephane : 825 lignes apres dedoublonnage."""
    _assert(len(df) == 825, f"LIAISON attendu 825 lignes, obtenu {len(df)}")
    logger.info("[TEST] LIAISON OK (%d lignes)", len(df))


def test_web_apres_nettoyage(n_apres_nettoyage: int) -> None:
    """Cible Stephane : 1428 lignes apres drop sku NaN."""
    _assert(
        n_apres_nettoyage == 1428,
        f"WEB nettoye attendu 1428 lignes, obtenu {n_apres_nettoyage}",
    )
    logger.info("[TEST] WEB nettoye OK (%d lignes)", n_apres_nettoyage)


def test_web_apres_dedup(df) -> None:
    """Cible Stephane : 714 lignes apres dedoublonnage sku."""
    _assert(len(df) == 714, f"WEB dedup attendu 714 lignes, obtenu {len(df)}")
    logger.info("[TEST] WEB dedup OK (%d lignes)", len(df))


def test_volumetrie_jointure(df) -> None:
    """Cible Stephane : 714 lignes apres fusion."""
    _assert(len(df) == 714, f"Fusion attendue 714 lignes, obtenu {len(df)}")
    logger.info("[TEST] Fusion OK (%d lignes)", len(df))


def test_classification_coherente(df) -> None:
    """Cible Stephane : 30 vins millesimes (Z-score > 1.96)."""
    counts = df["segment"].value_counts()
    n_premium = int(counts.get("premium", 0))
    n_ordinary = int(counts.get("ordinary", 0))
    _assert(
        n_premium == 30,
        f"Vins millesimes : attendu 30, obtenu {n_premium}",
    )
    _assert(
        n_premium + n_ordinary == len(df),
        f"Somme des segments != total ({n_premium}+{n_ordinary}!={len(df)})",
    )
    logger.info(
        "[TEST] Classification OK (%d millesimes, %d ordinaires)",
        n_premium, n_ordinary,
    )


def test_ca_total(df) -> None:
    """Cible Stephane : 70 568.60 EUR (tolerance +/- 1 EUR pour les arrondis)."""
    ca = total_revenue(df)
    _assert(
        abs(ca - 70_568.60) < 1.0,
        f"CA total attendu 70 568.60, obtenu {ca:.2f}",
    )
    logger.info("[TEST] CA total OK (%.2f EUR)", ca)


# --- Pipeline ---------------------------------------------------------------


def run() -> dict:
    """Execute le pipeline complet et retourne un resume."""
    started_at = datetime.now()
    logger.info("=" * 70)
    logger.info("PIPELINE BOTTLENECK - %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 70)

    # 1. Extraction
    logger.info("\n[1/6] Extraction des sources")
    sources = read_bottleneck_sources()

    # 2. Nettoyage + tests (chaque source contrôlée individuellement)
    logger.info("\n[2/6] Nettoyage + tests")
    erp = clean_erp(sources["erp"])
    test_erp_volumetrie(erp)

    liaison = clean_liaison(sources["liaison"])
    test_liaison_volumetrie(liaison)

    # WEB : on capte le compteur intermediaire (apres nettoyage = drop sku NaN)
    n_web_apres_nettoyage = sources["web"].dropna(subset=["sku"]).shape[0]
    test_web_apres_nettoyage(n_web_apres_nettoyage)
    web = clean_web(sources["web"])
    test_web_apres_dedup(web)

    # 3. Jointure + test
    logger.info("\n[3/6] Jointure + test")
    full = join_sources(erp, web, liaison)
    test_volumetrie_jointure(full)

    # 4. Classification + test
    logger.info("\n[4/6] Classification millesimes vs ordinaires + test")
    classified = classify_wines(full)  # Z-score 1.96 par defaut
    test_classification_coherente(classified)

    # 5. Calcul CA + test
    logger.info("\n[5/6] Calcul du CA + test")
    test_ca_total(classified)
    ca_total = total_revenue(classified)
    summary = revenue_summary(classified)
    logger.info("Resume CA :\n%s", summary.to_string(index=False))

    # 6. Persistance DuckDB (avec fallback) + Rapport Excel
    logger.info("\n[6/6] Persistance DuckDB + rapport Excel")
    duckdb_ok = True
    try:
        with get_connection() as conn:
            write_table(erp, "erp_clean", conn=conn)
            write_table(web, "web_clean", conn=conn)
            write_table(liaison, "liaison_clean", conn=conn)
            write_table(classified, "produits_consolides", conn=conn)
    except DuckDBUnavailable as exc:
        duckdb_ok = False
        logger.error("DuckDB KO -> fallback CSV deja ecrit. %s", exc)

    paths = generate_all_reports(classified)

    elapsed = (datetime.now() - started_at).total_seconds()
    logger.info("\n%s", "=" * 70)
    logger.info("Pipeline OK en %.1fs", elapsed)
    logger.info("Rapport Excel       : %s", paths["excel"])
    logger.info("CSV vins millesimes : %s", paths["csv_millesimes"])
    logger.info("CSV vins ordinaires : %s", paths["csv_ordinaires"])
    logger.info("DuckDB persiste     : %s", "oui" if duckdb_ok else "non (fallback CSV)")
    logger.info("=" * 70)

    return {
        "ok": True,
        "duration_s": elapsed,
        "ca_total": ca_total,
        "nb_produits": len(classified),
        "nb_premium": int((classified["segment"] == "premium").sum()),
        "nb_ordinary": int((classified["segment"] == "ordinary").sum()),
        "duckdb_persisted": duckdb_ok,
        "excel_path": str(paths["excel"]),
        "csv_millesimes_path": str(paths["csv_millesimes"]),
        "csv_ordinaires_path": str(paths["csv_ordinaires"]),
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    result = run()
    print("\n--- RESUME ---")
    for k, v in result.items():
        print(f"  {k:18s} : {v}")
