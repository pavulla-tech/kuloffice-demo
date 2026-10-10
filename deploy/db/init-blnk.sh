#!/bin/sh
# Idempotently prepares BLNK even when this compose stack already has a
# Postgres volume and docker-entrypoint-initdb.d will not run again.
set -eu
# The password goes in as a psql variable on stdin: psql interpolates :'var'
# only in input it reads, never in -c.

export PGPASSWORD="$DB_ROOT_PASSWORD"

if ! psql -At -h db -U "$POSTGRES_USER" -d postgres -c "SELECT 1 FROM pg_roles WHERE rolname = 'blnk'" | grep -q 1; then
  echo "CREATE ROLE blnk LOGIN PASSWORD :'blnk_password'" |
    psql -v ON_ERROR_STOP=1 -h db -U "$POSTGRES_USER" -d postgres --set=blnk_password="$BLNK_DB_PASSWORD"
else
  echo "ALTER ROLE blnk WITH LOGIN PASSWORD :'blnk_password'" |
    psql -v ON_ERROR_STOP=1 -h db -U "$POSTGRES_USER" -d postgres --set=blnk_password="$BLNK_DB_PASSWORD"
fi

if ! psql -At -h db -U "$POSTGRES_USER" -d postgres -c "SELECT 1 FROM pg_database WHERE datname = 'blnk'" | grep -q 1; then
  psql -v ON_ERROR_STOP=1 -h db -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE blnk OWNER blnk"
fi
