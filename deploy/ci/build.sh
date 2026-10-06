#!/bin/sh
# Builds (and with --push, pushes) one unit's images at a tag, from a checkout
# of its repository, with the same recipes as `make images` on a laptop.
#
#   ci/build.sh <unit> <tag> <checkout> [--push]
#
# Run from anywhere; CI checks this repository out beside the service's.
set -eu
unit=${1:?unit}; tag=${2:?tag}; src=${3:?checkout}; push=${4:-}
# The checkout, from where we were called, before moving into the kit.
src=$(cd "$src" && pwd)
cd "$(dirname "$0")/.."
. ./lib/units.sh

is_unit "$unit" || { echo "unknown unit $unit (one of: $UNITS)" >&2; exit 2; }
echo "$tag" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$' ||
  { echo "tag $tag is not vMAJOR.MINOR.PATCH[-alphaNN]" >&2; exit 2; }

# The example's image names, this unit's tag and checkout.
env_file=.ci.env
cp .env.example "$env_file"
set_var() {
  awk -v k="$1" -v v="$2" 'index($0, k"=") == 1 { print k"="v; found=1; next } { print }
    END { if (!found) print k"="v }' "$env_file" > "$env_file.tmp" && mv "$env_file.tmp" "$env_file"
}
images=$(unit_images "$unit")
for name in $images; do set_var "${name}_TAG" "$tag"; done
set_var "$(unit_dir_var "$unit")" "$src"
set_var TARGET_PLATFORM linux/amd64

make --no-print-directory images ENV_FILE="$env_file" S="$images"
if [ "$push" = "--push" ]; then
  make --no-print-directory push ENV_FILE="$env_file" S="$images"
fi
rm -f "$env_file"
