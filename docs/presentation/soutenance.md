# Support de soutenance — Projet 10 BottleNeck

> Trame de présentation orale (~25 min + Q/R). Chaque section indique les
> points clés à dire et le visuel à montrer. Les chiffres sont ceux validés
> sur le dataset réel.

---

## 1. Contexte de la mission *(2 min)*

**À dire** :
- BottleNeck est un e-commerce de **vins prestigieux** (scénario fictif OpenClassrooms).
- Deux personae métier :
  - **Laurent** (manager) — commanditaire, veut industrialiser.
  - **Stéphane** (Data Analyst) — fait la consolidation **à la main** chaque mois
    à partir de 3 fichiers Excel issus de systèmes différents.
- **Ma mission** : remplacer ce travail manuel par un pipeline Kestra automatisé,
  testé et planifié, pour que Stéphane se concentre sur l'analyse.

**Visuel** : tableau des 3 sources

| Fichier | Système d'origine | Volume | Clé |
|---|---|---|---|
| `Fichier_erp.xlsx` | ERP interne | 825 lignes | `product_id` |
| `Fichier_web.xlsx` | WooCommerce | 1 513 lignes | `sku` |
| `fichier_liaison.xlsx` | Mapping ERP ↔ Web | 825 lignes | `product_id` ↔ `id_web` |

---

## 2. Démarche technique *(3 min)*

**À dire** : pourquoi cette stack et pas une autre.

| Outil | Pourquoi ce choix |
|---|---|
| **Kestra** | Orchestrateur moderne avec UI web, workflows YAML versionnables, retries natifs, scheduling cron. Plus simple qu'Airflow pour cette échelle. |
| **DuckDB** | Entrepôt analytique en un fichier, SQL ANSI, pas de serveur à maintenir. Idéal pour < 10 M lignes. |
| **Python + pandas** | Standard de fait pour l'ingestion / transformation, écosystème riche pour Excel. |
| **SQL pour les tests** | Tests de qualité plus lisibles et plus rapides en SQL agrégé qu'en Python. |
| **Docker Compose** | Démarrage de Kestra + PostgreSQL en une commande, environnement reproductible. |

**Méthodologie** : *"test après chaque transformation"*. Chaque tâche de
transformation est suivie d'une tâche de test qui valide le résultat avant
de poursuivre. C'est l'exigence n°1 du brief OpenClassrooms.

---

## 3. Architecture retenue *(4 min)*

**Visuel** : afficher [`docs/architecture/data_lineage.drawio.png`](../architecture/data_lineage.drawio.png).

**À dire** :
1. **Sources** → Extraction → 1er test (volumétrie sources : 825/1513/825).
2. **Nettoyage** par source → 2e test (825/714/825).
3. **Jointures** ERP-LIAISON-WEB → 3e test (714 produits).
4. **Classification** Z-score → 4e test (30 millésimés / 684 ordinaires).
5. **Calcul CA** → 5e test (CA total = 70 568,60 €).
6. **Persistance DuckDB** + **Génération rapports** (Excel + 2 CSV).

