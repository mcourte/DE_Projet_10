# Projet 10 — Pipeline d'orchestration BottleRock

Pipeline Kestra pour industrialiser le travail de consolidation des données
effectué manuellement par Stéphane (Data Analyst) chez BottleRock.

## Stack

- **Kestra** — orchestrateur (workflows YAML)
- **DuckDB** — entrepôt analytique local (fichier unique)
- **Python + pandas** — scripts d'extraction et de nettoyage
- **SQL** — agrégations et tests de qualité
- **Docker Compose** — runtime Kestra + PostgreSQL

## Arborescence

```
DE_Projet_10/
├── docker-compose.yml       # Kestra + PostgreSQL
├── requirements.txt         # dépendances Python
├── .env.example             # variables d'environnement
├── data/
│   ├── raw/{premium,ordinary}/   # fichiers sources (non versionnés)
│   ├── processed/                # fichiers après nettoyage
│   └── rejected/                 # fichiers rejetés par les tests
├── duckdb/                  # base DuckDB (non versionnée)
├── kestra/
│   └── flows/               # workflows YAML
│       ├── 00_main_pipeline.yml
│       ├── 01_extraction.yml
│       ├── 02_transformation.yml
│       └── 03_tests.yml
├── scripts/
│   ├── python/              # scripts d'ingestion et de nettoyage
│   └── sql/                 # requêtes d'agrégation + tests
│       └── tests/
├── tests/                   # tests pytest
└── docs/
    ├── architecture/        # diagramme data lineage (.drawio)
    └── presentation/        # support de soutenance
```

## Démarrage rapide

```bash
# 1. Installer les dépendances Python
python -m pip install -r requirements.txt

# 2. Lancer Kestra
docker compose up -d

# 3. Ouvrir l'UI Kestra
# http://localhost:8080
```

## Les 5 étapes du projet

1. **Data Lineage** — diagramme draw.io dans `docs/architecture/`
2. **Extraction nominale** — workflow Kestra `01_extraction.yml`
3. **Tests qualité** — workflow Kestra `03_tests.yml`
4. **Soutenance** — support dans `docs/presentation/`
5. **Revue mentor**

## Chiffres cibles (validés par Stéphane)

| Indicateur | Valeur attendue |
|---|---|
| Systèmes avec fichiers rejetés | 2 |
| Lignes après dédoublonnage | 621 |
| Lignes après nettoyage | 1 428 |
| Lignes ventes | 74 |
| CA total | ≈ 70 000 000 € |
| Références uniques | 3 |
