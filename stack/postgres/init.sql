-- Keycloak's database, beside kuloffice's. Runs on the volume's first start only.
CREATE USER keycloak WITH PASSWORD 'keycloak';
CREATE DATABASE keycloak OWNER keycloak;
