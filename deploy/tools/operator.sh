#!/bin/sh
# A staff member: their workforce account (staff_user.py) and, unless both
# KULOFFICE_ROLE and KULOFFICE_ADMIN_ROLE are empty, a kuloffice operator bound
# to it with those roles (stack/seed_reviewer.py). KULOFFICE_ADMIN_ROLE holds
# every permission in kuloffice's catalogue. `make operator EMAIL=… FIRST=… LAST=… [ADMIN=1]`.
set -eu
export KC_BOOTSTRAP_ADMIN_USERNAME="${KC_ADMIN_USER:-admin}" KC_BOOTSTRAP_ADMIN_PASSWORD="${KC_ADMIN_PASSWORD:?}"
python3 /tools/staff_user.py
if [ -n "${KULOFFICE_ROLE:-}" ] || [ -n "${KULOFFICE_ADMIN_ROLE:-}" ]; then
  REVIEWER_EMAIL="$STAFF_EMAIL" REVIEWER_FIRST_NAME="${STAFF_FIRST_NAME:-}" REVIEWER_LAST_NAME="${STAFF_LAST_NAME:-}" \
  REVIEWER_ROLE="${KULOFFICE_ROLE:-}" REVIEWER_ADMIN_ROLE="${KULOFFICE_ADMIN_ROLE:-}" REVIEWER_REASON="make operator" \
  WORKFORCE_ISSUER="${KEYCLOAK_PUBLIC_URL:?}/realms/${WORKFORCE_REALM:-workforce}" \
    python3 /stack/seed_reviewer.py
fi
