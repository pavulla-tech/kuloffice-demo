#!/bin/sh
# Production-only, idempotent identity and license provisioning.
set -eu

: "${KEYCLOAK_PUBLIC_URL:?}" "${KC_ADMIN_PASSWORD:?}" "${ADMIN_CLIENT_SECRET:?}"
: "${WORKFORCE_API_SECRET:?}" "${KULOFFICE_LICENSE_KEY:?}"

export KC_BOOTSTRAP_ADMIN_USERNAME="${KC_ADMIN_USER:-admin}"
export KC_BOOTSTRAP_ADMIN_PASSWORD="$KC_ADMIN_PASSWORD"
export REALM="${REALM:-kulpay}"
export ADMIN_CLIENT_ID="${ADMIN_CLIENT_ID:-kulpay-backend}"
export API_AUDIENCE="$ADMIN_CLIENT_ID"
export WEB_CLIENT_ID="${WEB_CLIENT_ID:-kulpay-web}"
export PASSKEY_CLIENT_ID="${PASSKEY_CLIENT_ID:-kulpay-web-passkey}"
export MOBILE_CLIENT_ID="${MOBILE_CLIENT_ID:-kulpay-mobile}"
export APP_CLIENT_ID="bank-bootstrap-unused"
export PUBLIC_BASE_URL="$KULOFFICE_PUBLIC_URL"
export WEB_BASE_URL="${WEB_PUBLIC_URL:?}"
export SSL_REQUIRED=external
export BRUTE_FORCE_PROTECTED=true
export PHONE_BUDGET="${PHONE_BUDGET:-3}"
export IP_BUDGET="${IP_BUDGET:-10}"
export LOOKUP_BUDGET="${LOOKUP_BUDGET:-30}"
export DEBUG=false

echo "== customer realm '$REALM'"
python3 /setup/configure_realm.py
if [ -f /setup/update_existing_realm.py ]; then python3 /setup/update_existing_realm.py; fi
python3 /tools/client_themes.py
python3 /tools/gateway_client.py
python3 /bank/remove_client.py "$APP_CLIENT_ID"

echo "== workforce realm '${WORKFORCE_REALM:-workforce}'"
REVIEWER_EMAIL= API_CLIENT_SECRET="$WORKFORCE_API_SECRET" python3 /setup/add_workforce_realm.py
python3 /tools/solange_console_client.py
PORTAL_URL="${KULPORTAL_PUBLIC_URL:?}" PORTAL_CLIENT_SECRET="${KULPORTAL_CLIENT_SECRET:?}" \
  python3 /stack/add_portal_client.py

echo "== KulOffice license and identity providers"
KULOFFICE_LICENSE_KEY="$KULOFFICE_LICENSE_KEY" \
IDP_ISSUER_URL="$KEYCLOAK_PUBLIC_URL/realms/$REALM" \
IDP_CLIENT_ID="$ADMIN_CLIENT_ID" IDP_CLIENT_SECRET="$ADMIN_CLIENT_SECRET" \
WORKFORCE_ISSUER_URL="$KEYCLOAK_PUBLIC_URL/realms/${WORKFORCE_REALM:-workforce}" \
WORKFORCE_CLIENT_ID=kuloffice WORKFORCE_CLIENT_SECRET="$WORKFORCE_API_SECRET" \
  sh /stack/bootstrap.sh

echo "production provisioning completed"
