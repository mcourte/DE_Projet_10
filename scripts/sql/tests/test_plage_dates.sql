-- Test de plage de dates.
-- Toutes les post_date renseignees doivent etre entre 2018-01-01 et aujourd'hui.
-- Retourne le nombre de dates hors plage.
SELECT COUNT(*) 
FROM produits_consolides
WHERE post_date < '2018-01-01 00:00:00'::TIMESTAMP 
   OR post_date > NOW()::TIMESTAMP;