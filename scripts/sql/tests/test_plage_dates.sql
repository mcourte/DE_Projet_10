-- Test de plage de dates.
-- Toutes les post_date renseignees doivent etre entre 2018-01-01 et aujourd'hui.
-- Retourne le nombre de dates hors plage.
SELECT
    COUNT(*) AS nb_dates_hors_plage
FROM produits_consolides
WHERE post_date IS NOT NULL
  AND (post_date < DATE '2018-01-01' OR post_date > CURRENT_TIMESTAMP);