**Point clé à insister** : DuckDB sert d'**entrepôt central**. Chaque tâche
y persiste sa table de sortie, ce qui permet :
- l'**idempotence** (mode `replace` partout) → on peut relancer sans souci
- le **debug facile** (on peut requêter l'état intermédiaire après chaque étape)
- les **tests SQL** finaux qui interrogent les tables matérialisées

---

## 4. Démonstration *(5 min)*

### 4.1 Pipeline local (sans Kestra) — pour valider la logique

```bash
python -m scripts.python.run_pipeline
```

**À montrer** : la sortie affiche chaque étape avec ses tests intermédiaires
(`[TEST] ERP OK (825 lignes)`, ...) et termine sur le résumé :

```
[TEST] CA total OK (70568.60 EUR)
Pipeline OK en 1.8s
Rapport Excel       : data/processed/rapport_BottleNeck_2026-04.xlsx
CSV vins millesimes : data/processed/vins_millesimes_2026-04.csv
CSV vins ordinaires : data/processed/vins_ordinaires_2026-04.csv
DuckDB persiste     : oui
```

### 4.2 Tests pytest

```bash
python -m pytest tests/ -v
```

**À montrer** : `39 passed in 5.7s` — couvre 3 catégories :
- 26 unitaires (rapides, fixtures synthétiques)
- 8 sur les chiffres réels BottleNeck (`@pytest.mark.cibles`)
- 5 d'intégration post-pipeline DuckDB (`@pytest.mark.integration`)

### 4.3 Pipeline Kestra (UI web)

```bash
docker compose up -d
# puis ouvrir http://localhost:8080
```

**À montrer** :
- Les 4 flows YAML dans l'UI (`main_pipeline`, `extraction`, `transformation`, `tests`).
- Le trigger cron `0 9 15 * *` configuré.
- Une exécution manuelle de `main_pipeline` qui passe au vert (extraction → transformation → tests).
- L'arbre des sous-tâches avec, pour chaque transformation, sa tâche de test associée.

### 4.4 Rapport Excel livré

**À montrer** : ouvrir `data/processed/rapport_BottleNeck_2026-04.xlsx`,
parcourir les 4 onglets (`CA_par_produit`, `CA_total`, `Vins_premium`,
`Vins_ordinaires`).

---

## 5. Résultats *(3 min)*

**Visuel** : tableau comparatif chiffres attendus vs obtenus.

| Indicateur | Cible Stéphane | Pipeline | Statut |
|---|---|---|---|
| Dédoublonnage ERP | 825 | 825 | ✅ |
| Dédoublonnage LIAISON | 825 | 825 | ✅ |
| Nettoyage WEB | 1 428 | 1 428 | ✅ |
| Dédoublonnage WEB | 714 | 714 | ✅ |
| Fusion | 714 | 714 | ✅ |
| Vins millésimés (Z-score > 1,96) | 30 | 30 | ✅ |
| Vins ordinaires | 684 | 684 | ✅ |
| **CA total** | **70 568,60 €** | **70 568,60 €** | ✅ |

**À dire** :
- Pipeline complet exécuté en **~2 secondes** (ETL minuscule, pas un goulot).
- **39/39 tests pytest verts**, **8/8 tests SQL** verts.
- Le pipeline est **prêt pour la production** : tolérance aux pannes,
  idempotence, traçabilité (logs + tables intermédiaires DuckDB).

---

## 6. Tolérance aux pannes *(2 min)*

**À dire** : exigence du brief, mécanisme en cascade.

| Panne | Stratégie |
|---|---|
| DuckDB temporairement KO | Retry 3× avec backoff exponentiel (1s → 5s → 15s) |
| DuckDB définitivement KO | Fallback CSV dans `data/processed/_fallback/` + alerte |
| Erreur réseau Kestra | Retry exponentiel `maxAttempt: 3, interval: PT30S, maxInterval: PT5M` |
| Test SQL qui échoue | Flow en erreur, run précédent intact, alerte |
| Source corrompue | Log d'erreur dans Kestra (à compléter par déplacement vers `data/rejected/`) |

**Démonstration possible** : montrer le test pytest
`test_fallback_writes_csv_on_failure` qui simule une panne DuckDB
via `monkeypatch` et vérifie que le CSV de secours est bien écrit.

---

## 7. Limites et perspectives *(2 min)*

**À dire** : ce qui marche bien, ce qui pourrait être amélioré.

### Pistes d'amélioration

- **Notifications** : ajouter une tâche Kestra qui notifie Stéphane par email
  ou Slack quand le rapport mensuel est prêt.
- **Versioning des sources** : conserver un snapshot des fichiers Excel reçus
  dans `data/raw/_archive/YYYY-MM/` pour audit.
- **Drift de la classification** : surveiller le seuil Z-score sur plusieurs
  mois ; si la moyenne ou l'écart-type des prix change beaucoup, basculer
  vers un seuil absolu (ex : `prix > 87 €`).
- **Dashboard** : connecter Metabase ou Superset à DuckDB pour offrir une
  vue exploratoire à Stéphane et Laurent.
- **CI GitHub Actions** : exécuter automatiquement les 39 tests pytest à
  chaque push pour éviter les régressions.

### Ce qui a été le plus formateur

- Comprendre la **décomposition métier de Stéphane** (1 428 → 714 en 2 étapes
  distinctes : nettoyage puis dédoublonnage, pas un filtre unique).
- Choisir le bon **seuil statistique** pour la classification (Z-score 1,96
  vs IQR 1,5) — l'analyse comparative a été essentielle.
- Mettre en place la **tolérance aux pannes** réaliste (retry + fallback)
  sans tomber dans le sur-engineering.

---

## 8. Questions / Réponses *(4 min)*

**Questions probables anticipées** :

> *Pourquoi DuckDB et pas PostgreSQL ?*
- Pas de serveur à maintenir, parfait pour < 10 M lignes (BottleNeck en a 714).
- Lit les Excel/CSV nativement, intégration directe avec pandas.
- PostgreSQL serait pertinent si on passait à du multi-utilisateur ou >100 M lignes.

> *Pourquoi Z-score 1,96 et pas 2,0 ou IQR ?*
- 1,96 = quantile 97,5 % de la loi normale (seuil classique du test à 5 % d'erreur).
- C'est la méthode enseignée dans le parcours OC.
- IQR donne 32 vins, Z-score 2,0 donne 30 aussi mais 2,5 trop strict (25).
- 1,96 retombe pile sur les 30 vins identifiés par Stéphane.

> *Que se passe-t-il si un fichier source est corrompu ?*
- L'extraction lève FileNotFoundError ou ValueError.
- Kestra catch via `errors:` et passe le flow en erreur.
- Le run précédent reste intact (mode `replace` n'est appliqué qu'au succès).
- Stéphane est alerté et peut redéposer le fichier corrigé.

> *Le pipeline est-il scalable ?*
- En l'état : conçu pour < 1 M produits (load en RAM via pandas).
- Au-delà : passer à du chunked read + écriture en streaming dans DuckDB.
- DuckDB supporte > 100 M lignes sans difficulté.

---

## Aide-mémoire pendant la présentation

**Fichiers clés à pouvoir ouvrir vite** :
- [`docs/architecture/data_lineage.drawio.png`](../architecture/data_lineage.drawio.png) — vue d'ensemble
- [`scripts/python/run_pipeline.py`](../../scripts/python/run_pipeline.py) — orchestrateur lisible
- [`kestra/flows/00_main_pipeline.yml`](../../kestra/flows/00_main_pipeline.yml) — cron + retries
- [`docs/journal_de_bord.md`](../journal_de_bord.md) — backup détails techniques
- Tableau Excel `data/processed/rapport_BottleNeck_2026-04.xlsx`

**Commandes prêtes à coller** :
```bash
# 1. Pipeline local (~2 sec)
python -m scripts.python.run_pipeline

# 2. Tests pytest
python -m pytest tests/ -v

# 3. Kestra UI
docker compose up -d  # puis http://localhost:8080
```
