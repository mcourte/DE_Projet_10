-- CA total (tous segments confondus).
-- Cible : ~70 568 EUR sur le dataset BottleNeck.
SELECT
    COALESCE(SUM(price * total_sales), 0) AS ca_total
FROM produits_consolides;
