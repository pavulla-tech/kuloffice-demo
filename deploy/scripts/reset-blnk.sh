#!/bin/sh
# Rebuild only BLNK's authoritative database, queue and search projection.
# KulOffice/Keycloak/Solange/MinIO data are untouched. A database backup is
# written before the reset and can be restored with `make restore DB=blnk`.
set -eu

[ "${YES:-}" = "DESTROY" ] || {
  echo "This replaces the complete BLNK ledger. Run: make reset-blnk YES=DESTROY" >&2
  exit 1
}

env_file=${ENV_FILE:-.env}
compose() { ENV_FILE="$env_file" docker compose --env-file "$env_file" "$@"; }

say() { printf '%s\n' "$*"; }

volume_for() {
  cid=$(compose ps -aq "$1")
  [ -n "$cid" ] || return 1
  docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' "$cid"
}

say "Stopping every process that can write to BLNK..."
compose stop kuloffice blnk-worker blnk-server blnk-redis blnk-typesense >/dev/null 2>&1 || true
compose up -d db >/dev/null

tries=0
until compose exec -T db pg_isready -U postgres >/dev/null 2>&1; do
  tries=$((tries + 1))
  [ "$tries" -lt 30 ] || { echo "Postgres did not become ready" >&2; exit 1; }
  sleep 1
done

if [ "$(compose exec -T db psql -At -U postgres -d postgres -c "SELECT 1 FROM pg_database WHERE datname = 'blnk'")" = "1" ]; then
  backup="state/backups/blnk/$(date -u +%Y%m%d-%H%M%S)-before-reset.sql.gz"
  mkdir -p "$(dirname "$backup")"
  say "Saving the current BLNK database to $backup..."
  compose exec -T db pg_dump -U postgres -d blnk | gzip > "$backup.part"
  mv "$backup.part" "$backup"
  compose exec -T db dropdb --force -U postgres blnk
else
  backup=""
fi

redis_volume=$(volume_for blnk-redis || true)
typesense_volume=$(volume_for blnk-typesense || true)
compose rm -f blnk-redis blnk-typesense >/dev/null 2>&1 || true

for volume in "$redis_volume" "$typesense_volume"; do
  [ -z "$volume" ] && continue
  case "$volume" in
    *_blnk-redis-data|*_blnk-typesense-data) docker volume rm "$volume" >/dev/null ;;
    *) echo "Refusing unexpected volume $volume" >&2; exit 1 ;;
  esac
done

say "Creating a clean BLNK database and applying the pinned schema..."
compose run --rm blnk-db-init >/dev/null
compose up -d blnk-server blnk-worker >/dev/null

tries=0
until compose exec -T blnk-server sh -ec 'wget -q --header="X-Blnk-Key: $BLNK_SERVER_SECRET_KEY" --spider http://127.0.0.1:5001/' >/dev/null 2>&1; do
  tries=$((tries + 1))
  if [ "$tries" -ge 60 ]; then
    compose logs --tail=100 blnk-server blnk-worker >&2
    echo "BLNK did not become ready. The prior database backup is: ${backup:-none (no prior database)}" >&2
    exit 1
  fi
  sleep 2
done

say "Starting KulOffice; its bootstrap will create and verify the approved zero-balance topology..."
compose up -d --force-recreate kuloffice >/dev/null
say "BLNK reset complete. Prior database backup: ${backup:-none (this was the first installation)}"
