#!/bin/sh
# Once, as root, on the server: Docker Hub credentials for pulls, so the
# server pulls as an account (its rate limit) instead of anonymously (a much
# lower one, shared by everything on this address).
#
#   sudo sh bin/registry-login.sh [user …]     (default: kulpay-deploy and you)
#
# Use a Docker Hub personal access token with the "Public Repo Read-only"
# scope: it can pull, and nothing else. Never the push token CI uses.
#
# Docker keeps logins per user (~/.docker/config.json, readable by that user
# only), so each user that pulls gets it: the deploy user (CI's deploys and
# rollbacks) and whoever runs make here. Safe to run again, e.g. to rotate the
# token.
set -eu
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)" >&2; exit 1; }
users=${*:-kulpay-deploy ${SUDO_USER:-root}}

printf 'Docker Hub username: '
read -r username
[ -n "$username" ] || { echo "no username" >&2; exit 1; }
printf 'Read-only access token (not shown): '
stty -echo 2> /dev/null || true; read -r token || true; stty echo 2> /dev/null || true; echo
[ -n "$token" ] || { echo "no token" >&2; exit 1; }

for user in $users; do
  id "$user" > /dev/null 2>&1 || { echo "$user: no such user, skipped" >&2; continue; }
  if printf '%s' "$token" | su - "$user" -s /bin/sh -c "docker login -u '$username' --password-stdin" > /dev/null; then
    echo "$user: logged in to Docker Hub as $username"
  else
    echo "$user: the login failed (wrong token, or $user can't reach Docker)" >&2
    exit 1
  fi
done

