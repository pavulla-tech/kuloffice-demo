#!/bin/sh
# Copies the pipeline's secrets into the private service repositories.
#
#   sh deploy/ci/set-secrets.sh [NAME …]      (default: all of them)
#
# On GitHub Free, organisation secrets reach public repositories only: the
# private ones receive them empty. So each private repository gets its own
# copy. This asks for each value once (not echoed, not in shell history) and
# sets it in all five. kuloffice-demo is public and keeps using the
# organisation's. Run again to change or rotate one: set-secrets.sh DEPLOY_PASSWORD
#
# Needs gh logged in as someone who can administer those repositories.
set -eu
repos="kuloffice kulpay-webapp intaka solange boquisso-fileserver"
names=${*:-"KULPAY_DOCKERHUB_USERNAME KULPAY_DOCKERHUB_TOKEN DEPLOY_HOST DEPLOY_USER DEPLOY_PASSWORD DEPLOY_KNOWN_HOSTS"}

for name in $names; do
  printf '%s (Enter to skip): ' "$name"
  stty -echo 2> /dev/null || true; read -r value || true; stty echo 2> /dev/null || true; echo
  [ -n "$value" ] || { echo "  skipped"; continue; }
  for repo in $repos; do
    printf '%s' "$value" | gh secret set "$name" -R "pavulla-tech/$repo" > /dev/null
  done
  echo "  set in: $repos"
done
