#!/bin/sh
# Provision the two signed Gateway event feeds KulOffice consumes.  Secrets
# returned once by the Gateway are captured into the ignored .env and never
# printed. The Keycloak service client itself is provisioned by tools/init.sh.
set -eu

env_file=${ENV_FILE:-.env}
COMPOSE=${COMPOSE:-docker compose --env-file "$env_file"}

set_env() {
  tmp=$(mktemp)
  if grep -q "^$1=" "$env_file"; then
    awk -v k="$1" -v v="$2" 'index($0, k"=") == 1 { print k"="v; next } { print }' "$env_file" > "$tmp"
  else
    cat "$env_file" > "$tmp"
    printf '%s=%s\n' "$1" "$2" >> "$tmp"
  fi
  cat "$tmp" > "$env_file"
  rm -f "$tmp"
}

# The tools image's entrypoint is sh, so python3 is the entrypoint here.
result=$($COMPOSE --profile tools run --rm --entrypoint python3 tools /tools/gateway_kuloffice.py)
if [ -n "$result" ]; then
  printf '%s\n' "$result" | while IFS='=' read -r key value; do
    case "$key" in
      KULOFFICE_INCOMING_TRANSFERS_WEBHOOK_SECRETS|KULOFFICE_PAYMENT_ACCEPTANCE_WEBHOOK_SECRETS)
        [ -n "$value" ] || { echo "$key was empty" >&2; exit 1; }
        set_env "$key" "$value"
        ;;
      *) echo "unexpected provisioning output" >&2; exit 1 ;;
    esac
  done
  echo "Gateway signing secrets written to $env_file"
fi

$COMPOSE up -d --force-recreate kuloffice
echo "KulOffice recreated with the Gateway integration environment"
