# Data Lineage — Architecture du pipeline BottleNeck

> Diagramme : voir [`data_lineage.drawio`](data_lineage.drawio) (source éditable)
> et [`data_lineage.drawio.png`](data_lineage.drawio.png) (export visuel).

Ce document décrit la chaîne de transformation des données depuis les 3 fichiers
sources jusqu'aux livrables finaux, avec les **tâches de test** intercalées.

---

## Vue d'ensemble

```
                      ┌──────────────────────────────────────┐
                      │  data/raw/bottleneck/  (3 fichiers)  │
                      │  Fichier_erp.xlsx       (825 lignes) │
                      │  Fichier_web.xlsx     (1 513 lignes) │
                      │  fichier_liaison.xlsx   (825 lignes) │
                      └─────────────────┬────────────────────┘
                                        │
                                        ▼
                          [extract_files.py — extraction]
                                        │
                                        ▼
                          ┌─────  TEST volumétrie sources  ─────┐
                          │   825 / 1 513 / 825 lignes brutes   │
                          └──────────────────┬──────────────────┘
                                             ▼
                            [clean_data.py — nettoyage]
                       ┌─────────────┼──────────────┬───────────────┐
                       ▼             ▼              ▼               ▼
                  clean_erp     clean_web      clean_liaison   (dropna sku)
                   825 lignes   714 lignes      825 lignes      1 428 lignes
                                  │
                                  └─── TEST volumétries cibles ───
                                        ERP=825, WEB=714, LIAISON=825
                                                   │
                                                   ▼
                                  [join_data.py — jointures]
                                        │
                          ERP ⟕ LIAISON  (LEFT JOIN sur product_id)
                                        │
                          (ERP+LIAISON) ⟕ WEB  (INNER JOIN id_web=sku)
                                        │
                                        ▼
                          ┌─────  TEST volumétrie jointure  ─────┐
                          │      Cible : 714 produits           │
                          └──────────────────┬───────────────────┘
                                             ▼
                       [identify_wines.py — classification Z-score]
                                        │
                          z = (price − μ) / σ ;   millésimé si z > 1,96
                                        │
                                        ▼
                          ┌─────  TEST cohérence Z-score  ──────┐
                          │   30 millésimés / 684 ordinaires   │
                          │   pas d'incohérence prix/segment   │
                          └──────────────────┬───────────────────┘
                                             ▼
                          [calculate_revenue.py — CA produit/total]
                                        │
                          CA = price × total_sales
                                        │
                                        ▼
                          ┌─────  TEST cohérence CA  ─────────┐
                          │     CA total = 70 568,60 €        │
                          │   CA_premium + CA_ordinary = CA   │
                          └──────────────────┬─────────────────┘
                                             ▼
              ┌──────────────────────────────┴──────────────────────────────┐
              ▼                                                             ▼
    [load_to_duckdb.py]                                       [generate_reports.py]
    Persistance analytique                                    3 livrables Excel/CSV
              │                                                             │
              ▼                                                             ▼
    duckdb/bottlerock.db                              data/processed/
      • erp_clean                                       • rapport_BottleNeck_YYYY-MM.xlsx
      • web_clean                                         (4 onglets : CA_par_produit,
      • liaison_clean                                      CA_total, Vins_premium,
      • produits_joints                                    Vins_ordinaires)
      • produits_consolides                             • vins_millesimes_YYYY-MM.csv
                                                        • vins_ordinaires_YYYY-MM.csv
```

---

## 1. Sources

| Fichier | Système d'origine | Volume brut | Clé primaire |
|---|---|---|---|
| `Fichier_erp.xlsx` | ERP interne BottleNeck | 825 lignes | `product_id` |
| `Fichier_web.xlsx` | Export WooCommerce du site | 1 513 lignes | `sku` |
| `fichier_liaison.xlsx` | Table de correspondance ERP ↔ Web | 825 lignes | `product_id` ↔ `id_web` |

## 2. Étapes de transformation

| # | Tâche | Module Python | Volumétrie en sortie |
|---|---|---|---|
| 1 | **Extraction** | `extract_files.py` | 825 / 1 513 / 825 |
| 2 | **Nettoyage** | `clean_data.py` | ERP : 825 — WEB : 714 (1 428 puis dedup sku) — LIAISON : 825 |
| 3 | **Jointures** | `join_data.py` | 714 produits consolidés |
| 4 | **Classification** | `identify_wines.py` | 30 millésimés / 684 ordinaires |
| 5 | **Calcul CA** | `calculate_revenue.py` | CA total = 70 568,60 € |
| 6a | **Persistance** | `load_to_duckdb.py` | 5 tables DuckDB |
| 6b | **Rapport** | `generate_reports.py` | 1 Excel + 2 CSV |

