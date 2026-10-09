#!/bin/sh
# Reset a BLNK that this kit does not run (an existing install on another
# host), for the approved fresh KulPay topology. Run it ON that host. It:
#   1. stops the BLNK server and worker, so nothing writes meanwhile;
#   2. backs up BLNK's database (gzip SQL) before touching it;
#   3. drops and recreates that database, empty;
#   4. empties BLNK's Redis queue, so no old queued transaction replays;
#   5. starts BLNK again, applies its schema and checks it answers.
# KulOffice then creates the topology on its next start (BLNK bootstrap).
# Typesense (search) is left alone: it is a projection BLNK can re-index;
# recreate its volume separately if old search results must disappear.
# For a BLNK run by this kit's deploy compose, use reset-blnk.sh instead.
#
# Usage (names are this host's docker containers; check `docker ps`):
#   YES=DESTROY \
#   BLNK_DB_CONTAINER=blnk-postgres BLNK_DB_NAME=blnk BLNK_DB_USER=postgres \
#   BLNK_SERVER_CONTAINER=blnk-server BLNK_WORKER_CONTAINER=blnk-worker \
#   BLNK_REDIS_CONTAINER=blnk-redis \
#   sh reset-standalone-blnk.sh
set -eu

die() { echo "reset-standalone-blnk: $*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }

[ "${YES:-}" = "DESTROY" ] || die "this replaces the complete BLNK ledger; run with YES=DESTROY"
: "${BLNK_DB_CONTAINER:?name the Postgres container holding the BLNK database}"
: "${BLNK_DB_NAME:?name the BLNK database}"
: "${BLNK_DB_USER:?name a Postgres user that may drop and create it}"
: "${BLNK_SERVER_CONTAINER:?name the BLNK server container}"
: "${BLNK_REDIS_CONTAINER:?name the Redis container BLNK queues on (it must be dedicated to BLNK)}"
BLNK_WORKER_CONTAINER=${BLNK_WORKER_CONTAINER:-}
BLNK_PORT=${BLNK_PORT:-5001}
BACKUP_DIR=${BACKUP_DIR:-./blnk-backups}

for c in "$BLNK_DB_CONTAINER" "$BLNK_SERVER_CONTAINER" "$BLNK_REDIS_CONTAINER" $BLNK_WORKER_CONTAINER; do
  docker inspect "$c" >/dev/null 2>&1 || die "no container named $c"
done
case "$BLNK_DB_NAME" in
  postgres|template0|template1) die "refusing to drop the system database $BLNK_DB_NAME" ;;
esac
psql() { docker exec -i "$BLNK_DB_CONTAINER" psql -v ON_ERROR_STOP=1 -At -U "$BLNK_DB_USER" "$@"; }
[ "$(psql -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$BLNK_DB_NAME'")" = "1" ] ||
  die "database $BLNK_DB_NAME does not exist in $BLNK_DB_CONTAINER"
owner=$(psql -d postgres -c "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = '$BLNK_DB_NAME'")

say "Stopping BLNK so nothing writes during the reset..."
docker stop $BLNK_WORKER_CONTAINER "$BLNK_SERVER_CONTAINER" >/dev/null

mkdir -p "$BACKUP_DIR"
backup="$BACKUP_DIR/$BLNK_DB_NAME-$(date -u +%Y%m%d-%H%M%S)-before-reset.sql.gz"
say "Backing up $BLNK_DB_NAME to $backup..."
docker exec "$BLNK_DB_CONTAINER" pg_dump -U "$BLNK_DB_USER" -d "$BLNK_DB_NAME" | gzip > "$backup.part"
gzip -t "$backup.part" || die "the backup is not readable; nothing was dropped"
mv "$backup.part" "$backup"

say "Recreating $BLNK_DB_NAME empty (owner $owner)..."
psql -d postgres -c "DROP DATABASE \"$BLNK_DB_NAME\" WITH (FORCE)" >/dev/null
psql -d postgres -c "CREATE DATABASE \"$BLNK_DB_NAME\" OWNER \"$owner\"" >/dev/null

say "Emptying BLNK's Redis queue..."
docker exec "$BLNK_REDIS_CONTAINER" redis-cli FLUSHALL >/dev/null

say "Starting BLNK and applying its schema..."
docker start "$BLNK_SERVER_CONTAINER" >/dev/null
docker exec "$BLNK_SERVER_CONTAINER" blnk migrate up >/dev/null 2>&1 ||
  say "(blnk migrate up was not available or already applied; the server applies its schema on start)"
[ -n "$BLNK_WORKER_CONTAINER" ] && docker start "$BLNK_WORKER_CONTAINER" >/dev/null

tries=0
until curl -fsS "http://127.0.0.1:$BLNK_PORT/" >/dev/null 2>&1; do
  tries=$((tries + 1))
  [ "$tries" -lt 60 ] || die "BLNK did not answer on port $BLNK_PORT; the backup is $backup (restore: gunzip -c $backup | docker exec -i $BLNK_DB_CONTAINER psql -U $BLNK_DB_USER -d $BLNK_DB_NAME)"
  sleep 2
done
say "BLNK reset complete and answering on port $BLNK_PORT."
say "Backup of the old ledger: $backup"
say "Next: start KulOffice with BLNK bootstrap enabled; it creates the zero-balance KulPay topology."
