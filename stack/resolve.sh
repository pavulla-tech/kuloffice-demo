#!/bin/sh
# Works out what `make up` runs on this laptop and what it uses on the server,
# from KEYCLOAK, KULOFFICE, WEB and FILESERVER (stack.env, or `make up X=…`):
#
#   build     built here from its sibling checkout (the *_DIR settings)
#   v0.1.0-…  that image from Docker Hub (developerspavs/kulpay-*), run here
#   release   the newest v* tag on Docker Hub, run here
#   server    not run here: the deployed one is used (SERVER_* settings)
#
# PRESET=web|kuloffice|backend|local sets all three at once and wins over them.
# PANEL=on also runs the token panel when Keycloak isn't local (it always
# runs with a local Keycloak).
#
# Writes .stack/resolved.env (compose reads it after stack.env) and
# .stack/where.txt (make where), pulls the tagged images, and refuses the
# combinations that cannot work: the server never calls this laptop.
set -eu
mkdir -p .stack
die() { printf 'make up: %s\n' "$*" >&2; exit 1; }
note() { printf '  note: %s\n' "$*"; }

case ${PRESET:-} in
  "") ;;
  web) KEYCLOAK=server KULOFFICE=server WEB=build ;;
  kuloffice) KEYCLOAK=server KULOFFICE=build WEB=build ;;
  backend) KEYCLOAK=server KULOFFICE=build WEB=server ;;
  local) KEYCLOAK=build KULOFFICE=build WEB=build ;;
  *) die "PRESET=$PRESET: web, kuloffice, backend or local" ;;
esac
KEYCLOAK=${KEYCLOAK:-build} KULOFFICE=${KULOFFICE:-build} WEB=${WEB:-build} FILESERVER=${FILESERVER:-build}
STACK_NAME=${STACK_NAME:-kulstack} KC_PORT=${KC_PORT:-8080} KULOFFICE_PORT=${KULOFFICE_PORT:-18080} WEB_PORT=${WEB_PORT:-3000}
SERVER_KEYCLOAK_URL=${SERVER_KEYCLOAK_URL:-https://auth.kulpay.pavulla.com}
SERVER_KULOFFICE_URL=${SERVER_KULOFFICE_URL:-https://core.kulpay.pavulla.com}
SERVER_WEB_URL=${SERVER_WEB_URL:-https://app.kulpay.pavulla.com}
SERVER_REALM=${SERVER_REALM:-kulpay}

for pair in KEYCLOAK=$KEYCLOAK KULOFFICE=$KULOFFICE WEB=$WEB FILESERVER=$FILESERVER; do
  case ${pair#*=} in
    build | server | release | v[0-9]*) ;;
    *) die "$pair: build, server, release, or a tag such as v0.1.0-alpha03" ;;
  esac
done
[ "$FILESERVER" != server ] || die "FILESERVER=server: the server's file server isn't reachable from outside; build it or use a tag"

# The newest v* tag of a Docker Hub repository.
newest() {
  curl -fsS "https://hub.docker.com/v2/repositories/developerspavs/$1/tags?page_size=100" | python3 -c '
import json, re, sys
best = None
for t in json.load(sys.stdin).get("results", []):
    m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+))?", t["name"])
    if m:
        key = (int(m[1]), int(m[2]), int(m[3]), 1 if m[4] is None else 0, m[4] or "")
        best = max(best or (key, t["name"]), (key, t["name"]))
print(best[1] if best else "")' || true
}

# A service's image here: the local build, or a tag from Docker Hub (pulled).
image() { # service mode dir-var
  case $2 in
    build | server) printf '%s-%s:local' "$STACK_NAME" "$1" ;;
    *)
      tag=$2
      if [ "$tag" = release ]; then
        tag=$(newest "kulpay-$1")
        [ -n "$tag" ] || die "no v* tag of developerspavs/kulpay-$1 on Docker Hub"
      fi
      printf 'developerspavs/kulpay-%s:%s' "$1" "$tag"
      ;;
  esac
}
source_of() { # service mode dir
  case $2 in
    build) printf 'build (%s)' "$3" ;;
    server) printf 'server' ;;
    *) printf 'Docker Hub (%s)' "$(image "$1" "$2" | sed 's/.*://')" ;;
  esac
}
local_() { [ "$1" != server ]; }

