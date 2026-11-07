#!/bin/sh
# Weekly, from cron: what the runners' Docker engines built and pulled more
# than a week ago, and their stopped containers. The runners' Go and npm
# caches trim themselves (Go drops entries unused for five days).
set -eu
cd "$(dirname "$0")"
for d in dind-1 dind-2; do
  docker compose exec -T "$d" docker system prune -af --filter "until=168h" > /dev/null
  docker compose exec -T "$d" docker builder prune -af --filter "until=168h" > /dev/null
done
echo "runners cleaned: $(date -u +%FT%TZ)"
