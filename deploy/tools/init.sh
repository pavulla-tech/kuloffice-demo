#!/bin/sh
# Provisions the stack, every step idempotent (`make init` runs this in the
# tools image, on the stack's network):
#   1. the customer realm: flows, the web/passkey/mobile/panel/USSD clients
#   2. the workforce realm (staff), with kuloffice's and the console's clients
#   3. kuloffice: the license and both identity providers
# An existing realm is left alone, except for the additions the update scripts
# bring; FORCE_RESET=true rebuilds it (and invalidates every token).
set -eu

: "${KEYCLOAK_PUBLIC_URL:?}" "${KC_ADMIN_PASSWORD:?}" "${ADMIN_CLIENT_SECRET:?}"

# The names intaka's setup scripts read.
export KC_BOOTSTRAP_ADMIN_USERNAME="${KC_ADMIN_USER:-admin}" KC_BOOTSTRAP_ADMIN_PASSWORD="$KC_ADMIN_PASSWORD"
export REALM="${REALM:-kulpay}" ADMIN_CLIENT_ID="${ADMIN_CLIENT_ID:-kulpay-backend}"
export API_AUDIENCE="$ADMIN_CLIENT_ID"
export WEB_CLIENT_ID="${WEB_CLIENT_ID:-kulpay-web}" PASSKEY_CLIENT_ID="${PASSKEY_CLIENT_ID:-kulpay-web-passkey}"
export MOBILE_CLIENT_ID="${MOBILE_CLIENT_ID:-kulpay-mobile}"
# intaka's demo page client; its redirect is never used here.
export APP_CLIENT_ID="${DEMO_APP_CLIENT_ID:-kulpay-demo-app}" PUBLIC_BASE_URL="${KULOFFICE_PUBLIC_URL:?}"
export WEB_BASE_URL="${WEB_PUBLIC_URL:?}"
export SSL_REQUIRED="${SSL_REQUIRED:-external}" BRUTE_FORCE_PROTECTED="${BRUTE_FORCE_PROTECTED:-true}"
# The extension's own limits, not the demo's generous ones.
export PHONE_BUDGET="${PHONE_BUDGET:-3}" IP_BUDGET="${IP_BUDGET:-10}" LOOKUP_BUDGET="${LOOKUP_BUDGET:-30}"
export DEBUG="${INIT_DEBUG:-false}"
# The token panel finishes its sign-in on the server, at its own localhost.
export PANEL_ORIGIN="http://localhost:8765"

echo "== realm '$REALM' on $KEYCLOAK_URL (public $KEYCLOAK_PUBLIC_URL)"
python3 /setup/configure_realm.py
python3 /setup/add_token_panel_client.py
python3 /setup/add_ussd_client.py
python3 /setup/update_existing_realm.py
# Web apps on developers' laptops (the local stack's KEYCLOAK=server); unset
# means the local stack's web app, set empty means none.
DEV_WEB_ORIGINS="${DEV_WEB_ORIGINS-http://localhost:3000}" python3 /tools/dev_origins.py

echo "== workforce realm '${WORKFORCE_REALM:-workforce}'"
# No demo reviewer: staff are added with `make operator`.
REVIEWER_EMAIL= API_CLIENT_SECRET="${WORKFORCE_API_SECRET:?}" python3 /setup/add_workforce_realm.py
python3 /tools/solange_console_client.py
# The review portal's client, once bin/kulpay has made its secret.
if [ -n "${KULPORTAL_CLIENT_SECRET:-}" ]; then
  PORTAL_URL="${KULPORTAL_PUBLIC_URL:?}" PORTAL_CLIENT_SECRET="$KULPORTAL_CLIENT_SECRET" python3 /stack/add_portal_client.py
fi

echo "== kuloffice"
KULOFFICE_LICENSE_KEY="${KULOFFICE_LICENSE_KEY:?}" \
IDP_ISSUER_URL="$KEYCLOAK_PUBLIC_URL/realms/$REALM" IDP_CLIENT_ID="$ADMIN_CLIENT_ID" IDP_CLIENT_SECRET="$ADMIN_CLIENT_SECRET" \
WORKFORCE_ISSUER_URL="$KEYCLOAK_PUBLIC_URL/realms/${WORKFORCE_REALM:-workforce}" WORKFORCE_CLIENT_ID=kuloffice \
WORKFORCE_CLIENT_SECRET="$WORKFORCE_API_SECRET" \
  sh /stack/bootstrap.sh
echo "done"
