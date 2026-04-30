"""Tests pytest pour le pipeline BottleNeck.

Lancement :
    python -m pytest tests/ -v

Trois categories de tests :

1. **Tests unitaires** (fixtures synthetiques) : verifient la logique des
   fonctions sans dependance aux fichiers reels.

2. **Tests de chiffres cibles** : marques @pytest.mark.cibles.
   Lisent les VRAIS fichiers BottleNeck (data/raw/bottleneck/) et verifient
   les chiffres cles : 714 lignes apres jointure, ~32 premium, ~70 568 EUR de CA.
   Auto-skip si les fichiers sont absents.

3. **Tests d'integration DuckDB** : marques @pytest.mark.integration.
   Verifient les tables apres execution complete du pipeline.
   Auto-skip si duckdb/bottlerock.db n'existe pas.

Filtrage :
    pytest tests/ -m "not cibles and not integration"   # uniquement unitaires
    pytest tests/ -m cibles                              # chiffres BottleNeck
    pytest tests/ -m integration                         # post-pipeline
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Permet d'importer scripts.python.*
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.python import (  # noqa: E402
    calculate_revenue,
    clean_data,
    extract_files,
    generate_reports,
    identify_wines,
    join_data,
    load_to_duckdb,
)


BOTTLENECK_DIR = PROJECT_ROOT / "data" / "raw" / "bottleneck"
DUCKDB_FILE = PROJECT_ROOT / "duckdb" / "bottlerock.db"


# ===========================================================================
# Fixtures synthetiques
# ===========================================================================


@pytest.fixture
def fake_erp() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "product_id": [1, 2, 3, 4],
            "onsale_web": [1, 1, 1, 0],
            "price": [10.0, 50.0, 200.0, 25.0],
            "stock_quantity": [10, 5, 0, 20],
            "stock_status": ["instock", "instock", "outofstock", "instock"],
        }
    )


@pytest.fixture
def fake_web() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sku": ["A1", "A2", "A3", None, "A2"],  # ligne sku NaN + doublon A2
            "post_title": ["Vin 1", "Vin 2", "Vin 3", "Image", "Vin 2 dup"],
            "post_type": ["product", "product", "product", "attachment", "product"],
            "post_status": ["publish", "publish", "publish", "publish", "publish"],
            "total_sales": [10.0, 5.0, 2.0, 0.0, 100.0],
            "post_date": pd.to_datetime(
                ["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01", "2020-05-01"]
            ),
        }
    )


@pytest.fixture
def fake_liaison() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "product_id": [1, 2, 3, 4],
            "id_web": ["A1", "A2", "A3", None],
        }
    )


# ===========================================================================
# 1. Tests unitaires
# ===========================================================================


class TestExtractFiles:
    def test_list_source_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.csv").write_text("x,y\n1,2", encoding="utf-8")
        (tmp_path / "b.xlsx").write_bytes(b"")
        (tmp_path / ".hidden").write_text("nope", encoding="utf-8")
        files = extract_files.list_source_files(tmp_path)
        names = {f.name for f in files}
        assert "a.csv" in names
        assert "b.xlsx" in names
        assert ".hidden" not in names

    def test_read_csv(self, tmp_path: Path) -> None:
        path = tmp_path / "x.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        df = extract_files.read_file(path)
        assert list(df.columns) == ["a", "b"]

    def test_read_unknown_extension(self, tmp_path: Path) -> None:
        path = tmp_path / "x.json"
        path.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError):
            extract_files.read_file(path)

    def test_read_bottleneck_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            extract_files.read_bottleneck_sources(tmp_path)


class TestCleanData:
    def test_clean_erp_dedup(self, fake_erp: pd.DataFrame) -> None:
        # injection d'un doublon
        df = pd.concat([fake_erp, fake_erp.head(1)], ignore_index=True)
        out = clean_data.clean_erp(df)
        assert out["product_id"].is_unique
        assert len(out) == 4

    def test_clean_web_drops_sku_nan(self, fake_web: pd.DataFrame) -> None:
        # Etape 1 : on drop la ligne sku NaN (4 lignes brutes valides + 1 NaN)
        n = clean_data.count_web_after_cleaning(fake_web)
        assert n == 4  # 5 lignes - 1 NaN

    def test_clean_web_dedup_priorise_product(self, fake_web: pd.DataFrame) -> None:
        out = clean_data.clean_web(fake_web)
        # 4 SKU uniques (A1, A2, A3 sont 'product', l'attachment a un sku distinct ou none)
        # Le doublon A2 (un 'product' + un dup 'product') -> on garde le 1er
        assert out["sku"].is_unique
        # Tous les enregistrements gardes doivent etre 'product' s'il y a le choix
        for sku in ["A1", "A2", "A3"]:
            assert sku in out["sku"].tolist()

    def test_clean_web_dedup_keeps_first_for_same_post_type(
        self, fake_web: pd.DataFrame
    ) -> None:
        out = clean_data.clean_web(fake_web)
        # Le 1er A2 est garde (Vin 2, total_sales=5), pas le 2e (Vin 2 dup, 100)
        # Les deux sont 'product', donc keep='first' s'applique
        a2 = out[out["sku"] == "A2"].iloc[0]
        assert a2["post_title"] == "Vin 2"
        assert a2["total_sales"] == 5.0

    def test_clean_liaison_no_drop_nan(self, fake_liaison: pd.DataFrame) -> None:
        """Stephane conserve les lignes avec id_web NaN apres dedup."""
        out = clean_data.clean_liaison(fake_liaison)
        # 4 lignes en entree, toutes des product_id distincts -> 4 en sortie
        assert len(out) == 4


class TestJoinData:
    def test_join_inner_filters_orphans(
        self, fake_erp: pd.DataFrame, fake_web: pd.DataFrame, fake_liaison: pd.DataFrame
    ) -> None:
        erp = clean_data.clean_erp(fake_erp)
        web = clean_data.clean_web(fake_web)
        liaison = clean_data.clean_liaison(fake_liaison)
        out = join_data.join_sources(erp, web, liaison)
        # produit 4 n'a pas d'id_web -> exclu
        # produits 1,2,3 -> joints avec A1, A2, A3
        assert len(out) == 3
        assert set(out["sku"]) == {"A1", "A2", "A3"}

    def test_report_orphans(
        self, fake_erp: pd.DataFrame, fake_web: pd.DataFrame, fake_liaison: pd.DataFrame
    ) -> None:
        erp = clean_data.clean_erp(fake_erp)
        web = clean_data.clean_web(fake_web)
        liaison = clean_data.clean_liaison(fake_liaison)
        report = join_data.report_orphans(erp, web, liaison)
        assert "erp_sans_id_web" in report
        assert "web_sans_pendant_erp" in report


class TestIdentifyWines:
    def test_iqr_thresholds(self) -> None:
        prices = pd.Series([10, 20, 30, 40, 50, 1000])
        t = identify_wines.compute_iqr_thresholds(prices)
        assert t.q1 < t.q3
        assert t.upper > t.q3

    def test_zscore_thresholds(self) -> None:
        prices = pd.Series([10, 20, 30, 40, 50, 1000])
        z = identify_wines.compute_zscore_thresholds(prices, threshold=1.96)
        assert z.upper == z.mean + 1.96 * z.std

    def test_classify_zscore_isole_outlier(self) -> None:
        # Plus le ratio outlier/dataset est extreme, plus le Z-score isole
        df = pd.DataFrame({"price": [10] * 100 + [10_000]})
        out = identify_wines.classify_wines(df, method="zscore")
        assert (out["segment"] == "premium").sum() == 1
        assert out.iloc[-1]["segment"] == "premium"

    def test_classify_iqr_method(self) -> None:
        df = pd.DataFrame({"price": [10, 20, 30, 40, 50, 1000]})
        out = identify_wines.classify_wines(df, method="iqr")
        assert (out["segment"] == "premium").sum() >= 1

    def test_classify_invalid_method(self) -> None:
        with pytest.raises(ValueError):
            identify_wines.classify_wines(
                pd.DataFrame({"price": [1, 2, 3]}), method="bogus"
            )

    def test_classify_missing_price_column(self) -> None:
        with pytest.raises(ValueError):
            identify_wines.classify_wines(pd.DataFrame({"x": [1]}))

    def test_split_premium_ordinary(self) -> None:
        df = pd.DataFrame(
            {"price": [10, 1000], "segment": ["ordinary", "premium"]}
        )
        premium, ordinary = identify_wines.split_premium_ordinary(df)
        assert len(premium) == 1 and premium.iloc[0]["price"] == 1000
        assert len(ordinary) == 1


class TestCalculateRevenue:
    def test_total_revenue(self) -> None:
        df = pd.DataFrame({"price": [10, 20], "total_sales": [3, 5]})
        assert calculate_revenue.total_revenue(df) == 30 + 100

    def test_revenue_per_product_sorted(self) -> None:
        df = pd.DataFrame(
            {
                "sku": ["A", "B"],
                "post_title": ["x", "y"],
                "price": [10, 100],
                "total_sales": [1, 2],
            }
        )
        out = calculate_revenue.revenue_per_product(df)
        # B doit etre 1er (CA = 200) avant A (CA = 10)
        assert out.iloc[0]["sku"] == "B"

    def test_revenue_summary_segments(self) -> None:
        df = pd.DataFrame(
            {
                "price": [10, 100],
                "total_sales": [1, 2],
                "segment": ["ordinary", "premium"],
            }
        )
        out = calculate_revenue.revenue_summary(df)
        assert set(out["segment"]) == {"ordinary", "premium"}
        assert abs(out["part_pct"].sum() - 100.0) < 0.01


class TestLoadToDuckDB:
    def test_get_connection_in_memory(self) -> None:
        conn = load_to_duckdb.get_connection(":memory:")
        assert conn.execute("SELECT 1").fetchone()[0] == 1
        conn.close()

    def test_write_and_query_in_memory(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        conn = load_to_duckdb.get_connection(":memory:")
        load_to_duckdb.write_table(df, "t", "replace", conn=conn)
        out = load_to_duckdb.query("SELECT COUNT(*) AS n FROM t", conn=conn)
        assert out.iloc[0]["n"] == 3
        conn.close()

    def test_write_table_invalid_mode(self) -> None:
        with pytest.raises(ValueError):
            load_to_duckdb.write_table(pd.DataFrame({"a": [1]}), "t", mode="bogus")

    def test_fallback_writes_csv_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simule une indisponibilite DuckDB -> fallback CSV ecrit.

        On simule la panne en faisant lever DuckDBUnavailable directement
        par _write_table_inner (deja monkeypatche en bypassant le decorateur
        de retry). Cela permet de tester le bloc de fallback du write_table
        externe sans dependre des retries reels.
        """
        def fail(*args, **kwargs):
            raise load_to_duckdb.DuckDBUnavailable("DuckDB simule KO")

        monkeypatch.setattr(load_to_duckdb, "_write_table_inner", fail)
        monkeypatch.setattr(load_to_duckdb, "FALLBACK_DIR", tmp_path)

        with pytest.raises(load_to_duckdb.DuckDBUnavailable):
            load_to_duckdb.write_table(pd.DataFrame({"a": [1]}), "demo")

        assert (tmp_path / "demo.csv").exists()


