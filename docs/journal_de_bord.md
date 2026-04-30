# Journal de bord — Projet 10 BottleNeck

Ce journal documente la démarche, les choix techniques et les difficultés rencontrées
au fil du projet. Il sert de mémoire de travail pour la soutenance.

---

## 1. Contexte et compréhension du besoin

L'entreprise BottleNeck (e-commerce de vins prestigieux) consolide manuellement
ses données de vente. Stéphane (Data Analyst) reçoit chaque mois trois fichiers Excel
issus de systèmes différents et doit les rapprocher pour produire un rapport de
chiffre d'affaires et identifier les vins millésimés.

Laurent (manager) souhaite **industrialiser** ce processus pour que Stéphane se
concentre sur l'analyse plutôt que sur la consolidation. Le pipeline doit être
**reproductible**, **testable** et **planifié**.

### Sources reçues

| Fichier | Système d'origine | Volume | Clé |
|---|---|---|---|
| `Fichier_erp.xlsx` | ERP interne | 825 lignes | `product_id` |
| `Fichier_web.xlsx` | CMS WooCommerce du site | 1 513 lignes | `sku` |
| `fichier_liaison.xlsx` | Table de correspondance ERP ↔ Web | 825 lignes | `product_id` ↔ `id_web` |

---

## 2. Choix de la stack

| Outil | Pourquoi ce choix |
|---|---|
| **Kestra** | Orchestrateur moderne avec UI web, workflows YAML versionnables, retries natifs, scheduling cron. Plus simple que Airflow pour un projet à cette échelle. |
| **DuckDB** | Entrepôt analytique en un seul fichier, SQL ANSI, lectures Excel/CSV natives. Pas de serveur à maintenir contrairement à PostgreSQL. Idéal pour des volumes < 10 M lignes. |
| **Python + pandas** | Standard de fait pour l'ingestion et la transformation. openpyxl gère les Excel des sources. |
| **SQL pour les tests** | Les tests de qualité sont plus lisibles et plus rapides en SQL (DuckDB) qu'en Python pour ce type de vérifications agrégées. |
| **Docker Compose** | Simplifie le démarrage de Kestra + PostgreSQL en une commande, environnement reproductible sur n'importe quelle machine. |
| **draw.io** | Outil gratuit pour le data lineage, format `.drawio` versionnable en git. |

---

## 3. Architecture retenue (data lineage)

### Principe : « test après chaque transformation »

Le diagramme `docs/architecture/data_lineage.drawio` illustre la chaîne :

```
SOURCES → Extraction → Nettoyage → [TEST 1+2] → Fusion → [TEST 3]
       → Classification z-score → [TEST 5] → Calcul CA → [TEST 4]
       → Extractions (Excel + 2 CSV)
```

Chaque tâche de transformation est suivie d'une **tâche de test** qui valide
le résultat avant de poursuivre. Si un test échoue, le flow Kestra passe en
erreur et le run précédent reste intact (pas de corruption silencieuse).

DuckDB est utilisé en **entrepôt central** : chaque tâche y persiste sa table
de sortie, ce qui permet l'idempotence (mode `replace`) et facilite le débogage
en consultant la base après chaque exécution.

---

## 4. Démarche de développement

### 4.1 Exploration du dataset

Avant d'écrire la moindre ligne de pipeline, j'ai exploré les fichiers sources
en notebook pour comprendre :
- Le schéma exact de chaque fichier (colonnes, types, valeurs uniques)
- La nature des doublons dans `Fichier_web.xlsx` (798 doublons sur sku)
- La présence de lignes "attachment" (images de produits) qui polluent le fichier web
- Les `id_web` manquants dans le fichier de liaison

Cette exploration a permis de **valider les chiffres cibles annoncés par Stéphane**
avant de coder, et d'éviter les fausses pistes.

### 4.2 Règles de nettoyage (alignées sur Stéphane)

La logique implémentée respecte exactement la décomposition de Stéphane :

