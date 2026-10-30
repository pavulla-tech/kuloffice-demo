#!/bin/sh
# Validates tools/dev_policies.json with KulOffice's own validators:
#   tools/dev_policies_check/check.sh <KulOffice checkout>
# The test is compiled inside that checkout through go test -overlay; nothing
# is written there.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
ko=$(cd "${1:?usage: check.sh <KulOffice checkout>}" && pwd)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
printf '{"Replace":{"%s/internal/businesspolicy/zz_kit_dev_policies_test.go":"%s/validate_test.go"}}\n' "$ko" "$here" > "$tmp/overlay.json"
cd "$ko"
DEV_POLICIES="$here/../dev_policies.json" go test -p 1 -count=1 -vet=off -overlay "$tmp/overlay.json" ./internal/businesspolicy/ -run "TestEveryDevPolicyValidates|TestDevPoliciesSwitchTheProductsOn" -v
