-- Test de types.
-- Verifie que price et stock_quantity sont bien convertibles en numerique.
-- Retourne le nombre de lignes en erreur de cast.
SELECT
    SUM(
        CASE
            WHEN TRY_CAST(price          AS DECIMAL(10, 2)) IS NULL THEN 1
            WHEN TRY_CAST(stock_quantity AS INTEGER)        IS NULL THEN 1
            ELSE 0
        END
    ) AS nb_erreurs_type
FROM produits_consolides
WHERE price IS NOT NULL OR stock_quantity IS NOT NULL;
