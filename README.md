# Projet 10 — Pipeline d'orchestration BottleNeck

Pipeline automatisé pour industrialiser la consolidation manuelle effectuée par
Stéphane (Data Analyst) chez BottleNeck (e-commerce de vins prestigieux).


## Stack

- **Kestra** — orchestrateur (workflows YAML, planification, retry, Switch)
- **DuckDB** — entrepôt analytique local (fichier unique `.db`)
- **Python + pandas** — extraction, jointure, nettoyage, classification
- **openpyxl** — rapport Excel multi-onglets
- **SQL** — agrégations et tests de qualité
- **Docker Compose** — runtime Kestra + PostgreSQL
- **pytest** — 41 tests (structurels + cibles métier)

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

# 2. (Option A) Pipeline local sans Kestra — pour debug rapide (~2 s)
python -m scripts.python.run_pipeline

# 3. (Option B) Pipeline avec Kestra
docker compose up -d
# Ouvrir http://localhost:8080
# Importer les fichiers de kestra/flows/ dans l'UI
# Déclencher 00_main_pipeline manuellement, ou attendre le 15 du mois à 9h
```

## Étapes pour lancer le projet

### Étape 1 — Télécharger le code

Cliquer sur le bouton vert **\<\> Code** en haut de la page GitHub, puis sur **Download ZIP**.
Extraire l'ensemble des fichiers dans le dossier où vous souhaitez stocker le projet et les données.

### Étape 2 — Installer Python et ouvrir le terminal

Télécharger [Python](https://www.python.org/downloads/) et [l'installer](https://fr.wikihow.com/installer-Python).

Ouvrir le terminal de commande :
- **Windows** : [démarche à suivre](https://support.kaspersky.com/fr/common/windows/14637#block0)
- **Mac OS** : [démarche à suivre](https://support.apple.com/fr-fr/guide/terminal/apd5265185d-f365-44cb-8b09-71a064a42125/mac)
- **Linux** : ouvrir directement le terminal de commande

### Étape 3 — Créer un environnement virtuel

```bash
# Créer l'environnement
python3 -m venv env

# Activer l'environnement — Linux / Mac OS
source env/bin/activate

# Activer l'environnement — Windows
env\Scripts\activate.bat
```

### Étape 4 — Installer les dépendances

```bash
pip install -r requirements.txt
```

### Étape 5 — Créer le fichier `.env`

Copier `.env.example` en `.env` (le `.env` est ignoré par git, il peut contenir
des secrets sans risque) :

```bash
# Linux / Mac OS
cp .env.example .env

# Windows
copy .env.example .env
```

Adapter les valeurs si besoin (par défaut le pipeline pointe sur
`duckdb/bottlerock.db` et Kestra sur `http://localhost:8080`).

### Étape 6 — Placer les fichiers sources

Copier les trois fichiers Excel dans le dossier `data/raw/bottleneck/` :

```
data/raw/bottleneck/
├── Fichier_erp.xlsx
├── Fichier_web.xlsx
└── fichier_liaison.xlsx
```

### Étape 7 — Lancer le pipeline

**Option A — Pipeline local (sans Docker, recommandé pour tester rapidement)**

```bash
python -m scripts.python.run_pipeline
```

Les livrables sont générés dans `data/processed/` en ~2 secondes.

**Option B — Pipeline avec Kestra (production)**

```bash
# Démarrer Kestra + PostgreSQL
docker compose up -d

# Ouvrir l'interface Kestra
# http://localhost:8080

# Importer les flows depuis kestra/flows/ dans l'UI
# Déclencher 00_main_pipeline manuellement, ou attendre le 15 du mois à 9h
```

