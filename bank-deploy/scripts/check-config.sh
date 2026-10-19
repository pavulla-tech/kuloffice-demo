#!/bin/sh
set -eu

env_file=${ENV_FILE:-.env}
[ -f "$env_file" ] || { echo "$env_file does not exist; run make setup" >&2; exit 1; }
[ -f kuloffice.env ] || { echo "kuloffice.env does not exist; run make setup" >&2; exit 1; }

required='KEYCLOAK_TAG KULOFFICE_TAG WEB_TAG FILESERVER_TAG PROVISIONER_TAG SOLANGE_TAG SOLANGE_CONSOLE_TAG KULPORTAL_TAG MINIO_TAG MC_TAG GATEWAY_TAG KEYCLOAK_PUBLIC_URL KEYCLOAK_PUBLIC_HOST KULOFFICE_PUBLIC_URL KULOFFICE_PUBLIC_HOST WEB_PUBLIC_URL GATEWAY_PUBLIC_URL SOLANGE_PUBLIC_URL SOLANGE_CONSOLE_PUBLIC_URL KULPORTAL_PUBLIC_URL DB_ROOT_PASSWORD KULOFFICE_DB_PASSWORD KEYCLOAK_DB_PASSWORD SOLANGE_DB_PASSWORD BLNK_DB_PASSWORD GATEWAY_DB_PASSWORD KC_ADMIN_PASSWORD ADMIN_CLIENT_SECRET WORKFORCE_API_SECRET GATEWAY_KULOFFICE_CLIENT_SECRET KULPORTAL_CLIENT_SECRET KULPORTAL_SESSION_SECRET OLA_SMS_BASE_URL OLA_SMS_API_KEY OLA_SMS_PROVIDER_ID KULOFFICE_ADMIN_EMAIL KULOFFICE_ADMIN_PASSWORD KULOFFICE_LICENSE_KEY BLNK_SERVER_SECRET_KEY BLNK_TOKENIZATION_SECRET BLNK_TYPESENSE_API_KEY GATEWAY_ACCOUNT_ID GATEWAY_API_KEY GATEWAY_SERVICE_API_KEY GATEWAY_ADMIN_KEY GATEWAY_CHECKER_KEY GATEWAY_ENCRYPTION_KEY MINIO_ROOT_USER MINIO_ROOT_PASSWORD BOQUISSO_ACCESS_KEY BOQUISSO_SECRET_KEY KULPAY_SESSION_SECRET SOLANGE_VISITOR_SECRET SOLANGE_ENCRYPTION_KEY SOLANGE_SESSION_SECRET'

set -a
# shellcheck disable=SC1090
. "./$env_file"
set +a

missing=""
for key in $required; do
  eval "value=\${$key:-}"
  case "$value" in ""|CHANGE_ME|*CHANGE_ME*) missing="$missing $key" ;; esac
done
[ -z "$missing" ] || { echo "missing or placeholder values:$missing" >&2; exit 1; }

[ "${#GATEWAY_ACCOUNT_ID}" -eq 27 ] || { echo "GATEWAY_ACCOUNT_ID must be exactly 27 alphanumeric characters" >&2; exit 1; }
case "$GATEWAY_ACCOUNT_ID" in *[!0-9A-Za-z]*) echo "GATEWAY_ACCOUNT_ID must be alphanumeric" >&2; exit 1 ;; esac
[ "${#KULOFFICE_ADMIN_PASSWORD}" -ge 20 ] || { echo "KULOFFICE_ADMIN_PASSWORD must contain at least 20 characters" >&2; exit 1; }
if [ "${PUBLISH_ADDRESS:-127.0.0.1}" != "127.0.0.1" ] && [ "${ALLOW_REMOTE_PROXY:-false}" != "true" ]; then
  echo "non-loopback PUBLISH_ADDRESS requires ALLOW_REMOTE_PROXY=true and a source-restricted bank firewall" >&2
  exit 1
fi

for key in KEYCLOAK_PUBLIC_URL KULOFFICE_PUBLIC_URL WEB_PUBLIC_URL GATEWAY_PUBLIC_URL SOLANGE_PUBLIC_URL SOLANGE_CONSOLE_PUBLIC_URL KULPORTAL_PUBLIC_URL; do
  eval "value=\$$key"
  case "$value" in https://*) ;; *) echo "$key must use https://" >&2; exit 1 ;; esac
done
case "$KULOFFICE_PUBLIC_URL" in
  "https://$KULOFFICE_PUBLIC_HOST"|"https://$KULOFFICE_PUBLIC_HOST/"*) ;;
  *) echo "KULOFFICE_PUBLIC_HOST must match KULOFFICE_PUBLIC_URL" >&2; exit 1 ;;
esac
case "$KEYCLOAK_PUBLIC_URL" in
  "https://$KEYCLOAK_PUBLIC_HOST"|"https://$KEYCLOAK_PUBLIC_HOST/"*) ;;
  *) echo "KEYCLOAK_PUBLIC_HOST must match KEYCLOAK_PUBLIC_URL" >&2; exit 1 ;;
esac

for key in GATEWAY_API_KEY GATEWAY_SERVICE_API_KEY GATEWAY_ADMIN_KEY GATEWAY_CHECKER_KEY; do
  eval "value=\$$key"
  case "$value" in *[!0-9a-f]*|"") echo "$key must be lowercase hexadecimal" >&2; exit 1 ;; esac
  [ "${#value}" -eq 64 ] || { echo "$key must be 64 hexadecimal characters" >&2; exit 1; }
done

[ "$GATEWAY_API_KEY" != "$GATEWAY_SERVICE_API_KEY" ] && \
[ "$GATEWAY_API_KEY" != "$GATEWAY_ADMIN_KEY" ] && \
[ "$GATEWAY_API_KEY" != "$GATEWAY_CHECKER_KEY" ] && \
[ "$GATEWAY_SERVICE_API_KEY" != "$GATEWAY_ADMIN_KEY" ] && \
[ "$GATEWAY_SERVICE_API_KEY" != "$GATEWAY_CHECKER_KEY" ] && \
[ "$GATEWAY_ADMIN_KEY" != "$GATEWAY_CHECKER_KEY" ] || { echo "Gateway keys must all be different" >&2; exit 1; }
[ "$MINIO_ROOT_USER" != "$BOQUISSO_ACCESS_KEY" ] || { echo "BOQUISSO_ACCESS_KEY must not be the MinIO root user" >&2; exit 1; }
[ "$MINIO_ROOT_PASSWORD" != "$BOQUISSO_SECRET_KEY" ] || { echo "Boquisso and MinIO root secrets must be different" >&2; exit 1; }

echo "required settings are present"
