#!/bin/sh
# Makes a fresh kuloffice usable: activates a license and registers Keycloak as
# its identity provider. Each step is skipped when already done, so this is
# safe to run on every `make up`. Runs in the kuloffice image (kuloffice-license
# and curl), in the stack's shared network namespace.
set -eu

auth="$KULOFFICE_ADMIN_EMAIL:$KULOFFICE_ADMIN_PASSWORD"
api="$KULOFFICE_URL"

status() { curl -s -o /dev/null -w '%{http_code}' -u "$auth" "$@"; }

printf 'waiting for kuloffice at %s' "$api"
i=0
until [ "$(status "$api/v1/license")" != "000" ]; do
  i=$((i + 1))
  [ "$i" -lt 120 ] || { echo; echo "kuloffice never answered" >&2; exit 1; }
  printf '.'; sleep 1
done
echo

# The license middleware refuses everything else until one is active, so this
# goes first. It is signed with the key whose public half the image was built
# with (make keys).
if [ "$(status "$api/v1/license")" = "200" ]; then
  echo "license: already active"
else
  key=$(kuloffice-license generate --issuer="$LICENSE_ISSUER" --priv-key=/keys/private.pem \
    --issued-to=kuloffice-demo --valid-days=365 --features=basic)
  curl -fsS -u "$auth" -H 'Content-Type: application/json' -X POST "$api/v1/license/activate" \
    -d "{\"license_key\":\"$key\"}" >/dev/null
  echo "license: activated"
fi

# kuloffice finds a token's provider by an exact match on its issuer.
if curl -fsS -u "$auth" "$api/v1/system/identity-providers" | grep -qF "\"$IDP_ISSUER_URL\""; then
  echo "identity provider: $IDP_ISSUER_URL already registered"
else
  curl -fsS -u "$auth" -H 'Content-Type: application/json' -X POST "$api/v1/system/identity-providers" \
    -d "{\"name\":\"keycloak\",\"type\":\"oidc\",\"oidc\":{\"issuer_url\":\"$IDP_ISSUER_URL\",\"client_id\":\"$IDP_CLIENT_ID\",\"client_secret\":\"$IDP_CLIENT_SECRET\"}}" >/dev/null
  echo "identity provider: registered $IDP_ISSUER_URL"
fi

# Staff sign in to their own realm; kuloffice knows it as a second provider.
if curl -fsS -u "$auth" "$api/v1/system/identity-providers" | grep -qF "\"$WORKFORCE_ISSUER_URL\""; then
  echo "identity provider: $WORKFORCE_ISSUER_URL already registered"
else
  curl -fsS -u "$auth" -H 'Content-Type: application/json' -X POST "$api/v1/system/identity-providers" \
    -d "{\"name\":\"keycloak-workforce\",\"type\":\"oidc\",\"oidc\":{\"issuer_url\":\"$WORKFORCE_ISSUER_URL\",\"client_id\":\"$WORKFORCE_CLIENT_ID\",\"client_secret\":\"$WORKFORCE_CLIENT_SECRET\"}}" >/dev/null
  echo "identity provider: registered $WORKFORCE_ISSUER_URL"
fi
