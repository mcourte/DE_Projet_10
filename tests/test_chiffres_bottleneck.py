"""Tests des chiffres EXACTS de la POC BottleNeck (validés par Stéphane).

⚠️ Ces tests vérifient des valeurs hardcodées qui ne sont vraies QUE sur
le dataset de démonstration initial (data/raw/bottleneck/). Le mois
suivant, les chiffres réels seront différents et ces tests ÉCHOUERONT —
c'est volontaire : on documente ainsi la POC initiale.

Pour les tests qui doivent passer chaque mois (invariants structurels,
indépendants des valeurs), voir : tests/test_pipeline.py.

Lancement :
    python -m pytest tests/ -m cibles                  # ces tests seuls
    python -m pytest tests/ -m "not cibles"            # tout SAUF ceux-ci

Auto-skip si le dossier data/raw/bottleneck/ est absent ou vide
(utile en CI ou sur la machine d'un autre étudiant).

Chiffres de référence :
    extraction ERP brute   = 825 lignes
    extraction WEB brute   = 1 513 lignes
    extraction LIAISON     = 825 lignes
    dédup ERP              = 825 lignes
    dédup LIAISON          = 825 lignes
    nettoyage WEB (drop NaN) = 1 428 lignes
    dédup WEB              =   714 lignes
    fusion ERP+LIAISON+WEB =   714 lignes
    vins millésimés (Z>1,96) =  30
    vins ordinaires        =   684
    CA total               =  70 568,60 EUR
"""

import sys
from pathlib import Path

import pytest

# Racine du projet dans sys.path.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.python import (  # noqa: E402
    calculate_revenue,
    clean_data,
    extract_files,
    identify_wines,
    join_data,
    load_to_duckdb,
)


BOTTLENECK_DIR = PROJECT_ROOT / "data" / "raw" / "bottleneck"
DUCKDB_FILE = PROJECT_ROOT / "duckdb" / "bottlerock.db"


# ===========================================================================
# Fixtures : lecture du dataset réel (auto-skip si absent)
# ===========================================================================


@pytest.fixture
def real_sources():
    """Charge les 3 fichiers BottleNeck réels.

    Auto-skip si les fichiers sont absents (pratique en CI ou sur la
    machine d'un autre étudiant qui n'a pas encore décompressé le dataset).
    """
    if not BOTTLENECK_DIR.exists() or not list(BOTTLENECK_DIR.glob("*.xlsx")):
        pytest.skip("Fichiers BottleNeck absents (data/raw/bottleneck/)")
    return extract_files.read_bottleneck_sources(BOTTLENECK_DIR)


# ===========================================================================
# 1. Cibles directement sur les fichiers source (sans DuckDB)
# ===========================================================================


@pytest.mark.cibles
class TestChiffresBottleNeck:
    """Vérifie les chiffres EXACTS de Stéphane sur le dataset initial."""

    def test_extraction_volumetrie(self, real_sources) -> None:
        assert len(real_sources["erp"]) == 825
        assert len(real_sources["web"]) == 1513
        assert len(real_sources["liaison"]) == 825

    def test_dedup_erp_donne_825_lignes(self, real_sources) -> None:
        erp = clean_data.clean_erp(real_sources["erp"])
        assert len(erp) == 825

    def test_dedup_liaison_donne_825_lignes(self, real_sources) -> None:
        liaison = clean_data.clean_liaison(real_sources["liaison"])
        assert len(liaison) == 825

    def test_nettoyage_web_donne_1428_lignes(self, real_sources) -> None:
        # Étape 1 isolée : drop sku NaN seulement (avant le dédup).
        n = len(real_sources["web"].dropna(subset=["sku"]))
        assert n == 1428, f"Attendu 1428, reçu {n}"

    def test_dedup_web_donne_714_lignes(self, real_sources) -> None:
        web = clean_data.clean_web(real_sources["web"])
        assert len(web) == 714, f"Attendu 714, reçu {len(web)}"

    def test_fusion_donne_714_lignes(self, real_sources) -> None:
        erp = clean_data.clean_erp(real_sources["erp"])
        web = clean_data.clean_web(real_sources["web"])
        liaison = clean_data.clean_liaison(real_sources["liaison"])

        full = join_data.join_sources(erp, web, liaison)

        assert len(full) == 714

    def test_30_vins_millesimes(self, real_sources) -> None:
        erp = clean_data.clean_erp(real_sources["erp"])
        web = clean_data.clean_web(real_sources["web"])
        liaison = clean_data.clean_liaison(real_sources["liaison"])

        full = identify_wines.classify_wines(
            join_data.join_sources(erp, web, liaison),
        )

        n_premium = (full["segment"] == "premium").sum()
        assert n_premium == 30, f"Attendu 30 vins millésimés, reçu {n_premium}"

    def test_ca_total_egale_70568_60(self, real_sources) -> None:
        erp = clean_data.clean_erp(real_sources["erp"])
        web = clean_data.clean_web(real_sources["web"])
        liaison = clean_data.clean_liaison(real_sources["liaison"])

        full = join_data.join_sources(erp, web, liaison)
        ca = calculate_revenue.total_revenue(full)

        # Tolérance ±1 EUR pour absorber les arrondis float.
        assert abs(ca - 70_568.60) < 1.0, f"Attendu 70 568,60, reçu {ca:.2f}"


# ===========================================================================
# 2. Cibles dans DuckDB (après run_pipeline.py)
# ===========================================================================


@pytest.fixture
def duckdb_conn():
    """Connexion à la base post-pipeline (auto-skip si absente)."""
    if not DUCKDB_FILE.exists():
        pytest.skip("duckdb/bottlerock.db absent : exécuter run_pipeline.py")

    conn = load_to_duckdb.get_connection(DUCKDB_FILE)
    try:
        yield conn
    finally:
        conn.close()


@pytest.mark.cibles
@pytest.mark.integration
class TestChiffresDansDuckDB:
    """Mêmes cibles, mais vérifiées sur la base DuckDB post-pipeline."""

    def test_table_produits_consolides_contient_714_lignes(self, duckdb_conn) -> None:
        n = duckdb_conn.execute(
            "SELECT COUNT(*) FROM produits_consolides"
        ).fetchone()[0]
        assert n == 714, f"Attendu 714 produits, reçu {n}"

    def test_30_vins_premium_dans_duckdb(self, duckdb_conn) -> None:
        n = duckdb_conn.execute(
            "SELECT COUNT(*) FROM produits_consolides WHERE segment = 'premium'"
        ).fetchone()[0]
        assert n == 30, f"Attendu 30 vins premium, reçu {n}"

    def test_ca_total_dans_duckdb(self, duckdb_conn) -> None:
        ca = duckdb_conn.execute(
            "SELECT SUM(price * total_sales) FROM produits_consolides"
        ).fetchone()[0]
        assert abs(float(ca) - 70_568.60) < 1.0, f"Attendu 70 568,60, reçu {ca:.2f}"
