"""Orchestrateur local du pipeline BottleNeck.

----------------------------------------------------------------------------
ROLE DE CE MODULE :
    Permet de lancer la chaine COMPLETE du pipeline sans Kestra. Pratique
    pour :
        - debugger localement (on voit les erreurs Python directement).
        - relancer un run a la main (le mentor qui ouvre le projet).
        - servir de "specification executable" : si on lit ce fichier de
          haut en bas, on comprend exactement ce que fait le pipeline.

USAGE :
    python -m scripts.python.run_pipeline

ETAPES DU PIPELINE :
    1. Extraction des 3 sources Excel.
    2. Nettoyage (ERP, WEB, LIAISON) avec test de volumetrie.
    3. Jointure ERP-LIAISON-WEB avec test de volumetrie.
    4. Classification millesimes/ordinaires avec test de coherence.
    5. Calcul du CA avec test de plage.
    6. Persistance DuckDB (avec fallback CSV) + rapport Excel.

PHILOSOPHIE "TEST APRES CHAQUE TRANSFORMATION" :
    Conformement a l'architecture cible du livrable, chaque etape de
    transformation est suivie d'une 'tache de test' qui valide le
    resultat AVANT de poursuivre. Si un test echoue, le pipeline
    s'arrete net (AssertionError) -> on conserve l'etat du run
    precedent intact, et on alerte plutot que de produire un rapport
    silencieusement faux.

    Les memes tests sont re-joues par Kestra dans le workflow YAML, et
    par pytest dans tests/test_pipeline.py.
----------------------------------------------------------------------------
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

# Permet de lancer le module en standalone (`python -m scripts.python.run_pipeline`).
# Sans cette ligne, Python ne saurait pas trouver `scripts.python.*` quand
# le module est lance directement et non importe.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# `# noqa: E402` desactive le warning "import not at top of file" pour ces lignes.
# C'est volontaire : on doit modifier sys.path AVANT d'importer scripts.python.*.
from scripts.python.calculate_revenue import revenue_summary, total_revenue  # noqa: E402
from scripts.python.clean_data import clean_erp, clean_liaison, clean_web  # noqa: E402
from scripts.python.extract_files import read_bottleneck_sources  # noqa: E402
from scripts.python.generate_reports import generate_all_reports  # noqa: E402
from scripts.python.identify_wines import classify_wines  # noqa: E402
from scripts.python.join_data import join_sources  # noqa: E402
from scripts.python.load_to_duckdb import (  # noqa: E402
    DuckDBUnavailable,
    get_connection,
    write_table,
)


logger = logging.getLogger(__name__)


# --- Helper test ------------------------------------------------------------


def _check(condition: bool, message: str) -> None:
    """Leve AssertionError si la condition est fausse.

    Pourquoi pas un simple `assert` ?
        L'option `python -O` (mode optimise) DESACTIVE les `assert` natifs.
        Les tests "metier" du pipeline ne doivent JAMAIS etre ignores,
        meme en prod. Ce wrapper garantit qu'ils s'executent toujours.
    """
    if not condition:
        raise AssertionError(message)


# --- Taches de tests intermediaires -----------------------------------------
# Chaque test verifie UNE cible chiffree de Stephane apres une etape.
# Si l'un d'eux echoue, le pipeline s'arrete et on n'ecrit rien dans DuckDB
# ni dans le rapport Excel : on conserve l'etat du run precedent intact.


def test_erp_volumetrie(df) -> None:
    """Cible Stephane : 825 lignes apres dedoublonnage."""
    _check(len(df) == 825, f"ERP attendu 825 lignes, obtenu {len(df)}")
    logger.info("[TEST] ERP OK (%d lignes)", len(df))


def test_liaison_volumetrie(df) -> None:
    """Cible Stephane : 825 lignes apres dedoublonnage."""
    _check(len(df) == 825, f"LIAISON attendu 825 lignes, obtenu {len(df)}")
    logger.info("[TEST] LIAISON OK (%d lignes)", len(df))


def test_web_apres_nettoyage(n_apres_nettoyage: int) -> None:
    """Cible Stephane : 1428 lignes apres drop sku NaN.

    On recoit le compteur deja calcule (pas le DataFrame) parce qu'on
    veut tester l'etape 1 isolement, sans relancer l'etape 2.
    """
    _check(
        n_apres_nettoyage == 1428,
        f"WEB nettoye attendu 1428 lignes, obtenu {n_apres_nettoyage}",
    )
    logger.info("[TEST] WEB nettoye OK (%d lignes)", n_apres_nettoyage)


def test_web_apres_dedup(df) -> None:
    """Cible Stephane : 714 lignes apres dedoublonnage sku."""
    _check(len(df) == 714, f"WEB dedup attendu 714 lignes, obtenu {len(df)}")
    logger.info("[TEST] WEB dedup OK (%d lignes)", len(df))


def test_volumetrie_jointure(df) -> None:
    """Cible Stephane : 714 lignes apres fusion ERP-LIAISON-WEB."""
    _check(len(df) == 714, f"Fusion attendue 714 lignes, obtenu {len(df)}")
    logger.info("[TEST] Fusion OK (%d lignes)", len(df))


def test_classification_coherente(df) -> None:
    """Cible Stephane : 30 vins millesimes (Z-score > 1.96).

    Double verification :
        1) Le nombre de premium == 30.
        2) La somme premium + ordinary == total (= invariant de classification :
           chaque produit doit etre dans EXACTEMENT un segment).
    """
    counts = df["segment"].value_counts()
    n_premium = int(counts.get("premium", 0))
    n_ordinary = int(counts.get("ordinary", 0))
    _check(
        n_premium == 30,
        f"Vins millesimes : attendu 30, obtenu {n_premium}",
    )
    _check(
        n_premium + n_ordinary == len(df),
        f"Somme des segments != total ({n_premium}+{n_ordinary}!={len(df)})",
    )
    logger.info(
        "[TEST] Classification OK (%d millesimes, %d ordinaires)",
        n_premium, n_ordinary,
    )


def test_ca_total(df) -> None:
    """Cible Stephane : 70 568,60 EUR.

    Tolerance +/- 1 EUR pour absorber les arrondis float de pandas
    (les sommes de millions de floats peuvent diverger de quelques
    centimes selon l'ordre d'addition).
    """
    ca = total_revenue(df)
    _check(
        abs(ca - 70_568.60) < 1.0,
        f"CA total attendu 70 568.60, obtenu {ca:.2f}",
    )
    logger.info("[TEST] CA total OK (%.2f EUR)", ca)


# --- Pipeline ---------------------------------------------------------------


def run() -> dict:
    """Execute le pipeline complet et retourne un resume.

    C'est la fonction principale du module. Elle peut etre :
        - appelee directement par le bloc __main__ ci-dessous.
        - importee par un autre script (Kestra, notebook, autre).
        - testee unitairement (cf. tests/test_pipeline.py).

    Returns:
        dict avec les indicateurs cles du run (CA, volumetries, chemins
        des livrables, etat de DuckDB). Utile pour Kestra qui peut le
        serializer en JSON dans la sortie de la tache.
    """
    started_at = datetime.now()
    logger.info("=" * 70)
    logger.info("PIPELINE BOTTLENECK - %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 70)

    # ====================================================================
    # 1. Extraction
    # ====================================================================
    logger.info("\n[1/6] Extraction des sources")
    sources = read_bottleneck_sources()

    # ====================================================================
    # 2. Nettoyage + tests (chaque source controlee individuellement)
    # ====================================================================
    logger.info("\n[2/6] Nettoyage + tests")
    erp = clean_erp(sources["erp"])
    test_erp_volumetrie(erp)

    liaison = clean_liaison(sources["liaison"])
    test_liaison_volumetrie(liaison)

    # WEB : on capte le compteur intermediaire APRES etape 1 (drop sku NaN)
    # pour pouvoir tester la cible 1428 sans relancer toute clean_web.
    n_web_apres_nettoyage = sources["web"].dropna(subset=["sku"]).shape[0]
    test_web_apres_nettoyage(n_web_apres_nettoyage)

    # Puis on enchaine avec etape 2 (dedup) qui elle nous donne 714 lignes.
    web = clean_web(sources["web"])
    test_web_apres_dedup(web)

    # ====================================================================
    # 3. Jointure + test
    # ====================================================================
    logger.info("\n[3/6] Jointure + test")
    full = join_sources(erp, web, liaison)
    test_volumetrie_jointure(full)

    # ====================================================================
    # 4. Classification + test
    # ====================================================================
    logger.info("\n[4/6] Classification millesimes vs ordinaires + test")
    classified = classify_wines(full)  # Z-score 1.96 par defaut (cible Stephane)
    test_classification_coherente(classified)

    # ====================================================================
    # 5. Calcul CA + test
    # ====================================================================
    logger.info("\n[5/6] Calcul du CA + test")
    test_ca_total(classified)
    ca_total = total_revenue(classified)
    summary = revenue_summary(classified)
    logger.info("Resume CA :\n%s", summary.to_string(index=False))

    # ====================================================================
    # 6. Persistance DuckDB + Rapport Excel
    # ====================================================================
    # On commence par DuckDB (la persistance "long terme"). Si elle echoue,
    # write_table() ecrit deja un CSV de secours et leve DuckDBUnavailable.
    # On catch ici pour CONTINUER quand meme avec le rapport Excel : meme
    # sans DuckDB, Stephane recevra son rapport mensuel.
    logger.info("\n[6/6] Persistance DuckDB + rapport Excel")
    duckdb_ok = True
    try:
        # `with` garantit que la connexion sera fermee meme si une
        # exception est levee dans le bloc.
        with get_connection() as conn:
            write_table(erp, "erp_clean", conn=conn)
            write_table(web, "web_clean", conn=conn)
            write_table(liaison, "liaison_clean", conn=conn)
            write_table(classified, "produits_consolides", conn=conn)
    except DuckDBUnavailable as exc:
        # Le fallback CSV a deja ete ecrit par write_table().
        # On loggue le souci mais on poursuit avec le rapport Excel.
        duckdb_ok = False
        logger.error("DuckDB KO -> fallback CSV deja ecrit. %s", exc)

    # Rapport Excel + 2 CSV : on le fait toujours, meme si DuckDB a plante.
    # C'est le livrable principal pour Stephane et Laurent.
    paths = generate_all_reports(classified)

    # ====================================================================
    # Resume final
    # ====================================================================
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
    # Configuration logging :
    #   - niveau INFO : on voit toutes les etapes (DEBUG serait trop verbeux).
    #   - format avec timestamp : utile pour mesurer la duree de chaque etape.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    result = run()
    print("\n--- RESUME ---")
    for k, v in result.items():
        print(f"  {k:18s} : {v}")