KEYCLOAK_REF=$(image keycloak "$KEYCLOAK")
KULOFFICE_REF=$(image kuloffice "$KULOFFICE")
WEB_REF=$(image web "$WEB")
FILESERVER_REF=$(image fileserver "$FILESERVER")

# ── what cannot work ──────────────────────────────────────────────────────────
if ! local_ "$KULOFFICE" && local_ "$KEYCLOAK"; then
  die "KULOFFICE=server with a local Keycloak: the server's kuloffice only accepts the server's tokens. Use KEYCLOAK=server too."
fi
if local_ "$KULOFFICE" && ! local_ "$KEYCLOAK"; then
  [ -n "${SERVER_ADMIN_CLIENT_SECRET:-}" ] || die "a local kuloffice with KEYCLOAK=server needs SERVER_ADMIN_CLIENT_SECRET in stack.env (ADMIN_CLIENT_SECRET in the server's deploy/.env)"
  [ -n "${SERVER_WORKFORCE_API_SECRET:-}" ] || die "a local kuloffice with KEYCLOAK=server needs SERVER_WORKFORCE_API_SECRET in stack.env (WORKFORCE_API_SECRET in the server's deploy/.env)"
fi
case $KULOFFICE in
  build | server) ;;
  *) [ -n "${SERVER_LICENSE_KEY:-}" ] || die "a kuloffice image from Docker Hub only takes the official license: set SERVER_LICENSE_KEY in stack.env (KULOFFICE_LICENSE_KEY in the server's deploy/.env)" ;;
esac
for pair in "KEYCLOAK $KEYCLOAK ${INTAKA_DIR:-../keycloak-phone-authenticator}" "KULOFFICE $KULOFFICE ${KULOFFICE_DIR:-../kuloffice}" \
  "WEB $WEB ${WEB_DIR:-../kulpay-web}" "FILESERVER $FILESERVER ${FILESERVER_DIR:-../boquisso-fileserver}"; do
  set -- $pair
  [ "$2" != build ] || [ -d "$3" ] || die "$1=build needs its checkout at $3 (or use a tag)"
done

# ── identity: the local demo realm, or the server's ──────────────────────────
if local_ "$KEYCLOAK"; then
  KC_PUBLIC=http://localhost:$KC_PORT/auth KC_REALM=demo
  KC_BACKEND_CLIENT=demo-backend KC_BACKEND_SECRET=demo-backend-secret
  KC_WORKFORCE_SECRET=${WORKFORCE_API_SECRET:-kuloffice-workforce-secret}
  KC_ADMIN_USER=admin KC_ADMIN_PASSWORD=admin
  SEED_EMAIL=${REVIEWER_EMAIL:-reviewer@kulpay.local}
else
  KC_PUBLIC=$SERVER_KEYCLOAK_URL KC_REALM=$SERVER_REALM
  KC_BACKEND_CLIENT=kulpay-backend KC_BACKEND_SECRET=${SERVER_ADMIN_CLIENT_SECRET:-}
  KC_WORKFORCE_SECRET=${SERVER_WORKFORCE_API_SECRET:-}
  KC_ADMIN_USER=${SERVER_KC_ADMIN_USER:-admin} KC_ADMIN_PASSWORD=${SERVER_KC_ADMIN_PASSWORD:-}
  SEED_EMAIL=${SERVER_REVIEWER_EMAIL:-}
fi
if local_ "$KULOFFICE"; then API_URL=http://localhost:$KULOFFICE_PORT; else API_URL=$SERVER_KULOFFICE_URL; fi
if local_ "$WEB"; then WEB_URL=http://localhost:$WEB_PORT; else WEB_URL=$SERVER_WEB_URL; fi

# A local kuloffice makes a reviewer of the demo user (local Keycloak), or of
# your staff account on the server's (needs its admin password: read only).
SEED=no
if local_ "$KULOFFICE"; then
  if local_ "$KEYCLOAK" || { [ -n "$KC_ADMIN_PASSWORD" ] && [ -n "$SEED_EMAIL" ]; }; then SEED=yes; fi
