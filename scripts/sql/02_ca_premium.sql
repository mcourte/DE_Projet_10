-- CA des vins premium (somme price * total_sales).
SELECT
    COALESCE(SUM(price * total_sales), 0) AS ca_premium
FROM produits_consolides
WHERE segment = 'premium';
