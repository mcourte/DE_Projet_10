-- Test de coherence de volumetrie apres les jointures.
-- Cible : 714 lignes dans produits_consolides (= fusion ERP/LIAISON/WEB).
-- Retourne 0 si la volumetrie est correcte, sinon l'ecart.

SELECT
    ABS(COUNT(*) - 714) AS ecart_volumetrie
FROM produits_consolides;
