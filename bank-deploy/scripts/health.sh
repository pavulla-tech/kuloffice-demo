#!/bin/sh
set -eu

compose=${COMPOSE:-docker compose --env-file "${ENV_FILE:-.env}" -f compose.yaml}

failed=0
for service in db blnk-redis blnk-typesense blnk-server gateway keycloak minio kuloffice solange web kulportal; do
  status=$($compose ps --format json "$service" 2>/dev/null | sed -n 's/.*"Health":"\([^"]*\)".*/\1/p' | head -1)
  state=$($compose ps --format json "$service" 2>/dev/null | sed -n 's/.*"State":"\([^"]*\)".*/\1/p' | head -1)
  if [ "$state" = "running" ] && { [ -z "$status" ] || [ "$status" = "healthy" ]; }; then
    printf '%-24s %s\n' "$service" "ok"
  else
    printf '%-24s state=%s health=%s\n' "$service" "${state:-missing}" "${status:-none}"
    failed=1
  fi
done

for service in db-init minio-init solange-migrate gateway-config; do
  code=$($compose ps -a --format json "$service" 2>/dev/null | sed -n 's/.*"ExitCode":\([0-9]*\).*/\1/p' | head -1)
  if [ "$code" = "0" ]; then
    printf '%-24s %s\n' "$service" "completed"
  else
    printf '%-24s exit=%s\n' "$service" "${code:-missing}"
    failed=1
  fi
done

exit "$failed"
