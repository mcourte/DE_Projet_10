-- Creation des tables DuckDB pour BottleNeck.
-- Note : en pratique les tables sont creees dynamiquement par
-- load_to_duckdb.write_table(... mode='replace'). Ce script est conserve
-- a titre documentaire / pour un usage manuel via la CLI duckdb.

-- Table ERP nettoyee
CREATE TABLE IF NOT EXISTS erp_clean (
    product_id      INTEGER,
    onsale_web      INTEGER,
    price           DECIMAL(10, 2),
    stock_quantity  INTEGER,
    stock_status    VARCHAR
);

-- Table WEB nettoyee (filtree post_type=product, post_status=publish)
CREATE TABLE IF NOT EXISTS web_clean (
    sku             VARCHAR,
    post_title      VARCHAR,
    total_sales     DECIMAL(10, 2),
    post_date       TIMESTAMP,
    post_status     VARCHAR,
    post_type       VARCHAR
);

-- Table de liaison
CREATE TABLE IF NOT EXISTS liaison_clean (
    product_id      INTEGER,
    id_web          VARCHAR
);

-- Table consolidee (apres jointures et classification)
CREATE TABLE IF NOT EXISTS produits_consolides (
    product_id          INTEGER,
    id_web              VARCHAR,
    sku                 VARCHAR,
    post_title          VARCHAR,
    price               DECIMAL(10, 2),
    stock_quantity      INTEGER,
    stock_status        VARCHAR,
    total_sales         DECIMAL(10, 2),
    post_date           TIMESTAMP,
    segment             VARCHAR,
    segment_threshold   DECIMAL(10, 2)
);
