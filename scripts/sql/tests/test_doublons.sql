-- Test de doublons.
-- Verifie qu'il n'y a aucun doublon sur les cles primaires des tables.
-- Retourne le nombre de doublons. Doit etre = 0.

SELECT
    SUM(nb_doublons) AS nb_doublons_total
FROM (
    -- Doublons sur sku dans produits_consolides
    SELECT COUNT(*) - COUNT(DISTINCT sku) AS nb_doublons
    FROM produits_consolides
    UNION ALL
    -- Doublons sur product_id dans erp_clean
    SELECT COUNT(*) - COUNT(DISTINCT product_id) AS nb_doublons
    FROM erp_clean
    UNION ALL
    -- Doublons sur product_id dans liaison_clean
    SELECT COUNT(*) - COUNT(DISTINCT product_id) AS nb_doublons
    FROM liaison_clean
    UNION ALL
    -- Doublons sur sku dans web_clean
    SELECT COUNT(*) - COUNT(DISTINCT sku) AS nb_doublons
    FROM web_clean
);
