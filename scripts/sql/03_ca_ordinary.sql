-- CA des vins ordinaires (somme price * total_sales).
SELECT
    COALESCE(SUM(price * total_sales), 0) AS ca_ordinary
FROM produits_consolides
WHERE segment = 'ordinary';
