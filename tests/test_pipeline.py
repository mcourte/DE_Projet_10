"""Tests pytest du pipeline BottleNeck.

Lancement :
    python -m pytest tests/ -v

Trois categories de tests, separees par marqueurs pytest :

1. **Tests unitaires** (sans marqueur)
   Testent la logique de chaque fonction sur des fixtures synthetiques.
   Independants des fichiers reels -> rapides, deterministes.

2. **Tests sur chiffres cibles** -- marqueur `@pytest.mark.cibles`
   Lisent les VRAIS fichiers BottleNeck (data/raw/bottleneck/) et verifient
   les chiffres-cles annonces par Stephane :
        - 714 lignes apres jointure
        - 30 vins millesimes (Z-score > 1.96)
        - CA total ~ 70 568,60 EUR
   Auto-skip si les fichiers sont absents (utile en CI).

3. **Tests d'integration DuckDB** -- marqueur `@pytest.mark.integration`
   Verifient les tables apres une execution complete du pipeline.
   Auto-skip si duckdb/bottlerock.db n'existe pas.

Filtrage usuel :
    pytest tests/ -m "not cibles and not integration"   # uniquement unitaires
    pytest tests/ -m cibles                              # chiffres BottleNeck
    pytest tests/ -m integration                         # post-pipeline
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Ajout du dossier racine au sys.path pour pouvoir importer scripts.python.*
# meme quand pytest est lance depuis n'importe ou.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.python import (  # noqa: E402  (import apres modif sys.path)
    calculate_revenue,
    clean_data,
    extract_files,
    generate_reports,
    identify_wines,
    join_data,
    load_to_duckdb,
)


# Repertoires utiles aux tests "cibles" et "integration".
BOTTLENECK_DIR = PROJECT_ROOT / "data" / "raw" / "bottleneck"
DUCKDB_FILE = PROJECT_ROOT / "duckdb" / "bottlerock.db"


# ===========================================================================
# Fixtures synthetiques (donnees minimales pour les tests unitaires)
# ===========================================================================


@pytest.fixture
def fake_erp() -> pd.DataFrame:
    """Mini-ERP de 4 lignes pour tester les fonctions de nettoyage / jointure."""
    return pd.DataFrame({
        "product_id": [1, 2, 3, 4],
        "onsale_web": [1, 1, 1, 0],
        "price": [10.0, 50.0, 200.0, 25.0],
        "stock_quantity": [10, 5, 0, 20],
        "stock_status": ["instock", "instock", "outofstock", "instock"],
    })


@pytest.fixture
def fake_web() -> pd.DataFrame:
    """Mini-WEB avec 5 lignes incluant :
        - une ligne sku=NaN (a droper a l'etape 1).
        - un sku 'A2' en doublon (post_type='product' x2) : on doit garder le 1er.
        - un sku 'A3' en attachment + product : la priorite va au 'product'.
    """
    return pd.DataFrame({
        "sku": ["A1", "A2", "A3", None, "A2"],
        "post_title": ["Vin 1", "Vin 2", "Vin 3", "Image", "Vin 2 dup"],
        "post_type": ["product", "product", "product", "attachment", "product"],
        "post_status": ["publish", "publish", "publish", "publish", "publish"],
        "total_sales": [10.0, 5.0, 2.0, 0.0, 100.0],
        "post_date": pd.to_datetime([
            "2020-01-01", "2020-02-01", "2020-03-01",
            "2020-04-01", "2020-05-01",
        ]),
    })


@pytest.fixture
def fake_liaison() -> pd.DataFrame:
    """Mini-LIAISON : product_id 1->A1, 2->A2, 3->A3, et 4 sans id_web (NaN)."""
    return pd.DataFrame({
        "product_id": [1, 2, 3, 4],
        "id_web": ["A1", "A2", "A3", None],
    })


# ===========================================================================
# 1. Tests unitaires
# ===========================================================================


class TestExtractFiles:
    """Tests de scripts.python.extract_files."""

    def test_list_source_files(self, tmp_path: Path) -> None:
        # On cree 3 fichiers dans un dossier temporaire :
        # un .csv, un .xlsx, et un fichier cache (.hidden).
        # Seuls les 2 premiers doivent apparaitre dans la liste.
        (tmp_path / "a.csv").write_text("x,y\n1,2", encoding="utf-8")
        (tmp_path / "b.xlsx").write_bytes(b"")
        (tmp_path / ".hidden").write_text("nope", encoding="utf-8")

        files = extract_files.list_source_files(tmp_path)
        names = {f.name for f in files}

        assert "a.csv" in names
        assert "b.xlsx" in names
        assert ".hidden" not in names

    def test_read_csv(self, tmp_path: Path) -> None:
        # Un CSV simple doit etre lu avec ses 2 colonnes 'a' et 'b'.
        path = tmp_path / "x.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")

        df = extract_files.read_file(path)
        assert list(df.columns) == ["a", "b"]

    def test_read_unknown_extension(self, tmp_path: Path) -> None:
        # Un fichier .json n'est pas dans SUPPORTED_EXTENSIONS -> ValueError.
        path = tmp_path / "x.json"
        path.write_text("{}", encoding="utf-8")

        with pytest.raises(ValueError):
            extract_files.read_file(path)

    def test_read_bottleneck_missing(self, tmp_path: Path) -> None:
        # Dossier vide -> aucun des 3 fichiers attendus -> FileNotFoundError.
        with pytest.raises(FileNotFoundError):
            extract_files.read_bottleneck_sources(tmp_path)


class TestCleanData:
    """Tests de scripts.python.clean_data."""

    def test_clean_erp_dedup(self, fake_erp: pd.DataFrame) -> None:
        # On injecte un doublon en concatenant la 1re ligne a la fin.
        # clean_erp doit le retirer -> 4 product_id uniques.
        df = pd.concat([fake_erp, fake_erp.head(1)], ignore_index=True)

        out = clean_data.clean_erp(df)

        assert out["product_id"].is_unique
        assert len(out) == 4

    def test_clean_web_drops_sku_nan(self, fake_web: pd.DataFrame) -> None:
        # Etape 1 du nettoyage WEB : drop des lignes sku=NaN.
        # Sur 5 lignes brutes dont 1 NaN, il doit en rester 4.
        n = clean_data.count_web_after_cleaning(fake_web)
        assert n == 4

    def test_clean_web_dedup_priorise_product(self, fake_web: pd.DataFrame) -> None:
        # Etape 2 : tous les sku doivent etre uniques apres dedup.
        out = clean_data.clean_web(fake_web)

        assert out["sku"].is_unique
        # Tous les sku 'product' connus du fake_web doivent etre presents.
        for sku in ["A1", "A2", "A3"]:
            assert sku in out["sku"].tolist()

    def test_clean_web_dedup_keeps_first_for_same_post_type(
        self, fake_web: pd.DataFrame
    ) -> None:
        # Quand 2 lignes ont le meme sku ET le meme post_type='product',
        # drop_duplicates(keep='first') garde la 1re. Ici 'A2' apparait
        # 2 fois en 'product' : on doit garder "Vin 2" (total_sales=5),
        # pas "Vin 2 dup" (total_sales=100).
        out = clean_data.clean_web(fake_web)

        a2 = out[out["sku"] == "A2"].iloc[0]
        assert a2["post_title"] == "Vin 2"
        assert a2["total_sales"] == 5.0

    def test_clean_liaison_no_drop_nan(self, fake_liaison: pd.DataFrame) -> None:
        # Stephane CONSERVE les lignes id_web=NaN apres dedup
        # (elles seront filtrees plus tard par l'inner join WEB).
        # 4 product_id distincts en entree -> 4 en sortie.
        out = clean_data.clean_liaison(fake_liaison)
        assert len(out) == 4


class TestJoinData:
    """Tests de scripts.python.join_data."""

    def test_join_inner_filters_orphans(
        self,
        fake_erp: pd.DataFrame,
        fake_web: pd.DataFrame,
        fake_liaison: pd.DataFrame,
    ) -> None:
        # Le produit 4 n'a pas d'id_web -> il sera filtre par l'inner join.
        # Les produits 1, 2, 3 sont relies a A1, A2, A3 -> 3 lignes finales.
        erp = clean_data.clean_erp(fake_erp)
        web = clean_data.clean_web(fake_web)
        liaison = clean_data.clean_liaison(fake_liaison)

        out = join_data.join_sources(erp, web, liaison)

        assert len(out) == 3
        assert set(out["sku"]) == {"A1", "A2", "A3"}

    def test_report_orphans(
        self,
        fake_erp: pd.DataFrame,
        fake_web: pd.DataFrame,
        fake_liaison: pd.DataFrame,
    ) -> None:
        # Le rapport doit exposer au moins ces 2 cles.
        erp = clean_data.clean_erp(fake_erp)
        web = clean_data.clean_web(fake_web)
        liaison = clean_data.clean_liaison(fake_liaison)

        report = join_data.report_orphans(erp, web, liaison)

        assert "erp_sans_id_web" in report
        assert "web_sans_pendant_erp" in report


class TestIdentifyWines:
    """Tests de scripts.python.identify_wines."""

    def test_iqr_thresholds(self) -> None:
        # IQR = Q3 - Q1, donc Q1 < Q3 et upper > Q3 par construction.
        prices = pd.Series([10, 20, 30, 40, 50, 1000])
        t = identify_wines.compute_iqr_thresholds(prices)

        assert t.q1 < t.q3
        assert t.upper > t.q3

    def test_zscore_thresholds(self) -> None:
        # Verification de la formule : upper == mean + threshold * std.
        prices = pd.Series([10, 20, 30, 40, 50, 1000])
        z = identify_wines.compute_zscore_thresholds(prices, threshold=1.96)

        assert z.upper == z.mean + 1.96 * z.std

    def test_classify_zscore_isole_outlier(self) -> None:
        # 100 valeurs a 10 + 1 outlier a 10 000 : le Z-score doit isoler
        # exactement 1 produit comme 'premium' (l'outlier extreme).
        df = pd.DataFrame({"price": [10] * 100 + [10_000]})

        out = identify_wines.classify_wines(df, method="zscore")

        assert (out["segment"] == "premium").sum() == 1
        assert out.iloc[-1]["segment"] == "premium"

    def test_classify_iqr_method(self) -> None:
        # La methode IQR doit aussi detecter au moins l'outlier 1000.
        df = pd.DataFrame({"price": [10, 20, 30, 40, 50, 1000]})

        out = identify_wines.classify_wines(df, method="iqr")

        assert (out["segment"] == "premium").sum() >= 1

    def test_classify_invalid_method(self) -> None:
        # Une methode inconnue doit lever ValueError.
        with pytest.raises(ValueError):
            identify_wines.classify_wines(
                pd.DataFrame({"price": [1, 2, 3]}), method="bogus"
            )

    def test_classify_missing_price_column(self) -> None:
        # Pas de colonne 'price' -> ValueError.
        with pytest.raises(ValueError):
            identify_wines.classify_wines(pd.DataFrame({"x": [1]}))

    def test_split_premium_ordinary(self) -> None:
        # Split correct : 1 ligne dans chaque sous-DataFrame.
        df = pd.DataFrame({
            "price": [10, 1000],
            "segment": ["ordinary", "premium"],
        })

        premium, ordinary = identify_wines.split_premium_ordinary(df)

        assert len(premium) == 1 and premium.iloc[0]["price"] == 1000
        assert len(ordinary) == 1


class TestCalculateRevenue:
    """Tests de scripts.python.calculate_revenue."""

    def test_total_revenue(self) -> None:
        # CA = 10*3 + 20*5 = 30 + 100 = 130.
        df = pd.DataFrame({"price": [10, 20], "total_sales": [3, 5]})
        assert calculate_revenue.total_revenue(df) == 30 + 100

    def test_revenue_per_product_sorted(self) -> None:
        # Le produit B (CA=200) doit apparaitre avant A (CA=10).
        df = pd.DataFrame({
            "sku": ["A", "B"],
            "post_title": ["x", "y"],
            "price": [10, 100],
            "total_sales": [1, 2],
        })

        out = calculate_revenue.revenue_per_product(df)

        assert out.iloc[0]["sku"] == "B"

    def test_revenue_summary_segments(self) -> None:
        # On doit retrouver les 2 segments + un total des parts == 100%.
        df = pd.DataFrame({
            "price": [10, 100],
            "total_sales": [1, 2],
            "segment": ["ordinary", "premium"],
        })

        out = calculate_revenue.revenue_summary(df)

        assert set(out["segment"]) == {"ordinary", "premium"}
        assert abs(out["part_pct"].sum() - 100.0) < 0.01


class TestLoadToDuckDB:
    """Tests de scripts.python.load_to_duckdb (sans serveur externe :
    on travaille en base ':memory:' pour rester ephemere)."""

    def test_get_connection_in_memory(self) -> None:
        # Une connexion in-memory doit savoir executer un simple SELECT 1.
        conn = load_to_duckdb.get_connection(":memory:")
        try:
            assert conn.execute("SELECT 1").fetchone()[0] == 1
        finally:
            conn.close()

    def test_write_and_query_in_memory(self) -> None:
        # Round-trip : write_table puis query renvoie 3 lignes.
        df = pd.DataFrame({"a": [1, 2, 3]})
        conn = load_to_duckdb.get_connection(":memory:")
        try:
            load_to_duckdb.write_table(df, "t", "replace", conn=conn)
            out = load_to_duckdb.query("SELECT COUNT(*) AS n FROM t", conn=conn)
            assert out.iloc[0]["n"] == 3
        finally:
            conn.close()

    def test_write_table_invalid_mode(self) -> None:
        # Mode 'bogus' n'est ni 'replace' ni 'append' -> ValueError immediat.
        with pytest.raises(ValueError):
            load_to_duckdb.write_table(
                pd.DataFrame({"a": [1]}), "t", mode="bogus"
            )

    def test_fallback_writes_csv_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tolerance aux pannes : si DuckDB est KO, un CSV de secours est ecrit.

        On simule la panne en monkeypatchant `_write_table_inner` pour qu'il
        leve directement DuckDBUnavailable (court-circuite la boucle de retry).
        On redirige aussi FALLBACK_DIR vers un dossier temporaire pour que
        le CSV ecrit ne pollue pas le projet.
        """
        def fail(*args, **kwargs):
            raise load_to_duckdb.DuckDBUnavailable("DuckDB simule KO")

        monkeypatch.setattr(load_to_duckdb, "_write_table_inner", fail)
        monkeypatch.setattr(load_to_duckdb, "FALLBACK_DIR", tmp_path)

        # write_table doit re-lever DuckDBUnavailable (signal pour l'appelant)
        # MAIS le CSV doit avoir ete ecrit AVANT.
        with pytest.raises(load_to_duckdb.DuckDBUnavailable):
            load_to_duckdb.write_table(pd.DataFrame({"a": [1]}), "demo")

        assert (tmp_path / "demo.csv").exists()


class TestGenerateReports:
    """Tests de scripts.python.generate_reports."""

    def test_report_has_expected_sheets(self, tmp_path: Path) -> None:
        # On verifie que le fichier Excel produit contient bien les 4 onglets
        # imposes par l'enonce du livrable.
        from openpyxl import load_workbook  # import local : evite de payer le cout au boot

        df = pd.DataFrame({
            "sku": ["A", "B", "C"],
            "post_title": ["x", "y", "z"],
            "price": [10, 100, 200],
            "stock_quantity": [1, 2, 3],
            "stock_status": ["instock"] * 3,
            "total_sales": [1, 2, 3],
            "post_date": pd.to_datetime(["2020-01-01"] * 3),
            "segment": ["ordinary", "ordinary", "premium"],
        })

        out = generate_reports.generate_excel_report(
            df, output_path=tmp_path / "r.xlsx"
        )

        wb = load_workbook(out, read_only=True)
        assert set(wb.sheetnames) == {
            "CA_par_produit",
            "CA_total",
            "Vins_premium",
            "Vins_ordinaires",
        }

    def test_report_missing_segment_column(self, tmp_path: Path) -> None:
        # Sans colonne 'segment', on ne peut pas decouper -> ValueError.
        df = pd.DataFrame({"sku": ["A"], "price": [10], "total_sales": [1]})

        with pytest.raises(ValueError):
            generate_reports.generate_excel_report(
                df, output_path=tmp_path / "r.xlsx"
            )


# ===========================================================================
# 2. Tests sur les chiffres cibles BottleNeck (donnees reelles)
# ===========================================================================


@pytest.fixture
def real_sources():
    """Charge les 3 fichiers BottleNeck reels.

    Auto-skip si le dossier ou les fichiers n'existent pas (pratique en CI
    ou sur la machine d'un autre etudiant qui n'a pas encore decompresse
    le dataset).
    """
    if not BOTTLENECK_DIR.exists() or not list(BOTTLENECK_DIR.glob("*.xlsx")):
        pytest.skip("Fichiers BottleNeck absents")
    return extract_files.read_bottleneck_sources(BOTTLENECK_DIR)


@pytest.mark.cibles
class TestChiffresBottleNeck:
    """Verifie les chiffres EXACTS annonces par Stephane sur le dataset reel.

    Cibles :
        - dedup ERP        = 825 lignes
        - dedup LIAISON    = 825 lignes
        - nettoyage WEB    = 1 428 lignes (drop sku NaN)
        - dedup WEB        = 714 lignes
        - fusion           = 714 lignes
        - vins millesimes  = 30   (Z-score > 1.96)
        - CA total         = 70 568,60 EUR
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
        # Etape 1 isolee : drop sku NaN seulement.
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

        # Tolerance +/- 1 EUR pour absorber les arrondis float.
        assert abs(ca - 70_568.60) < 1.0, f"Attendu 70 568.60, recu {ca:.2f}"


# ===========================================================================
# 3. Tests d'integration sur DuckDB (apres run pipeline)
# ===========================================================================


@pytest.fixture
def duckdb_conn():
    """Ouvre une connexion sur la base post-pipeline.

    Auto-skip si la base n'existe pas (il faut avoir lance run_pipeline.py
    au moins une fois pour qu'elle soit creee).
    """
    if not DUCKDB_FILE.exists():
        pytest.skip("duckdb/bottlerock.db absent : executer run_pipeline.py")

    conn = load_to_duckdb.get_connection(DUCKDB_FILE)
    try:
        yield conn
    finally:
        conn.close()


@pytest.mark.integration
class TestDuckDBIntegration:
    """Tests post-pipeline : on interroge DuckDB et on valide les invariants."""

    def test_table_produits_consolides_existe(self, duckdb_conn) -> None:
        # La table doit exister et contenir 714 produits.
        n = duckdb_conn.execute(
            "SELECT COUNT(*) FROM produits_consolides"
        ).fetchone()[0]
        assert n == 714

    def test_ca_premium_plus_ordinary_egal_total(self, duckdb_conn) -> None:
        # Test de coherence : la somme des CA par segment doit egaler le total.
        # COALESCE pour proteger des cas ou un segment serait vide (renvoie 0).
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
        # Apres nettoyage : aucune ligne ne doit avoir un price/sku/product_id NULL.
        n = duckdb_conn.execute("""
            SELECT COUNT(*) FROM produits_consolides
            WHERE price IS NULL OR sku IS NULL OR product_id IS NULL
        """).fetchone()[0]

        assert n == 0

    def test_references_uniques(self, duckdb_conn) -> None:
        # Tous les sku doivent etre distincts apres dedup (proxy : 'references').
        n = duckdb_conn.execute(
            "SELECT COUNT(DISTINCT sku) FROM produits_consolides"
        ).fetchone()[0]

        assert n == 714