| Étape | Règle | Cible |
|---|---|---|
| Dédoublonnage ERP | `drop_duplicates(product_id)` | 825 lignes |
| Dédoublonnage LIAISON | `drop_duplicates(product_id)` (les `id_web` NaN sont conservés à ce stade — ils seront filtrés par la jointure inner) | 825 lignes |
| Nettoyage WEB | `dropna(subset=['sku'])` — supprime les 85 lignes sans sku | 1 428 lignes |
| Dédoublonnage WEB | `drop_duplicates(sku)` avec **priorité aux lignes `post_type='product'`** sur les `attachment` (sinon les images écraseraient les vraies fiches produits) | 714 lignes |

**Difficulté rencontrée** : initialement, j'avais filtré directement sur
`post_type='product' AND post_status='publish'`, ce qui donnait 716 lignes — pas 1 428.
Après échange, j'ai compris que Stéphane considère le "nettoyage" et le
"dédoublonnage" comme deux étapes distinctes : la première supprime juste les
lignes vides (sku NaN), la seconde déduplique. La distinction est importante
pour le journal de bord et les tests intermédiaires.

### 4.3 Stratégie de jointure

```
ERP (825) ⟕ LIAISON (825) → erp_liaison (825 lignes, dont 91 sans id_web)
                          ⟕ WEB (714) → produits_consolides (714 lignes)
```

- Premier `LEFT JOIN` ERP ↔ LIAISON sur `product_id` : conserve tous les produits ERP.
- Deuxième `INNER JOIN` avec WEB sur `id_web = sku` : ne garde que les produits
  qui existent réellement côté site (les 91 produits ERP sans `id_web` sont écartés).

### 4.4 Identification des vins millésimés (z-score)

J'ai testé plusieurs méthodes de classification avant de retenir le z-score :

| Méthode | Vins identifiés | Verdict |
|---|---|---|
| IQR boxplot (`Q3 + 1.5×IQR`) | 32 | Trop large |
| Z-score > 1.96 (seuil 95% loi normale) | **30** | ✅ Cible Stéphane |
| Z-score > 2.0 | 30 | Identique 1.96 ici |
| Z-score > 2.5 | 25 | Trop strict |
| Top N par prix | 30 | Méthode arbitraire, pas reproductible |
| Détection mot "millésime" dans titre | 3 | Trop sémantique |

Le **z-score à 1.96** correspond au seuil statistique classique de l'intervalle
de confiance à 95% sur une distribution normale. C'est la méthode enseignée
dans le parcours OpenClassrooms et celle qui retombe pile sur les 30 vins
identifiés par Stéphane. Méthode retenue par défaut, IQR conservée comme
alternative via le paramètre `method='iqr'`.

Seuils calculés sur le dataset :
- moyenne prix : 32,49 €
- écart-type : 27,81 €
- seuil = `32.49 + 1.96 × 27.81` = **87,00 €**
- 30 vins ont un prix > 87 €

### 4.5 Calcul du chiffre d'affaires

Définition retenue : `CA produit = price × total_sales`.

CA total obtenu : **70 568,60 €**, exactement la valeur annoncée par Stéphane.

Répartition par segment :
- Vins millésimés : 6 884,40 € (9,76 % du CA)
- Vins ordinaires : 63 684,20 € (90,24 % du CA)

### 4.6 Génération des livrables

Trois fichiers produits en sortie de pipeline :

1. **`rapport_BottleNeck_YYYY-MM.xlsx`** — Excel à 4 onglets pour la consultation
   confortable par Stéphane :
   - `CA_par_produit` (714 lignes, trié par CA décroissant)
   - `CA_total` (1 ligne récap avec date de génération)
   - `Vins_premium` (30 lignes)
   - `Vins_ordinaires` (684 lignes)

