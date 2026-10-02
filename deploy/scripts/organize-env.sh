#!/bin/sh

set -eu

env_file=${1:-.env}
example_file=${2:-.env.example}

if [ ! -f "$env_file" ]; then
  echo "$env_file does not exist; run 'make setup' first" >&2
  exit 1
fi

if [ ! -f "$example_file" ]; then
  echo "$example_file does not exist" >&2
  exit 1
fi

temp_file=$(mktemp "${TMPDIR:-/tmp}/kulpay-env.XXXXXX")
trap 'rm -f "$temp_file"' EXIT HUP INT TERM

awk '
  function assignment(line, normalized) {
    normalized = line
    sub(/^[[:space:]]*/, "", normalized)
    sub(/^#[[:space:]]*/, "", normalized)
    if (normalized !~ /^[A-Za-z_][A-Za-z0-9_]*=/) return ""
    return normalized
  }

  function key_of(line, normalized, parts) {
    normalized = assignment(line)
    if (normalized == "") return ""
    split(normalized, parts, "=")
    return parts[1]
  }

  FNR == NR {
    key = key_of($0)
    if (key == "") next

    if (!(key in seen_order)) {
      order[++order_count] = key
      seen_order[key] = 1
    }

    normalized = assignment($0)
    trimmed = $0
    sub(/^[[:space:]]*/, "", trimmed)

    if (trimmed ~ /^#/) {
      if (!(key in active)) {
        current[key] = normalized
        commented[key] = 1
      }
    } else {
      current[key] = normalized
      active[key] = 1
      delete commented[key]
    }
    next
  }

  {
    key = key_of($0)
    if (key == "") {
      print $0
      next
    }

    template[key] = 1
    if (key in current) {
      if (key in active) print current[key]
      else print "# " current[key]
    } else {
      print "# " assignment($0)
    }
  }

  END {
    custom_count = 0
    for (i = 1; i <= order_count; i++) {
      key = order[i]
      if (!(key in template)) custom_count++
    }

    if (custom_count > 0) {
      print ""
      print "# Custom or legacy variables preserved from the previous .env"
      for (i = 1; i <= order_count; i++) {
        key = order[i]
        if (key in template) continue
        if (key in active) print current[key]
        else print "# " current[key]
      }
    }
  }
' "$env_file" "$example_file" > "$temp_file"

if cmp -s "$env_file" "$temp_file"; then
  echo "$env_file is already organized"
  exit 0
fi

timestamp=$(date +%Y%m%d-%H%M%S)
backup_file="${env_file}.backup.${timestamp}"
if [ -e "$backup_file" ]; then
  backup_file="${backup_file}.$$"
fi

cp -p "$env_file" "$backup_file"
while IFS= read -r line || [ -n "$line" ]; do
  printf "%s\n" "$line"
done < "$temp_file" > "$env_file"

echo "Organized $env_file using $example_file"
echo "Backup: $backup_file"
