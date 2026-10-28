#!/bin/sh
# Run the resumable FNB pilot provisioner inside the bank's tools image.
set -eu

command=${1:-apply}
config=${FNB_PILOT_CONFIG:-./fnb-pilot.yaml}
output=${FNB_PILOT_OUTPUT:-./fnb-pilot-output}
env_file=${ENV_FILE:-.env}

case "$command" in plan|apply|rollback) ;; *) echo "usage: $0 plan|apply|rollback" >&2; exit 2 ;; esac
[ -f "$config" ] || { echo "configuration not found: $config" >&2; exit 2; }
mkdir -p "$output"
chmod 700 "$output"

config_dir_abs=$(cd "$(dirname "$config")" && pwd)
config_name=$(basename "$config")
output_abs=$(cd "$output" && pwd)

docker compose --env-file "$env_file" -f compose.yaml --profile provisioning run --rm --no-deps \
  --entrypoint python3 \
  -e FNB_PILOT_CONFIG="/input/$config_name" \
  -e FNB_PILOT_OUTPUT=/output \
  -v "$config_dir_abs:/input:ro" \
  -v "$output_abs:/output" \
  provisioner /bank/fnb_pilot.py "$command"
