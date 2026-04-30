-- Test de coherence du z-score sur la classification millesimes / ordinaires.
--
-- Verifie 2 invariants :
--   1. Tous les vins classes 'premium' ont un prix > seuil z-score (mean + 1.96*std)
--   2. Tous les vins classes 'ordinary'  ont un prix <= seuil
--
-- Retourne le nombre de violations. Doit etre = 0.
--
-- Cible attendue par Stephane :
--   30 vins millesimes / 684 vins ordinaires.

WITH stats AS (
    SELECT
        AVG(price)                      AS mean_price,
        stddev_samp(price)              AS std_price,
        AVG(price) + 1.96 * stddev_samp(price) AS seuil_z
    FROM produits_consolides
    WHERE price IS NOT NULL
),
violations AS (
    SELECT COUNT(*) AS nb
    FROM produits_consolides p, stats s
    WHERE
        -- Cas 1 : vin marque premium mais prix <= seuil
        (p.segment = 'premium'  AND p.price <= s.seuil_z)
        OR
        -- Cas 2 : vin marque ordinary mais prix > seuil
        (p.segment = 'ordinary' AND p.price >  s.seuil_z)
),
volumetrie AS (
    SELECT
        COUNT(*) FILTER (WHERE segment = 'premium')  AS nb_millesimes,
        COUNT(*) FILTER (WHERE segment = 'ordinary') AS nb_ordinaires
    FROM produits_consolides
)
SELECT
    v.nb
    -- on inclut volumetrie pour debug : si la classification est mauvaise on le voit
    + CASE WHEN vol.nb_millesimes <> 30  THEN 100 ELSE 0 END
    + CASE WHEN vol.nb_ordinaires <> 684 THEN 100 ELSE 0 END
    AS nb_violations
FROM violations v, volumetrie vol;
