"""Orchestrateur local du pipeline BottleNeck.

Lance la chaîne complète sans Kestra (pratique pour debug, démo, ou
test manuel). Usage :

    python -m scripts.python.run_pipeline

Pipeline = 6 étapes : extraction → nettoyage → jointure → classification
→ CA → persistance (DuckDB + Excel). Après chaque transformation, un
contrôle vérifie une cible chiffrée. Si un contrôle échoue, le pipeline
s'arrête immédiatement pour ne PAS écrire un rapport silencieusement faux
(on conserve l'état du run précédent intact).
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

# On ajoute la racine du projet à sys.path pour pouvoir importer
# scripts.python.* quand on lance le fichier en standalone.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# noqa: E402 = "import not at top of file". C'est volontaire :
# il FAUT modifier sys.path avant d'importer scripts.python.*.
from scripts.python.calculate_revenue import revenue_summary, total_revenue  # noqa: E402
from scripts.python.clean_data import clean_erp, clean_liaison, clean_web  # noqa: E402
from scripts.python.extract_files import read_bottleneck_sources  # noqa: E402
from scripts.python.generate_reports import generate_all_reports  # noqa: E402
from scripts.python.identify_wines import classify_wines  # noqa: E402
from scripts.python.join_data import join_sources  # noqa: E402
from scripts.python.load_to_duckdb import DuckDBUnavailable, get_connection, write_table  # noqa: E402


logger = logging.getLogger(__name__)


def _check(condition: bool, message: str) -> None:
    """Lève AssertionError si la condition est fausse.

    On n'utilise pas `assert` directement parce qu'il est désactivé par
    `python -O` (mode optimisé) : les contrôles métier doivent TOUJOURS
    s'exécuter, même en prod.
    """
    if not condition:
        raise AssertionError(message)


def run() -> dict:
    """Lance le pipeline complet et renvoie un résumé (lu par Kestra)."""
    started_at = datetime.now()
    logger.info("=" * 70)
    logger.info("PIPELINE BOTTLENECK - %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 70)

    # --- 1. Extraction ------------------------------------------------------
    logger.info("[1/6] Extraction des sources")
    sources = read_bottleneck_sources()

    # --- 2. Nettoyage + contrôles STRUCTURELS -------------------------------
    # Les contrôles ci-dessous testent des INVARIANTS (pas de doublons, pas
    # de table vide, etc.) — ils restent valides quel que soit le mois.
    # Les chiffres POC initiaux validés par Stéphane (825 / 1428 / 714) sont
    # vérifiés séparément dans tests/test_chiffres_bottleneck.py.
    logger.info("[2/6] Nettoyage + contrôles structurels")
    erp = clean_erp(sources["erp"])
    _check(
        len(erp) > 0 and erp["product_id"].is_unique,
        f"ERP invalide : {len(erp)} lignes ou doublons product_id",
    )

    liaison = clean_liaison(sources["liaison"])
    _check(
        len(liaison) > 0 and liaison["product_id"].is_unique,
        f"LIAISON invalide : {len(liaison)} lignes ou doublons product_id",
    )

    # WEB : on vérifie que le nettoyage a bien filtré quelque chose (drop NaN)
    # ET qu'on a au moins 1 ligne après dédup, sans doublon de sku.
    n_web_brut = len(sources["web"])
    n_web_intermediaire = sources["web"].dropna(subset=["sku"]).shape[0]
    _check(
        n_web_intermediaire < n_web_brut,
        f"WEB drop sku NaN inefficace : {n_web_brut} -> {n_web_intermediaire}",
    )
    web = clean_web(sources["web"])
    _check(
        len(web) > 0 and web["sku"].is_unique,
        f"WEB dédup invalide : {len(web)} lignes ou doublons sku",
    )
    logger.info("ERP=%d, LIAISON=%d, WEB=%d", len(erp), len(liaison), len(web))

    # --- 3. Jointure + contrôle structurel ---------------------------------
    logger.info("[3/6] Jointure ERP ⟕ LIAISON ⟕ WEB")
    full = join_sources(erp, web, liaison)
    # Invariants : la fusion (inner join) ne peut pas créer plus de lignes
    # que la source la plus petite, et chaque produit y est unique par sku.
    _check(
        len(full) > 0 and len(full) <= min(len(erp), len(web), len(liaison)),
        f"Fusion suspecte : {len(full)} (max attendu {min(len(erp), len(web), len(liaison))})",
    )
    _check(full["sku"].is_unique, "Fusion : doublons sku détectés")

    # --- 4. Classification + contrôles structurels --------------------------
    logger.info("[4/6] Classification millésimés vs ordinaires (Z-score > 1.96)")
    classified = classify_wines(full)
    counts = classified["segment"].value_counts()
    n_premium = int(counts.get("premium", 0))
    n_ordinary = int(counts.get("ordinary", 0))
    # Invariants : chaque produit est dans exactement 1 segment + les 2
    # segments sont non vides (sinon la méthode Z-score est cassée).
    _check(
        n_premium + n_ordinary == len(classified),
        f"Somme des segments != total ({n_premium}+{n_ordinary}!={len(classified)})",
    )
    _check(
        n_premium > 0 and n_ordinary > 0,
        f"Classification dégénérée : {n_premium} premium / {n_ordinary} ordinary",
    )
    # Invariant méthode Z-score : la moyenne des prix premium > moyenne ordinary.
    mean_premium = classified.loc[classified["segment"] == "premium", "price"].mean()
    mean_ordinary = classified.loc[classified["segment"] == "ordinary", "price"].mean()
    _check(
        mean_premium > mean_ordinary,
        f"Prix moyen premium ({mean_premium:.2f}) <= ordinary ({mean_ordinary:.2f})",
    )
    logger.info("%d millésimés, %d ordinaires", n_premium, n_ordinary)

    # --- 5. Calcul CA + contrôle structurel --------------------------------
    logger.info("[5/6] Calcul du CA")
    ca_total = total_revenue(classified)
    # Invariant : le CA doit être strictement positif (sinon données absurdes).
    _check(ca_total > 0, f"CA total invalide : {ca_total:.2f} EUR")
    # Invariant comptable : somme des CA par segment = CA total (à 1 centime près).
    ca_premium = (
        classified.loc[classified["segment"] == "premium", ["price", "total_sales"]]
        .prod(axis=1).sum()
    )
    ca_ordinary = (
        classified.loc[classified["segment"] == "ordinary", ["price", "total_sales"]]
        .prod(axis=1).sum()
    )
    _check(
        abs((ca_premium + ca_ordinary) - ca_total) < 0.01,
        f"Incohérence CA : premium({ca_premium:.2f}) + ordinary({ca_ordinary:.2f}) != total({ca_total:.2f})",
    )
    summary = revenue_summary(classified)
    logger.info("CA total = %.2f EUR\n%s", ca_total, summary.to_string(index=False))

    # --- 6. Persistance DuckDB + rapport Excel -----------------------------
    # DuckDB = persistance long terme. Excel = livrable principal pour
    # Stéphane. Si DuckDB tombe, write_table() écrit déjà un CSV de
    # secours -> on capte l'exception et on continue jusqu'au rapport.
    logger.info("[6/6] Persistance DuckDB + rapport Excel")
    duckdb_ok = True
    try:
        with get_connection() as conn:
            write_table(erp, "erp_clean", conn=conn)
            write_table(web, "web_clean", conn=conn)
            write_table(liaison, "liaison_clean", conn=conn)
            write_table(classified, "produits_consolides", conn=conn)
    except DuckDBUnavailable as exc:
        duckdb_ok = False
        logger.error("DuckDB KO -> fallback CSV déjà écrit. %s", exc)

    paths = generate_all_reports(classified)

    # --- Résumé final ------------------------------------------------------
    elapsed = (datetime.now() - started_at).total_seconds()
    logger.info("=" * 70)
    logger.info("Pipeline OK en %.1fs", elapsed)
    logger.info("Rapport Excel       : %s", paths["excel"])
    logger.info("CSV vins millésimés : %s", paths["csv_millesimes"])
    logger.info("CSV vins ordinaires : %s", paths["csv_ordinaires"])
    logger.info("DuckDB persisté     : %s", "oui" if duckdb_ok else "non (fallback CSV)")
    logger.info("=" * 70)

    return {
        "ok": True,
        "duration_s": elapsed,
        "ca_total": ca_total,
        "nb_produits": len(classified),
        "nb_premium": n_premium,
        "nb_ordinary": n_ordinary,
        "duckdb_persisted": duckdb_ok,
        "excel_path": str(paths["excel"]),
        "csv_millesimes_path": str(paths["csv_millesimes"]),
        "csv_ordinaires_path": str(paths["csv_ordinaires"]),
    }


if __name__ == "__main__":
    # Logging avec timestamps : utile pour voir combien dure chaque étape.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    result = run()
    print("\n--- RESUME ---")
    for k, v in result.items():
        print(f"  {k:18s} : {v}")
