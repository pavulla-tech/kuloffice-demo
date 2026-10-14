#!/bin/sh
set -eu

env_file=${ENV_FILE:-.env}
compose=${COMPOSE:-docker compose --env-file "$env_file" -f compose.yaml}
set -a
# shellcheck disable=SC1090
. "./$env_file"
set +a

mode=${SOLANGE_KULPAY_MODE:-live}
url="${KULOFFICE_PUBLIC_URL:?}/v1/integrations/solange/events"
events=scan.created,conversion.recorded,code.ended,code.exhausted

sol() { $compose exec -T solange solange "$@"; }

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

if ! sol webhook list -app kulpay-app >/dev/null 2>&1; then
  sol app create -slug kulpay-app -name KulPay -prefix k -support "${SOLANGE_SUPPORT:-}"
fi

if [ -z "${KULOFFICE_SOLANGE_API_KEY:-}" ]; then
  key=$(sol key create -app kulpay-app -mode "$mode" -name kuloffice -scopes codes:read,codes:write,scans:read | tail -1)
  case "$key" in sl_*) set_env KULOFFICE_SOLANGE_API_KEY "$key" ;; *) echo "Solange did not return an API key" >&2; exit 1 ;; esac
fi

current=$(sol webhook list -app kulpay-app | awk -v m="$mode" '$2 == m && $3 == "active" { print $1, $4; exit }')
id=${current%% *}
at=${current#* }
secret=""
if [ -n "$current" ] && [ "$at" = "$url" ]; then
  [ -n "${KULOFFICE_SOLANGE_WEBHOOK_SECRETS:-}" ] || secret=$(sol webhook rotate -id "$id" | tail -1)
else
  [ -z "$current" ] || sol webhook disable -id "$id"
  secret=$(sol webhook create -app kulpay-app -mode "$mode" -url "$url" -events "$events" | tail -1)
fi
[ -z "$secret" ] || set_env KULOFFICE_SOLANGE_WEBHOOK_SECRETS "$secret"

$compose up -d --force-recreate kuloffice
echo "KulOffice QR integration is provisioned"
