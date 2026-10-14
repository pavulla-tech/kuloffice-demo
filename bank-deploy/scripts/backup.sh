#!/bin/sh
set -eu

compose=${COMPOSE:-docker compose --env-file "${ENV_FILE:-.env}" -f compose.yaml}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target="backups/$stamp"
mkdir -p "$target"

for database in kuloffice keycloak solange blnk gateway; do
  $compose exec -T db pg_dump -U postgres -Fc "$database" > "$target/$database.dump"
done

$compose --profile maintenance run --rm -T backup-helper -C /source -cf - . > "$target/minio.tar"
sha256sum "$target"/* > "$target/SHA256SUMS"
chmod -R go-rwx "$target"
echo "$target"