fi

# QR codes for a local kuloffice, through the server's Solange (optional).
SOLANGE_BASE= SOLANGE_KEY=
if local_ "$KULOFFICE" && [ -n "${SOLANGE_API_KEY:-}" ]; then
  SOLANGE_BASE=${SOLANGE_URL:-https://qr.kulpay.pavulla.com} SOLANGE_KEY=$SOLANGE_API_KEY
fi

# ── profiles: what runs here; what to stop and build ─────────────────────────
profiles="" stop="" build=""
add() { case " $profiles " in *" $2 "*) ;; *) profiles="${profiles:+$profiles }$2" ;; esac; }
# The SMS inbox catches the local Keycloak's codes; the token panel signs in
# to it. Neither runs for the server's Keycloak unless asked (PANEL=on).
if local_ "$KEYCLOAK"; then add _ keycloak; add _ base; add _ inbox; add _ panel; else stop="$stop keycloak realm-setup sms-inbox"; fi
if [ "${PANEL:-}" = on ]; then add _ panel; fi
case " $profiles " in *" panel "*) ;; *) stop="$stop token-panel" ;; esac
if local_ "$KULOFFICE"; then add _ kuloffice; add _ base; else stop="$stop kuloffice bootstrap fileserver minio minio-init"; fi
if local_ "$WEB"; then add _ web; else stop="$stop web"; fi
if [ "$SEED" = yes ]; then add _ seed; else stop="$stop reviewer-seed"; fi
# The review portal needs the local staff realm and kuloffice, and its checkout.
PORTAL=off
if local_ "$KEYCLOAK" && local_ "$KULOFFICE" && [ -d "${PORTAL_DIR:-../kulportal2}" ]; then
  PORTAL=on; add _ portal; build="$build portal"
else
  stop="$stop portal"
fi
case " $profiles " in *" base "*) ;; *) stop="$stop db" ;; esac
[ "$KEYCLOAK" != build ] || build="$build keycloak"
[ "$KULOFFICE" != build ] || build="$build kuloffice"
[ "$WEB" != build ] || build="$build web"
if local_ "$KULOFFICE" && [ "$FILESERVER" = build ]; then build="$build fileserver"; fi
case " $profiles " in *" inbox "*) build="$build sms-inbox" ;; esac

# Tagged images, pulled now so a missing tag stops here.
for ref in "$KEYCLOAK_REF:$KEYCLOAK" "$KULOFFICE_REF:$KULOFFICE" "$WEB_REF:$WEB" "$FILESERVER_REF:$FILESERVER"; do
  mode=${ref##*:}; image=${ref%:*}
  case $mode in build | server) continue ;; esac
  case $image in *fileserver*) local_ "$KULOFFICE" || continue ;; esac
  printf '  pulling %s\n' "$image"
  docker pull -q "$image" > /dev/null || die "could not pull $image (is the tag on Docker Hub?)"
done

if local_ "$KULOFFICE"; then
  case $KULOFFICE in build) BOOTSTRAP_REF=$KULOFFICE_REF LICENSE_KEY= ;; *) BOOTSTRAP_REF=curlimages/curl:8.10.1 LICENSE_KEY=$SERVER_LICENSE_KEY ;; esac
else
  BOOTSTRAP_REF=$KULOFFICE_REF LICENSE_KEY=
fi

