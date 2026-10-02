#!/bin/sh
# Each service's role and database, on Postgres's first start only (an empty
# data volume). Passwords come from the container's environment (.env).
set -eu
for svc in kuloffice keycloak solange; do
  pw=$(eval "printf %s \"\${$(echo "$svc" | tr a-z A-Z)_DB_PASSWORD}\"")
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -c "CREATE ROLE $svc LOGIN PASSWORD '$pw'"
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -c "CREATE DATABASE $svc OWNER $svc"
done