## 3. Tâches de test

Conformément au principe **« test après chaque transformation »**, chaque étape
de transformation est suivie d'une tâche de test qui valide le résultat avant
de poursuivre. Si un test échoue, le flow Kestra passe en erreur et le run
précédent reste intact (mode `replace` uniquement sur succès).

| Catégorie | Test | Implémentation | Cible |
|---|---|---|---|
| Volumétrie sources | extraction OK | `01_extraction.yml` (assert) | 825 / 1 513 / 825 |
| Volumétrie nettoyage | dedup respecté | `02_transformation.yml` (assert) | ERP=825, WEB=714, LIAISON=825 |
| Volumétrie jointure | fusion OK | `02_transformation.yml` + `test_volumetrie_jointure.sql` | 714 |
| Cohérence Z-score | classification correcte | `02_transformation.yml` + `test_zscore.sql` | 30 / 684, 0 violation |
| Cohérence CA | calcul cohérent | `02_transformation.yml` + `test_ca.sql` + `test_coherence.sql` | < 1 € d'écart |
| Doublons | aucun doublon résiduel | `test_doublons.sql` | 0 |
| Complétude | aucun NULL critique | `test_completude.sql` | 0 |
| Types | casts numériques OK | `test_types.sql` | 0 erreur |
| Plage dates | `post_date` ∈ [2018, today] | `test_plage_dates.sql` | 0 hors plage |

## 4. Destinations

### DuckDB (`duckdb/bottlerock.db`)

5 tables matérialisées au fil du pipeline (mode `replace`, idempotent) :

| Table | Rôle | Lignes |
|---|---|---|
| `erp_clean` | ERP nettoyé (dedup product_id) | 825 |
| `web_clean` | WEB nettoyé (drop sku NaN + dedup sku priorité 'product') | 714 |
| `liaison_clean` | Table de liaison nettoyée | 825 |
| `produits_joints` | Sortie de la double jointure (avant classification) | 714 |
| `produits_consolides` | Table finale (avec colonnes `segment` et `segment_threshold`) | 714 |

### Fichiers livrables (`data/processed/`)

| Fichier | Usage |
|---|---|
| `rapport_BottleNeck_YYYY-MM.xlsx` | Rapport mensuel multi-onglets pour Stéphane et Laurent |
| `vins_millesimes_YYYY-MM.csv` | Liste des 30 vins premium (séparateur `;`, utf-8-sig) |
| `vins_ordinaires_YYYY-MM.csv` | Liste des 684 vins ordinaires (séparateur `;`, utf-8-sig) |

### Fallback (`data/processed/_fallback/`)

Si DuckDB est indisponible après les 3 retries, les tables sont écrites en CSV
ici avant remontée d'erreur. Permet de relancer le pipeline une fois DuckDB
rétabli sans perte de données.

## 5. Tolérance aux pannes — vue d'ensemble

| Risque | Mécanisme | Localisation |
|---|---|---|
| DuckDB temporairement indisponible | Retry 3× backoff exponentiel (1s/5s/15s) | `load_to_duckdb._run_with_retry` |
| DuckDB définitivement KO | Fallback CSV dans `_fallback/` | `load_to_duckdb.write_table` |
| Erreur réseau / timeout Kestra | Retry exponentiel maxAttempt=3 | `kestra/flows/*.yml` (clé `retry`) |
| Test SQL qui échoue | Flow en erreur, run précédent intact | `03_tests.yml` (assert) |
| Kestra redémarre en plein run | Mode `replace` partout = idempotence | `load_to_duckdb.write_table` |
| Source corrompue | Log d'erreur Kestra (manuel si besoin) | `01_extraction.yml` (`errors:`) |

## 6. Planification

```yaml
# kestra/flows/00_main_pipeline.yml
triggers:
  - id: schedule_15_du_mois
    type: io.kestra.plugin.core.trigger.Schedule
    cron: "0 9 15 * *"
    timezone: Europe/Paris
```

Déclenchement automatique **le 15 de chaque mois à 9h00 (Paris)**. Rejouable
manuellement à tout moment via l'UI Kestra ou l'API REST (utile après
correction d'un fichier source).
