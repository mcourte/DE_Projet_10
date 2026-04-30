-- Test de coherence du chiffre d'affaires.
-- Cible : CA total = 70 568.60 EUR.
-- Retourne 0 si CA est dans la tolerance, sinon |ecart| en EUR.

SELECT
    CAST(ABS(COALESCE(SUM(price * total_sales), 0) - 70568.60) AS DECIMAL(10, 2)) AS ecart_ca
FROM produits_consolides;
