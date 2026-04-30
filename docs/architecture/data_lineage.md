# Data Lineage — Étape 1

Diagramme à réaliser sous [draw.io](https://draw.io) et à exporter en `.drawio` + `.png`
dans ce dossier.

## À représenter

**Sources** :
- 7 systèmes / ERP
- Formats : CSV, Excel, TXT

**Étapes de traitement** :
1. Extraction
2. Identification premium / ordinary
3. Nettoyage
4. Dédoublonnage
5. Agrégation (CA premium, CA ordinary, CA total)
6. Tests qualité

**Destinations** :
- Tables DuckDB : `clients`, `commandes`, `ventes`
- Rapports CSV/Excel pour Stéphane

