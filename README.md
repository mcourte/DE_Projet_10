# Projet 10 — Pipeline d'orchestration BottleNeck

Pipeline automatisé pour industrialiser la consolidation manuelle effectuée par
Stéphane (Data Analyst) chez BottleNeck (e-commerce de vins prestigieux).

## Stack

- **Kestra** — orchestrateur (workflows YAML)
- **DuckDB** — entrepôt analytique local (fichier unique `.db`)
- **Python + pandas** — extraction, jointure, nettoyage, classification
- **openpyxl** — rapport Excel multi-onglets
- **SQL** — agrégations et tests de qualité
- **Docker Compose** — runtime Kestra + PostgreSQL

## Sources (dataset BottleNeck)

| Fichier | Volume | Clé |
|---|---|---|
| `data/raw/bottleneck/Fichier_erp.xlsx` | 825 lignes | `product_id` |
| `data/raw/bottleneck/Fichier_web.xlsx` | 1 513 lignes | `sku` |
| `data/raw/bottleneck/fichier_liaison.xlsx` | 825 lignes | `product_id` ↔ `id_web` |

## Démarrage rapide

```bash
# 1. Installer les dépendances Python
python -m pip install -r requirements.txt

# 2. (Option A) Pipeline local sans Kestra — pour debug rapide
python -m scripts.python.run_pipeline

# 3. (Option B) Pipeline avec Kestra
docker compose up -d
# Ouvrir http://localhost:8080
# Importer les fichiers de kestra/flows/ dans l'UI
# Déclencher main_pipeline manuellement, ou attendre le 15 du mois à 9h
```

## Livrables produits

Après exécution :
- `duckdb/bottlerock.db` — base DuckDB avec les tables `erp_clean`, `web_clean`, `liaison_clean`, `produits_consolides`
- `data/processed/rapport_BottleNeck_YYYY-MM.xlsx` — rapport Excel à 4 onglets :
  - **CA_par_produit** : 714 produits triés par CA décroissant
  - **CA_total** : ligne récapitulative (`CA total = 70 568,60 €`)
  - **Vins_premium** : 32 vins prestigieux
  - **Vins_ordinaires** : 682 vins courants

## Architecture

Chaque tâche de transformation est suivie d'une tâche de test (architecture
"data quality at every step") :

```
extraction (3 Excel)
   ↓ test volumétrie (825 / 1513 / 825)
nettoyage (filtre WEB, dedup sku)
   ↓ test : WEB nettoyé = 714 lignes
jointure (ERP ⟕ LIAISON ⟕ WEB)
   ↓ test : 714 produits consolidés
classification IQR (premium / ordinary)
   ↓ test : somme = total
calcul CA + génération Excel
   ↓ test : 4 onglets présents
tests SQL finaux (complétude, cohérence, types, plage dates)
```

## Tolérance aux pannes

| Risque | Stratégie |
|---|---|
| DuckDB indisponible | Retry 3× avec backoff exponentiel (1s, 5s, 15s) puis fallback CSV dans `data/processed/_fallback/` |
| Échec d'écriture Excel | Retry au niveau Kestra (3 tentatives avec backoff) |
| Test métier échoué | Pipeline en erreur, run précédent conservé intact |
| Kestra redémarre | Idempotence (mode `replace`), simple relance manuelle |
| Source corrompue | Déplacement automatique vers `data/rejected/` |

## Planification

```yaml
# kestra/flows/00_main_pipeline.yml
cron: "0 9 15 * *"      # le 15 de chaque mois à 9h00
timezone: Europe/Paris
```

## Tests pytest

```bash
# Tous les tests (32)
python -m pytest tests/ -v

# Uniquement unitaires (rapides, pas de fichiers réels)
python -m pytest tests/ -m "not cibles and not integration"

# Vérifier les chiffres cibles BottleNeck
python -m pytest tests/ -m cibles

# Vérifier l'intégrité DuckDB après pipeline
python -m pytest tests/ -m integration
```

## Chiffres de référence (validés)

| Indicateur | Valeur |
|---|---|
| Lignes ERP brutes | 825 |
| Lignes WEB brutes | 1 513 |
| Lignes WEB après nettoyage | **714** |
| Produits consolidés (jointure) | **714** |
| Vins premium (IQR) | **32** |
| Vins ordinaires | **682** |
| **CA total** | **70 568,60 €** |
| Durée d'exécution complète | ~2 secondes |

## Arborescence

```
DE_Projet_10/
├── README.md                        ← ce fichier
├── docker-compose.yml               ← Kestra + PostgreSQL
├── requirements.txt
├── pytest.ini
├── data/
│   ├── raw/bottleneck/              ← 3 fichiers Excel sources
│   ├── processed/                   ← rapports Excel générés
│   └── rejected/                    ← sources corrompues
├── duckdb/bottlerock.db             ← base DuckDB
├── kestra/flows/
│   ├── 00_main_pipeline.yml         ← cron + retries
│   ├── 01_extraction.yml            ← + test volumétrie
│   ├── 02_transformation.yml        ← clean / join / classify / report + tests
│   └── 03_tests.yml                 ← tests SQL globaux
├── scripts/
│   ├── python/
│   │   ├── extract_files.py
│   │   ├── clean_data.py
│   │   ├── join_data.py
│   │   ├── identify_wines.py
│   │   ├── calculate_revenue.py
│   │   ├── generate_reports.py
│   │   ├── load_to_duckdb.py        ← retry + fallback CSV
│   │   └── run_pipeline.py          ← orchestrateur local
│   └── sql/
│       ├── 01_create_tables.sql
│       ├── 02_ca_premium.sql
│       ├── 03_ca_ordinary.sql
│       ├── 04_ca_total.sql
│       └── tests/
│           ├── test_completude.sql
│           ├── test_coherence.sql
│           ├── test_types.sql
│           └── test_plage_dates.sql
├── tests/
│   └── test_pipeline.py             ← 32 tests pytest
└── docs/
    ├── journal_de_bord.md
    ├── architecture/data_lineage.md
```
