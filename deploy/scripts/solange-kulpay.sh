#!/bin/sh
# KulPay in Solange, idempotently:
#   1. the app kulpay-app (printed codes are https://<qr>/k/<code>);
#   2. kuloffice's key, unless .env already has one;
#   3. the webhook to kuloffice's public URL, unless it is already there with
#      its secret in .env (the URL changed: the old endpoint is disabled).
# Secrets are written into .env, never printed; kuloffice is then recreated.
set -eu
env_file=${ENV_FILE:-.env}
COMPOSE=${COMPOSE:-docker compose --env-file $env_file}
# shellcheck disable=SC1090
set -a; . "./$env_file"; set +a
mode=${SOLANGE_KULPAY_MODE:-live}
url="${KULOFFICE_PUBLIC_URL:?}/v1/integrations/solange/events"
events=scan.created,conversion.recorded,code.ended,code.exhausted

sol() { $COMPOSE exec -T solange solange "$@"; }

# KEY=value into .env: replaced if present, appended otherwise.
set_env() {
  tmp=$(mktemp)
  if grep -q "^$1=" "$env_file"; then
    awk -v k="$1" -v v="$2" 'index($0, k"=") == 1 { print k"="v; next } { print }' "$env_file" > "$tmp"
  else
    cat "$env_file" > "$tmp"; printf '%s=%s\n' "$1" "$2" >> "$tmp"
  fi
  cat "$tmp" > "$env_file"; rm -f "$tmp"
}

if sol webhook list -app kulpay-app >/dev/null 2>&1; then
  echo "app kulpay-app: already there"
else
  sol app create -slug kulpay-app -name KulPay -prefix k -support "${SOLANGE_SUPPORT:-}"
fi

if [ -n "${KULOFFICE_SOLANGE_API_KEY:-}" ]; then
  echo "kuloffice's key: already in $env_file (clear it to issue another)"
else
  key=$(sol key create -app kulpay-app -mode "$mode" -name kuloffice -scopes codes:read,codes:write,scans:read | tail -1)
  case $key in sl_*) ;; *) echo "no key in Solange's answer" >&2; exit 1 ;; esac
  set_env KULOFFICE_SOLANGE_API_KEY "$key"
  echo "kuloffice's key: issued ($mode), written to $env_file"
fi

current=$(sol webhook list -app kulpay-app | awk -v m="$mode" '$2 == m && $3 == "active" { print $1, $4 }')
id=${current%% *}; at=${current#* }
secret=""
if [ -n "$current" ] && [ "$at" = "$url" ]; then
  if [ -n "${KULOFFICE_SOLANGE_WEBHOOK_SECRETS:-}" ]; then
    echo "webhook: already sending to $url"
  else
    secret=$(sol webhook rotate -id "$id" | tail -1)
  fi
else
  [ -z "$current" ] || sol webhook disable -id "$id"
  secret=$(sol webhook create -app kulpay-app -mode "$mode" -url "$url" -events "$events" | tail -1)
  echo "webhook: sending to $url"
fi
if [ -n "$secret" ]; then
  set_env KULOFFICE_SOLANGE_WEBHOOK_SECRETS "$secret"
  echo "webhook secret: written to $env_file"
fi

$COMPOSE up -d --force-recreate kuloffice
echo "kuloffice recreated with QR codes on"
