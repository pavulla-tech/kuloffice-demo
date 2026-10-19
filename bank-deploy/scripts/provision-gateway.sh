#!/bin/sh
set -eu

env_file=${ENV_FILE:-.env}
compose=${COMPOSE:-docker compose --env-file "$env_file" -f compose.yaml}

set_env() {
  tmp=$(mktemp)
  if grep -q "^$1=" "$env_file"; then
    awk -v k="$1" -v v="$2" 'index($0, k"=") == 1 { print k"="v; next } { print }' "$env_file" > "$tmp"
  else
    sed -n '1,$p' "$env_file" > "$tmp"
    printf '%s=%s\n' "$1" "$2" >> "$tmp"
  fi
  sed -n '1,$p' "$tmp" > "$env_file"
  rm -f "$tmp"
}

result=$($compose --profile provisioning run --rm --entrypoint python3 provisioner /tools/gateway_kuloffice.py)
if [ -n "$result" ]; then
  printf '%s\n' "$result" | while IFS='=' read -r key value; do
    case "$key" in
      KULOFFICE_INCOMING_TRANSFERS_WEBHOOK_SECRETS|KULOFFICE_PAYMENT_ACCEPTANCE_WEBHOOK_SECRETS)
        [ -n "$value" ] || { echo "$key was empty" >&2; exit 1; }
        set_env "$key" "$value"
        ;;
      *) echo "unexpected Gateway provisioning output" >&2; exit 1 ;;
    esac
  done
fi

$compose up -d --force-recreate kuloffice
echo "signed Gateway event delivery is provisioned"