> **Prérequis Option B** : [Docker Desktop](https://www.docker.com/products/docker-desktop/) installé et démarré.

### Étape 8 — Vérifier les résultats

```bash
# Tous les tests (41)
python -m pytest tests/ -v

# Uniquement les tests structurels — utilisables chaque mois sur tout dataset
python -m pytest tests/ -m "not cibles"

# Uniquement les chiffres cibles de Stéphane (POC initiale)
python -m pytest tests/ -m cibles

# Tests d'intégrité DuckDB après run du pipeline
python -m pytest tests/ -m integration
```

Après exécution :
- `duckdb/bottlerock.db` — base DuckDB avec les tables `erp_clean`, `web_clean`, `liaison_clean`, `produits_consolides`
- `data/processed/rapport_BottleNeck_YYYY-MM.xlsx` — rapport Excel à 4 onglets :
  - **CA_par_produit** : 714 produits triés par CA décroissant
  - **CA_total** : ligne récapitulative (`CA total = 70 568,60 €`)
  - **Vins_premium** : 30 vins millésimés (z-score > 1,96)
  - **Vins_ordinaires** : 684 vins courants
- `data/processed/vins_millesimes_YYYY-MM.csv` — 30 vins premium (séparateur `;`, UTF-8 BOM)
- `data/processed/vins_ordinaires_YYYY-MM.csv` — 684 vins ordinaires

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
classification z-score (premium / ordinary)
   ↓ test : 30 millésimés, 684 ordinaires, CA total = 70 568,60 €
génération du rapport Excel
   ↓ test : 4 onglets présents
extractions CSV (tâche Switch)
   ↓ test : CSV millésimés et ordinaires non vides
tests SQL globaux (complétude, cohérence, types, plage dates)
```

Le diagramme complet est disponible dans
[`docs/architecture/data_lineage.drawio.png`](docs/architecture/data_lineage.drawio.png).

## Fonctionnalités Kestra mises en œuvre

| Fonctionnalité Kestra | Où | Utilité |
|---|---|---|
| **Schedule / cron** | `00_main_pipeline.yml` | Déclenchement le 15 du mois à 9h |
| **Subflow** | `00_main_pipeline.yml` | Orchestrateur qui chaîne 3 sous-pipelines |
| **Retry exponentiel** | `00_main_pipeline.yml`, `02_transformation.yml` | Robustesse face aux services tiers indisponibles |
| **Switch** | `02_transformation.yml` | Branche l'extraction CSV selon le mode (`full` / `premium-only` / `ordinary-only`) |
| **Inputs (SELECT)** | `02_transformation.yml` | Paramètre `extraction_mode` pour les demandes ad-hoc |
| **Bloc `errors:`** | `00_main_pipeline.yml`, `01_extraction.yml` | Alerting automatique en cas de panne |
| **Python Script tasks** | tous les flows | Exécution des scripts du dossier `scripts/python/` |

## Tolérance aux pannes

| Risque | Stratégie |
|---|---|
| DuckDB indisponible | Retry 3× avec backoff exponentiel (1s, 5s, 15s) puis fallback CSV dans `data/processed/_fallback/` |
| Échec d'écriture Excel | Retry au niveau Kestra (3 tentatives avec backoff) |
| Test métier échoué | Pipeline en erreur, run précédent conservé intact |
| Subflow Kestra en échec | Bloc `errors:` global → log d'alerte (branchable sur Slack/email via plugin notifications) |
| Kestra redémarre en plein run | Idempotence (mode `replace`), simple relance manuelle |
| Source corrompue | Déplacement automatique vers `data/rejected/` |

## Planification

```yaml
# kestra/flows/00_main_pipeline.yml
triggers:
  - id: monthly_schedule
    type: io.kestra.core.models.triggers.types.Schedule
    cron: "0 9 15 * *"           # le 15 de chaque mois à 9h00
    timezone: Europe/Paris
```

## Tests pytest

**41 tests** répartis sur **2 fichiers**, organisés en 3 catégories pour
permettre une exécution mensuelle sans dépendance aux chiffres POC :

| Fichier | Catégorie | Nb | Description |
|---|---|---:|---|
| `tests/test_pipeline.py` | Unitaires | 25 | Logique des fonctions sur fixtures synthétiques |
| `tests/test_pipeline.py` | `@pytest.mark.integration` | 5 | Invariants structurels post-pipeline (pas de doublons, somme cohérente…) — **réutilisables chaque mois** |
| `tests/test_chiffres_bottleneck.py` | `@pytest.mark.cibles` | 8 | Chiffres exacts de Stéphane sur les fichiers source (825 / 1428 / 714 / 30 / 70568,60 €) |
| `tests/test_chiffres_bottleneck.py` | `@pytest.mark.cibles` + `integration` | 3 | Chiffres exacts vérifiés dans DuckDB après run |

### Commandes utiles

```bash
# Tous les tests (41)
python -m pytest tests/ -v

# Mensuel : uniquement structurels (32 tests) — passe quelle que soit la donnée
python -m pytest tests/ -m "not cibles"

# Validation POC : uniquement les chiffres cibles de Stéphane (11 tests)
python -m pytest tests/ -m cibles

# Intégration DuckDB (5 tests post-pipeline)
python -m pytest tests/ -m integration
```

### Tests SQL Kestra (en plus des pytest)

8 tests SQL exécutés par le flow `03_tests.yml` :
`test_doublons`, `test_completude`, `test_volumetrie_jointure`, `test_ca`,
`test_zscore`, `test_coherence`, `test_types`, `test_plage_dates`.

## Chiffres de référence (validés par Stéphane)

| Indicateur | Valeur |
|---|---|
| Lignes ERP brutes | 825 |
| Lignes WEB brutes | 1 513 |
| Lignes WEB après drop sku NaN | 1 428 |
| Lignes WEB après dédup sku | **714** |
| Produits consolidés (jointure) | **714** |
| Vins millésimés (z-score > 1,96) | **30** |
| Vins ordinaires | **684** |
| **CA total** | **70 568,60 €** |
| Durée d'exécution complète | ~2 secondes |

## Arborescence

```
DE_Projet_10/
├── README.md                              ← ce fichier
├── docker-compose.yml                     ← Kestra + PostgreSQL
├── requirements.txt
├── pytest.ini                             ← marqueurs cibles / integration
├── data/
│   ├── raw/bottleneck/                    ← 3 fichiers Excel sources
│   ├── processed/                         ← rapports Excel + CSV générés
│   └── rejected/                          ← sources corrompues
├── duckdb/bottlerock.db                   ← base DuckDB
├── kestra/flows/
│   ├── 00_main_pipeline.yml               ← cron + retries + errors block
│   ├── 01_extraction.yml                  ← + test volumétrie
│   ├── 02_transformation.yml              ← clean / join / classify / report + Switch CSV
│   └── 03_tests.yml                       ← tests SQL globaux
├── scripts/
│   ├── python/
│   │   ├── extract_files.py               ← lecture des 3 Excel
│   │   ├── clean_data.py                  ← dédup + filtres
│   │   ├── join_data.py                   ← jointure 3 sources
│   │   ├── identify_wines.py              ← classification z-score / IQR
│   │   ├── calculate_revenue.py           ← CA par produit + CA total
│   │   ├── generate_reports.py            ← Excel 4 onglets + 2 CSV
│   │   ├── load_to_duckdb.py              ← retry + fallback CSV
│   │   └── run_pipeline.py                ← orchestrateur local (sans Kestra)
│   └── sql/
│       ├── 01_create_tables.sql           ← schémas (documentaire)
│       ├── 02_ca_premium.sql              ← CA des vins millésimés
│       ├── 03_ca_ordinary.sql             ← CA des vins ordinaires
│       ├── 04_ca_total.sql                ← CA total
│       └── tests/
│           ├── test_doublons.sql
│           ├── test_completude.sql
│           ├── test_volumetrie_jointure.sql
│           ├── test_ca.sql
│           ├── test_zscore.sql
│           ├── test_coherence.sql
│           ├── test_types.sql
│           └── test_plage_dates.sql
├── tests/
│   ├── test_pipeline.py                   ← 32 tests structurels (unitaires + intégration)
│   └── test_chiffres_bottleneck.py        ← 11 tests cibles POC (chiffres exacts Stéphane)
├── .env.example                           ← gabarit des variables d'environnement
└── docs/
    ├── journal_de_bord.md                 ← démarche, choix techniques, difficultés
    ├── architecture/
    │   ├── data_lineage.md                ← documentation du lineage
    │   ├── data_lineage.drawio            ← diagramme source (éditable)
    │   └── data_lineage.drawio.png        ← export visuel
```

## Méthodologie statistique — classification z-score

Un vin est classé **millésimé** (premium) si son z-score sur le prix dépasse
**1,96**, soit le quantile 97,5 % de la loi normale (seuil bilatéral à 5 %).

```
z_score(prix) = (prix - moyenne) / écart-type
```

Sur le dataset BottleNeck :
- moyenne des prix : **32,49 €**
- écart-type : **27,81 €**
- seuil de classification : **87,00 €**
- → **30 vins millésimés** / 684 ordinaires

La fonction `classify_wines()` accepte aussi la méthode IQR comme alternative
(`method="iqr"`) et un seuil personnalisé (`threshold=2.0` par exemple).

## Documentation complémentaire

- 📘 [Journal de bord](docs/journal_de_bord.md) — démarche complète, choix techniques, difficultés rencontrées
- 🏗 [Data lineage](docs/architecture/data_lineage.md) + [diagramme Drawio](docs/architecture/data_lineage.drawio.png)