2. **`vins_millesimes_YYYY-MM.csv`** — extraction des 30 vins millésimés en CSV
   (séparateur `;`, encodage `utf-8-sig` pour qu'Excel ouvre correctement les accents).

3. **`vins_ordinaires_YYYY-MM.csv`** — extraction des 684 vins ordinaires.

Le double format (Excel + CSV) permet à la fois la consultation humaine et
la reprise par d'autres outils (Power BI, R, autre script).

---

## 5. Implémentation Kestra

### 5.1 Architecture des flows

Quatre fichiers YAML composent l'orchestration :

| Flow | Rôle |
|---|---|
| `00_main_pipeline.yml` | Flow principal : enchaîne extraction → transformation → tests via subflows. Porte le **trigger cron** et la stratégie de retry globale. |
| `01_extraction.yml` | Lecture des 3 Excel + test de volumétrie (825/1513/825). |
| `02_transformation.yml` | Nettoyage → Jointure → Classification → CA → Génération du rapport. Chaque tâche de transformation est suivie de sa tâche de test inline. |
| `03_tests.yml` | Cinq tests SQL finaux sur DuckDB (cf. section 6). |

### 5.2 Planification

```yaml
triggers:
  - id: schedule_15_du_mois
    type: io.kestra.plugin.core.trigger.Schedule
    cron: "0 9 15 * *"
    timezone: Europe/Paris
```

Le pipeline se déclenche **le 15 de chaque mois à 9h00 (heure Paris)**.

Au-delà du cron, le pipeline peut être déclenché manuellement depuis l'UI
Kestra ou via l'API REST, ce qui est utile pour les rejeux après correction
de fichier source.

### 5.3 Tolérance aux pannes

Plusieurs mécanismes en cascade :

1. **Retry exponentiel au niveau Kestra** : `maxAttempt: 3`, `interval: PT30S`,
   `maxInterval: PT5M`. Configuré sur chaque tâche de transformation.

2. **Retry interne au code Python** dans `load_to_duckdb.py` : décorateur
   `@_with_retry` avec backoff de 1s, 5s, 15s qui catche les `IOException`,
   `ConnectionException` et `OSError`.

3. **Fallback CSV** : si DuckDB reste indisponible après les 3 retries internes,
   les données sont écrites en CSV dans `data/processed/_fallback/<table>.csv`
   et l'exception est propagée pour que Kestra puisse alerter. Le pipeline
   peut être rejoué une fois DuckDB rétabli sans perte de données.

4. **Tests bloquants** : si un test échoue, le flow passe en erreur. Les
   tables DuckDB du run précédent restent intactes (mode `replace` uniquement
   sur succès).

5. **Idempotence** : tous les écritures DuckDB sont en mode `replace`. Relancer
   le pipeline donne exactement le même résultat, même après une interruption
   à mi-parcours.

---

## 6. Tests de qualité

Les cinq catégories de tests imposées par le brief sont toutes implémentées,
en SQL pour la version Kestra finale et en pytest pour le développement local.

| # | Test | Implémentation | Cible |
|---|---|---|---|
| 1 | Absence de doublons | `scripts/sql/tests/test_doublons.sql` — `COUNT(*) - COUNT(DISTINCT)` sur les 4 tables | 0 |
| 2 | Absence de valeurs manquantes | `test_completude.sql` — `COUNT WHERE price IS NULL OR sku IS NULL OR product_id IS NULL` | 0 |
| 3 | Cohérence volumétrie après jointures | `test_volumetrie_jointure.sql` — `\|COUNT(*) - 714\|` | 0 |
| 4 | Cohérence du CA calculé | `test_ca.sql` — `\|SUM(price × total_sales) - 70568.60\|` | < 1 € |
| 5 | Cohérence z-score millésimes/ordinaires | `test_zscore.sql` — vérifie qu'aucun vin n'est mal classé selon son prix vs le seuil mean+1.96·std, et que les volumétries 30/684 sont respectées | 0 |

### Tests pytest complémentaires

39 tests pytest couvrent l'ensemble du pipeline :
- **23 tests unitaires** sur fixtures synthétiques (rapides, indépendants des données réelles)
- **8 tests "cibles"** qui valident les chiffres exacts de Stéphane sur le dataset réel
- **4 tests d'intégration** post-pipeline qui interrogent DuckDB

Le dispatch est fait via marqueurs pytest :
```bash
python -m pytest tests/ -m cibles        # validation chiffres
python -m pytest tests/ -m integration   # post-run
python -m pytest tests/ -m "not cibles and not integration"  # uniquement unitaires
```

---

## 7. Difficultés rencontrées et apprentissages

### Encoding des fichiers Excel
Les titres du fichier web contiennent des caractères accentués (`Château`,
`Pomerol`, etc.). À l'affichage console Windows (cp1252), ils apparaissent
mal, mais les bytes UTF-8 sont corrects. Pour les CSV de sortie, j'utilise
`encoding='utf-8-sig'` (UTF-8 avec BOM) pour qu'Excel les ouvre directement
sans devoir passer par "Importer depuis CSV".

### Compréhension de la logique métier
La première version du nettoyage filtrait WEB sur `post_type='product' AND post_status='publish'`
en une seule étape (716 lignes). C'était logiquement correct mais ne correspondait
pas à la décomposition de Stéphane (1 428 puis 714). J'ai ré-écouté l'analyse :
les attachments ne sont pas "supprimés" mais "déduplifiés" (même sku que le
produit, le dédoublonnage les écarte naturellement avec la priorité `post_type='product'`).
Comprendre la décomposition de Stéphane était essentiel pour les tests intermédiaires.

### Choix entre IQR et z-score pour les millésimés
J'ai d'abord implémenté la méthode IQR (boxplot) qui donnait 32 vins. La cible
de 30 m'a fait creuser et tester d'autres méthodes statistiques. Le z-score
à 1.96 (seuil 95%) tombe pile, et c'est aussi la méthode classique enseignée
dans la formation OpenClassrooms. Les deux méthodes sont conservées dans
`identify_wines.py` via le paramètre `method`.

### Test du fallback CSV
Tester la résilience à une panne DuckDB sans réellement faire planter DuckDB
nécessite du `monkeypatch`. La première version du test échouait parce que
le décorateur `@_with_retry` était bypassé par le monkeypatch. La solution
a été de simuler la panne en levant directement `DuckDBUnavailable` dans la
fonction interne, ce qui exerce bien le bloc de fallback du `write_table`
externe.

---

## 8. Validation finale

Pipeline lancé en local (`python -m scripts.python.run_pipeline`) :

| Indicateur | Cible Stéphane | Pipeline | Statut |
|---|---|---|---|
| Dédoublonnage ERP | 825 | 825 | ✅ |
| Dédoublonnage LIAISON | 825 | 825 | ✅ |
| Nettoyage WEB | 1 428 | 1 428 | ✅ |
| Dédoublonnage WEB | 714 | 714 | ✅ |
| Fusion | 714 | 714 | ✅ |
| Vins millésimés (z-score > 1.96) | 30 | 30 | ✅ |
| Vins ordinaires | 684 | 684 | ✅ |
| CA total | 70 568,60 € | 70 568,60 € | ✅ |

Pipeline complet exécuté en ~2 secondes, base DuckDB persistée, 3 livrables
générés (Excel + 2 CSV), 39/39 tests pytest verts.

---

## 9. Pistes d'amélioration

- **Notifications** : ajouter une tâche de notification Slack/email à la fin
  du flow Kestra pour avertir Stéphane que le rapport est prêt.
- **Versioning des sources** : conserver un snapshot des fichiers Excel reçus
  dans `data/raw/_archive/YYYY-MM/` pour audit ultérieur.
- **Drift de la classification** : surveiller la dérive du seuil z-score au
  fil des mois. Si la moyenne ou l'écart-type des prix change beaucoup, il
  faudra peut-être basculer sur un seuil absolu (par exemple `prix > 87 €`).
- **Tableau de bord** : connecter Metabase ou Superset à DuckDB pour offrir
  une vue exploratoire à Stéphane et Laurent.
- **CI GitHub Actions** : exécuter automatiquement les 39 tests pytest à
  chaque push pour éviter les régressions sur les scripts Python.
