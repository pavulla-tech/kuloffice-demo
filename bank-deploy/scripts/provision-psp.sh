#!/bin/sh
# Run the resumable PSP provisioner (provisioning/psp_provision.py) inside the
# tools image: PSP_CONFIG names the partner's YAML (FNB_PILOT_CONFIG still read).
# It runs as root so it can write the root-only output directory. Tools images
# without PyYAML install it on the fly (needs the network).
set -eu

command=${1:-apply}
config=${PSP_CONFIG:-${FNB_PILOT_CONFIG:-./fnb-pilot.yaml}}
output=${PSP_OUTPUT:-${FNB_PILOT_OUTPUT:-./fnb-pilot-output}}
env_file=${ENV_FILE:-.env}

case "$command" in plan|apply|rollback) ;; *) echo "usage: $0 plan|apply|rollback" >&2; exit 2 ;; esac
[ -f "$config" ] || { echo "configuration not found: $config" >&2; exit 2; }
mkdir -p "$output"
chmod 700 "$output"

config_dir_abs=$(cd "$(dirname "$config")" && pwd)
config_name=$(basename "$config")
output_abs=$(cd "$output" && pwd)

docker compose --env-file "$env_file" -f compose.yaml --profile provisioning run --rm --no-deps \
  -u 0 --entrypoint sh \
  -e PSP_CONFIG="/input/$config_name" \
  -e PSP_OUTPUT=/output \
  -v "$config_dir_abs:/input:ro" \
  -v "$output_abs:/output" \
  provisioner -c 'python3 -c "import yaml" 2>/dev/null || python3 -m pip install --quiet --disable-pip-version-check --target /tmp/py pyyaml || { echo "the provisioner image has no PyYAML and it could not be installed" >&2; exit 2; }; PYTHONPATH=/tmp/py exec python3 /bank/psp_provision.py "$0"' "$command"