class TestGenerateReports:
    def test_report_has_expected_sheets(self, tmp_path: Path) -> None:
        from openpyxl import load_workbook

        df = pd.DataFrame(
            {
                "sku": ["A", "B", "C"],
                "post_title": ["x", "y", "z"],
                "price": [10, 100, 200],
                "stock_quantity": [1, 2, 3],
                "stock_status": ["instock"] * 3,
                "total_sales": [1, 2, 3],
                "post_date": pd.to_datetime(["2020-01-01"] * 3),
                "segment": ["ordinary", "ordinary", "premium"],
            }
        )
        out = generate_reports.generate_excel_report(df, output_path=tmp_path / "r.xlsx")
        wb = load_workbook(out, read_only=True)
        assert set(wb.sheetnames) == {
            "CA_par_produit",
            "CA_total",
            "Vins_premium",
            "Vins_ordinaires",
        }

    def test_report_missing_segment_column(self, tmp_path: Path) -> None:
        df = pd.DataFrame({"sku": ["A"], "price": [10], "total_sales": [1]})
        with pytest.raises(ValueError):
            generate_reports.generate_excel_report(df, output_path=tmp_path / "r.xlsx")


# ===========================================================================
# 2. Tests sur les chiffres cibles BottleNeck (donnees reelles)
# ===========================================================================