cat > .stack/resolved.env << EOF
# Written by stack/resolve.sh on every make up: do not edit.
COMPOSE_PROFILES=$(echo "$profiles" | tr ' ' ',')
STACK_STOP="$(echo $stop)"
STACK_BUILD="$(echo $build)"
STACK_KULOFFICE_LOCAL=$(local_ "$KULOFFICE" && echo yes || echo no)
STACK_SEED=$SEED
KEYCLOAK_REF=$KEYCLOAK_REF
KULOFFICE_REF=$KULOFFICE_REF
WEB_REF=$WEB_REF
FILESERVER_REF=$FILESERVER_REF
BOOTSTRAP_REF=$BOOTSTRAP_REF
KULOFFICE_LICENSE_KEY=$LICENSE_KEY
KC_PUBLIC=$KC_PUBLIC
KC_REALM=$KC_REALM
KC_ISSUER=$KC_PUBLIC/realms/$KC_REALM
KC_WORKFORCE_ISSUER=$KC_PUBLIC/realms/workforce
KC_BACKEND_CLIENT=$KC_BACKEND_CLIENT
KC_BACKEND_SECRET=$KC_BACKEND_SECRET
KC_WORKFORCE_SECRET=$KC_WORKFORCE_SECRET
KC_ADMIN_USER=$KC_ADMIN_USER
KC_ADMIN_PASSWORD=$KC_ADMIN_PASSWORD
SEED_EMAIL=$SEED_EMAIL
API_URL=$API_URL
WEB_URL=$WEB_URL
SOLANGE_BASE=$SOLANGE_BASE
SOLANGE_KEY=$SOLANGE_KEY
EOF
# Ports and the image prefix, so `make up WEB_PORT=…` reaches compose too.
for v in STACK_NAME STACK_BIND KC_PORT KULOFFICE_PORT KULOFFICE_GRPC_PORT WEB_PORT PANEL_PORT SMS_INBOX_PORT \
  FILESERVER_PORT MINIO_PORT MINIO_CONSOLE_PORT DB_PORT; do
  eval "val=\${$v:-}"
  [ -z "$val" ] || printf '%s=%s\n' "$v" "$val" >> .stack/resolved.env
done
chmod 600 .stack/resolved.env

{
  printf '%-10s %-38s %s\n' keycloak "$KC_PUBLIC" "$(source_of keycloak "$KEYCLOAK" "${INTAKA_DIR:-../keycloak-phone-authenticator}")"
  printf '%-10s %-38s %s\n' kuloffice "$API_URL" "$(source_of kuloffice "$KULOFFICE" "${KULOFFICE_DIR:-../kuloffice}")"
  printf '%-10s %-38s %s\n' web "$WEB_URL" "$(source_of web "$WEB" "${WEB_DIR:-../kulpay-web}")"
  if [ "$PORTAL" = on ]; then
    printf '%-10s %-38s %s\n' portal "http://localhost:${PORTAL_PORT:-3100}" "build (${PORTAL_DIR:-../kulportal2})"
  fi
  if local_ "$KULOFFICE"; then
    printf '%-10s %-38s %s\n' fileserver "http://localhost:${FILESERVER_PORT:-8082}" "$(source_of fileserver "$FILESERVER" "${FILESERVER_DIR:-../boquisso-fileserver}")"
    printf '%-10s %-38s %s\n' solange "${SOLANGE_BASE:-off}" "${SOLANGE_BASE:+server (SOLANGE_API_KEY)}"
  fi
} > .stack/where.txt

echo "This run:"
sed 's/^/  /' .stack/where.txt
if local_ "$WEB" && ! local_ "$KULOFFICE"; then note "the web app here works on the SERVER's data: real accounts, real reviews"; fi
if local_ "$KULOFFICE" && ! local_ "$KEYCLOAK"; then
  note "you sign in with your server account; this kuloffice has its own database, so you onboard again here"
  [ "$SEED" = yes ] || note "no reviewer here: set SERVER_KC_ADMIN_PASSWORD and SERVER_REVIEWER_EMAIL to make your staff account one"
fi
if local_ "$KULOFFICE" && [ -n "$SOLANGE_BASE" ]; then note "QR codes through the server's Solange: its scan webhooks can't reach this laptop"; fi
if ! local_ "$WEB" && { local_ "$KULOFFICE" || local_ "$KEYCLOAK"; }; then note "the deployed web app never calls this laptop: call the API here (PANEL=on adds the token panel)"; fi
if local_ "$KULOFFICE" && ! local_ "$KEYCLOAK"; then note "no SMS inbox: this kuloffice's own SMS (approvals) are only logged"; fi
if ! local_ "$KEYCLOAK" && local_ "$WEB"; then note "the server's Keycloak must accept http://localhost:$WEB_PORT (DEV_WEB_ORIGINS on the server, applied by Server → provision)"; fi
