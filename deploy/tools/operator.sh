#!/bin/sh
# A staff member: their workforce account (staff_user.py) and, unless
# KULOFFICE_ROLE is empty, a kuloffice operator bound to it with that role
# (stack/seed_reviewer.py). `make operator EMAIL=… FIRST=… LAST=…`.
set -eu
export KC_BOOTSTRAP_ADMIN_USERNAME="${KC_ADMIN_USER:-admin}" KC_BOOTSTRAP_ADMIN_PASSWORD="${KC_ADMIN_PASSWORD:?}"
python3 /tools/staff_user.py
if [ -n "${KULOFFICE_ROLE:-}" ]; then
  REVIEWER_EMAIL="$STAFF_EMAIL" REVIEWER_FIRST_NAME="${STAFF_FIRST_NAME:-}" REVIEWER_LAST_NAME="${STAFF_LAST_NAME:-}" \
  REVIEWER_ROLE="$KULOFFICE_ROLE" REVIEWER_REASON="make operator" \
  WORKFORCE_ISSUER="${KEYCLOAK_PUBLIC_URL:?}/realms/${WORKFORCE_REALM:-workforce}" \
    python3 /stack/seed_reviewer.py
fi
