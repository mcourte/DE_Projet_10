-- Test STRUCTUREL de la classification Z-score (reutilisable chaque mois).
--
-- Verifie 3 invariants :
--   1. Chaque vin 'premium'  a un prix > seuil z-score (mean + 1.96*std).
--   2. Chaque vin 'ordinary' a un prix <= seuil.
--   3. Les 2 segments sont non vides (sinon classification degeneree).
--
-- Retourne 0 si OK, sinon un code > 0.
--
-- Volumes POC initiaux (cf. test_chiffres_bottleneck.py) :
--   30 vins millesimes / 684 vins ordinaires.

WITH stats AS (
    SELECT
        AVG(price) + 1.96 * stddev_samp(price) AS seuil_z
    FROM produits_consolides
    WHERE price IS NOT NULL
),
violations AS (
    SELECT COUNT(*) AS nb
    FROM produits_consolides p, stats s
    WHERE
        (p.segment = 'premium'  AND p.price <= s.seuil_z)   -- mal classe en premium
        OR
        (p.segment = 'ordinary' AND p.price >  s.seuil_z)   -- mal classe en ordinary
),
volumetrie AS (
    SELECT
        COUNT(*) FILTER (WHERE segment = 'premium')  AS nb_premium,
        COUNT(*) FILTER (WHERE segment = 'ordinary') AS nb_ordinary
    FROM produits_consolides
)
SELECT
    CASE
        WHEN v.nb > 0                                    THEN 1   -- regle Z-score violee
        WHEN vol.nb_premium = 0 OR vol.nb_ordinary = 0   THEN 2   -- segment vide
        ELSE 0
    END AS nb_violations
FROM violations v, volumetrie vol;