@pytest.fixture
def real_sources():
    if not BOTTLENECK_DIR.exists() or not list(BOTTLENECK_DIR.glob("*.xlsx")):
        pytest.skip("Fichiers BottleNeck absents")
    return extract_files.read_bottleneck_sources(BOTTLENECK_DIR)


@pytest.mark.cibles
class TestChiffresBottleNeck:
    """Verifie les chiffres EXACTS annonces par Stephane sur le dataset reel.

    Cibles :
        - dedup ERP        = 825 lignes
        - dedup LIAISON    = 825 lignes
        - nettoyage WEB    = 1428 lignes (drop sku NaN)
        - dedup WEB        = 714 lignes
        - fusion           = 714 lignes
        - vins millesimes  = 30  (Z-score > 1.96)
        - CA total         = 70 568.60 EUR
    """

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
        # Etape 1 : drop sku NaN seulement
        n = clean_data.count_web_after_cleaning(real_sources["web"])
        assert n == 1428, f"Attendu 1428, recu {n}"

    def test_dedup_web_donne_714_lignes(self, real_sources) -> None:
        web = clean_data.clean_web(real_sources["web"])
        assert len(web) == 714, f"Attendu 714, recu {len(web)}"

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
            method="zscore",
        )
        n_premium = (full["segment"] == "premium").sum()
        assert n_premium == 30, f"Attendu 30 vins millesimes, recu {n_premium}"

    def test_ca_total_egale_70568_60(self, real_sources) -> None:
        erp = clean_data.clean_erp(real_sources["erp"])
        web = clean_data.clean_web(real_sources["web"])
        liaison = clean_data.clean_liaison(real_sources["liaison"])
        full = join_data.join_sources(erp, web, liaison)
        ca = calculate_revenue.total_revenue(full)
        assert abs(ca - 70_568.60) < 1.0, f"Attendu 70 568.60, recu {ca:.2f}"


