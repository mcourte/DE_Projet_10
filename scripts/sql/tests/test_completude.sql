-- Test de completude.
-- Aucune ligne ne doit avoir un prix ou un sku NULL apres consolidation.
-- Retourne le nombre de lignes invalides. Doit etre = 0.
SELECT
    COUNT(*) AS nb_lignes_invalides
FROM produits_consolides
WHERE price IS NULL
   OR sku IS NULL
   OR sku = ''
   OR product_id IS NULL;
