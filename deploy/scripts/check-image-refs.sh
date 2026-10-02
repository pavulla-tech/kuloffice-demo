#!/bin/sh
# Refuses two services pointed at the same image reference. Compose, the push
# and the pull are all happy with it; the wrong container just starts.
# Usage: check-image-refs.sh .env KEYCLOAK KULOFFICE … (the .env prefixes).
set -eu
env_file=$1; shift
[ -f "$env_file" ] || { echo "$env_file not found; run 'make setup'" >&2; exit 1; }
# shellcheck disable=SC1090
case $env_file in /*) ;; *) env_file=./$env_file ;; esac
set -a; . "$env_file"; set +a
seen=""
for name in "$@"; do
  eval "image=\${${name}_IMAGE:-}; tag=\${${name}_TAG:-}"
  [ -n "$image" ] && [ -n "$tag" ] || continue
  ref="$image:$tag"
  case " $seen " in
    *" $ref "*) echo "Two images point at $ref ($name and another): give each its own repository or tag in $env_file." >&2; exit 1 ;;
  esac
  seen="$seen $ref"
done