# ===========================================================================
# 3. Tests d'integration sur DuckDB (apres run pipeline)
# ===========================================================================


@pytest.fixture
def duckdb_conn():
    if not DUCKDB_FILE.exists():
        pytest.skip("duckdb/bottlerock.db absent : executer run_pipeline.py")
    conn = load_to_duckdb.get_connection(DUCKDB_FILE)
    yield conn
    conn.close()


@pytest.mark.integration
class TestDuckDBIntegration:
    """Tests post-pipeline qui interrogent DuckDB."""

    def test_table_produits_consolides_existe(self, duckdb_conn) -> None:
        n = duckdb_conn.execute(
            "SELECT COUNT(*) FROM produits_consolides"
        ).fetchone()[0]
        assert n == 714

    def test_ca_premium_plus_ordinary_egal_total(self, duckdb_conn) -> None:
        sql = """
            SELECT
                COALESCE(SUM(CASE WHEN segment='premium'  THEN price*total_sales END), 0) AS ca_p,
                COALESCE(SUM(CASE WHEN segment='ordinary' THEN price*total_sales END), 0) AS ca_o,
                COALESCE(SUM(price*total_sales), 0) AS ca_t
            FROM produits_consolides
        """
        row = duckdb_conn.execute(sql).fetchone()
        ca_p, ca_o, ca_t = float(row[0]), float(row[1]), float(row[2])
        assert abs((ca_p + ca_o) - ca_t) < 0.01

    def test_completude_aucun_null_critique(self, duckdb_conn) -> None:
        n = duckdb_conn.execute(
            """
            SELECT COUNT(*) FROM produits_consolides
            WHERE price IS NULL OR sku IS NULL OR product_id IS NULL
            """
        ).fetchone()[0]
        assert n == 0

    def test_references_uniques(self, duckdb_conn) -> None:
        # Nombre de skus distincts (proxy pour 'references')
        n = duckdb_conn.execute(
            "SELECT COUNT(DISTINCT sku) FROM produits_consolides"
        ).fetchone()[0]
        assert n == 714  # tous distincts apres dedup
