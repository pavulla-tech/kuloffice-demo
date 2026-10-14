#!/bin/sh
# Idempotently creates/updates the five isolated application roles and databases.
set -eu

export PGPASSWORD="$DB_ROOT_PASSWORD"

ensure_database() {
  role=$1
  password=$2
  psql -X -v ON_ERROR_STOP=1 -h db -U "$POSTGRES_USER" -d postgres \
    --set=role="$role" --set=password="$password" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'role')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'role') \gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'role', :'password') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'role', :'role')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'role') \gexec
SQL
}

ensure_database kuloffice "$KULOFFICE_DB_PASSWORD"
ensure_database keycloak "$KEYCLOAK_DB_PASSWORD"
ensure_database solange "$SOLANGE_DB_PASSWORD"
ensure_database blnk "$BLNK_DB_PASSWORD"
ensure_database gateway "$GATEWAY_DB_PASSWORD"
echo "application databases are ready"
