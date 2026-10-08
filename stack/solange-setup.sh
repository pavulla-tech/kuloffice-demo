#!/bin/sh
# KulPay in the local Solange, idempotently (as deploy/scripts/solange-kulpay.sh
# does on the server, in test mode so the webhook may be plain http):
#   1. the app kulpay-app;
#   2. kuloffice's key, unless .stack/solange.env has one;
#   3. the webhook to this kuloffice, unless one is active there.
# Writes .stack/solange.env (gitignored) and recreates kuloffice when it changed.
set -eu
: "${KULOFFICE_PORT:?}" "${STACK_NAME:?}"
# The Makefile's compose command, with the licence key kuloffice is started with.
LICENSE_PUBLIC_KEY=$(cat .stack/keys/public.pem.base64 2>/dev/null || true); export LICENSE_PUBLIC_KEY
COMPOSE="docker compose -p $STACK_NAME -f docker-compose.yml --env-file stack.env --env-file .stack/resolved.env"
out=.stack/solange.env
url="http://localhost:${KULOFFICE_PORT}/v1/integrations/solange/events"
events=scan.created,conversion.recorded,code.ended,code.exhausted
sol() { $COMPOSE exec -T solange solange "$@"; }

i=0
until curl -fsS "http://localhost:${SOLANGE_PORT:-8094}/healthz" >/dev/null 2>&1; do
  i=$((i + 1)); [ $i -lt 60 ] || { echo "Solange didn't come up (make logs S=solange)" >&2; exit 1; }
  sleep 1
done

key=$(sed -n 's/^SOLANGE_KEY=//p' "$out" 2>/dev/null || true)
secret=$(sed -n 's/^SOLANGE_WEBHOOK_SECRETS=//p' "$out" 2>/dev/null || true)
changed=no

if sol webhook list -app kulpay-app >/dev/null 2>&1; then :; else
  sol app create -slug kulpay-app -name KulPay -prefix k -support "" >/dev/null
  echo "solange: app kulpay-app created"
fi
if [ -z "$key" ]; then
  key=$(sol key create -app kulpay-app -mode test -name kuloffice -scopes codes:read,codes:write,scans:read | tail -1)
  case $key in sl_*) ;; *) echo "solange: no key in its answer" >&2; exit 1 ;; esac
  changed=yes; echo "solange: kuloffice's key issued (test)"
fi
active=$(sol webhook list -app kulpay-app | awk -v u="$url" '$2 == "test" && $3 == "active" && $4 == u { print $1 }' | head -1)
if [ -z "$active" ] || [ -z "$secret" ]; then
  [ -z "$active" ] || sol webhook disable -id "$active" >/dev/null
  secret=$(sol webhook create -app kulpay-app -mode test -url "$url" -events "$events" | tail -1)
  changed=yes; echo "solange: webhook to $url"
fi
umask 077
printf 'SOLANGE_KEY=%s\nSOLANGE_WEBHOOK_SECRETS=%s\n' "$key" "$secret" > "$out"
# This run's resolved settings too, so a make rebuild before the next make up
# keeps the key (resolve.sh reads .stack/solange.env from then on).
tmp=$(mktemp)
grep -v '^SOLANGE_KEY=\|^SOLANGE_WEBHOOK_SECRETS=' .stack/resolved.env > "$tmp" || true
printf 'SOLANGE_KEY=%s\nSOLANGE_WEBHOOK_SECRETS=%s\n' "$key" "$secret" >> "$tmp"
cat "$tmp" > .stack/resolved.env; rm -f "$tmp"

if [ "$changed" = yes ] || [ "${SOLANGE_KEY:-}" != "$key" ]; then
  SOLANGE_KEY=$key SOLANGE_WEBHOOK_SECRETS=$secret $COMPOSE up -d --no-deps --force-recreate kuloffice >/dev/null 2>&1
  echo "solange: kuloffice recreated with QR codes on"
else
  echo "solange: ready"
fi
