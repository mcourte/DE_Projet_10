-- Test STRUCTUREL du chiffre d'affaires (reutilisable chaque mois).
--
-- Verifie 2 invariants :
--   1. Le CA total est strictement positif (sinon donnees absurdes).
--   2. Somme des CA par segment = CA total (coherence comptable, tolerance 0.01 EUR).
--
-- Retourne 0 si OK, sinon un code > 0.
--
-- CA POC initial (cf. test_chiffres_bottleneck.py) : 70 568,60 EUR.

WITH agreg AS (
    SELECT
        COALESCE(SUM(CASE WHEN segment = 'premium'  THEN price * total_sales END), 0) AS ca_premium,
        COALESCE(SUM(CASE WHEN segment = 'ordinary' THEN price * total_sales END), 0) AS ca_ordinary,
        COALESCE(SUM(price * total_sales), 0)                                         AS ca_total
    FROM produits_consolides
)
SELECT
    CASE
        WHEN ca_total <= 0                                     THEN 1   -- CA nul ou negatif
        WHEN ABS((ca_premium + ca_ordinary) - ca_total) > 0.01 THEN 2   -- incoherence comptable
        ELSE 0
    END AS nb_violations
FROM agreg;
