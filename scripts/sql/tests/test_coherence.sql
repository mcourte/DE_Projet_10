-- Test de coherence.
-- CA_premium + CA_ordinary doit etre egal au CA_total.
-- Retourne l'ecart (devrait etre proche de 0).
WITH agg AS (
    SELECT
        COALESCE(SUM(CASE WHEN segment = 'premium'  THEN price * total_sales END), 0) AS ca_premium,
        COALESCE(SUM(CASE WHEN segment = 'ordinary' THEN price * total_sales END), 0) AS ca_ordinary,
        COALESCE(SUM(price * total_sales), 0)                                          AS ca_total
    FROM produits_consolides
)
SELECT
    ROUND(ca_total - (ca_premium + ca_ordinary), 4) AS ecart
FROM agg;
