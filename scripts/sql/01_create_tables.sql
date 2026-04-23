-- Creation des tables cibles dans DuckDB.

-- Table clients (consolidee premium + ordinary)
CREATE TABLE IF NOT EXISTS clients (
    client_id    VARCHAR PRIMARY KEY,
    nom          VARCHAR,
    email        VARCHAR,
    segment      VARCHAR CHECK (segment IN ('premium', 'ordinary'))
    -- TODO : completer selon les fichiers sources
);

-- Table commandes
CREATE TABLE IF NOT EXISTS commandes (
    commande_id  VARCHAR PRIMARY KEY,
    client_id    VARCHAR REFERENCES clients(client_id),
    date_cmd     DATE,
    montant      DECIMAL(12, 2)
    -- TODO
);

-- Table ventes / produits
CREATE TABLE IF NOT EXISTS ventes (
    vente_id     VARCHAR PRIMARY KEY,
    reference    VARCHAR,
    quantite     INTEGER,
    prix_unit    DECIMAL(10, 2)
    -- TODO
);
