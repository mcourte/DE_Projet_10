-- Test STRUCTUREL de la jointure (reutilisable chaque mois).
--
-- Verifie 2 invariants :
--   1. La table produits_consolides est non vide.
--   2. Chaque sku y est unique (= COUNT(DISTINCT sku) = COUNT(*)).
--
-- Retourne 0 si les deux invariants sont OK, sinon un code > 0.
--
-- Volume POC initial (cf. test_chiffres_bottleneck.py) : 714 lignes.

SELECT
    CASE
        WHEN COUNT(*) = 0                    THEN 1   -- table vide
        WHEN COUNT(*) <> COUNT(DISTINCT sku) THEN 2   -- doublons sku
        ELSE 0
    END AS nb_violations
FROM produits_consolides;
