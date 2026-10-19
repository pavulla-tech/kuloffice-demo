#!/bin/sh
# A staff member: their workforce account (staff_user.py) and, unless
# KULOFFICE_ROLE is empty, a kuloffice operator bound to it with that role
# (stack/seed_reviewer.py). KULOFFICE_ROLE=ADMIN makes an admin instead: the
# Administradores role, holding every permission in kuloffice's catalogue.
# `make operator EMAIL=… FIRST=… LAST=… [ROLE=…|ADMIN]`.
set -eu
export KC_BOOTSTRAP_ADMIN_USERNAME="${KC_ADMIN_USER:-admin}" KC_BOOTSTRAP_ADMIN_PASSWORD="${KC_ADMIN_PASSWORD:?}"
python3 /tools/staff_user.py
role=${KULOFFICE_ROLE:-} admin=
case $role in
  [Aa][Dd][Mm][Ii][Nn])
    # The whole catalogue covers the KYC and product roles: grant neither.
    role= admin=Administradores
    export REVIEWER_PRODUCT_ROLE=
    ;;
esac
if [ -n "$role" ] || [ -n "$admin" ]; then
  REVIEWER_EMAIL="$STAFF_EMAIL" REVIEWER_FIRST_NAME="${STAFF_FIRST_NAME:-}" REVIEWER_LAST_NAME="${STAFF_LAST_NAME:-}" \
  REVIEWER_ROLE="$role" REVIEWER_ADMIN_ROLE="$admin" REVIEWER_REASON="make operator" \
  WORKFORCE_ISSUER="${KEYCLOAK_PUBLIC_URL:?}/realms/${WORKFORCE_REALM:-workforce}" \
    python3 /stack/seed_reviewer.py
fi
