#!/bin/sh
# A merchant's kulpay_balance binding on the Gateway, made from its Payment
# Acceptance application in KulOffice (make kulpay-balance APP=pacapp_…).
# KulOffice's database gives the application's account, environment, receiving
# product (live) or sandbox destination (test) and the business's Gateway
# tenant (set by IG-67 provisioning); the tools image then writes the binding
# with the operator key. Secrets stay in .env and are never printed.
set -eu

app=${1:?usage: kulpay-balance.sh pacapp_…}
env_file=${ENV_FILE:-.env}
COMPOSE=${COMPOSE:-docker compose --env-file "$env_file"}

case $app in *[!A-Za-z0-9_]* | "") echo "not an application id: $app" >&2; exit 2 ;; esac

row=$($COMPOSE exec -T db psql -U postgres -d kuloffice -tA -F '|' -c "
  SELECT a.account_id, a.environment, a.sandbox_destination_id, a.gateway_account_id, a.status,
         COALESCE((SELECT d.product_id FROM payment_acceptance_destinations d
                    WHERE d.application_id = a.id AND d.removed_at IS NULL
                    ORDER BY d.created_at LIMIT 1), '')
    FROM payment_acceptance_applications a WHERE a.id = '$app'")
[ -n "$row" ] || { echo "no Payment Acceptance application $app in KulOffice" >&2; exit 1; }

IFS='|' read -r account environment sandbox tenant status product <<EOF
$row
EOF

[ "$status" = active ] || { echo "$app is $status, not active" >&2; exit 1; }
[ -n "$tenant" ] || { echo "$app has no Gateway tenant yet: wait for provisioning (KULOFFICE_PAYMENT_ACCEPTANCE_PROVISIONING_ENABLED)" >&2; exit 1; }
if [ "$environment" = test ]; then destination=$sandbox; else destination=$product; fi
[ -n "$destination" ] || { echo "$app has no destination product: authorize one on its page first" >&2; exit 1; }

$COMPOSE --profile tools run --rm --entrypoint python3 \
  -e BINDING_APP="$app" -e BINDING_ACCOUNT="$account" -e BINDING_MODE="$environment" \
  -e BINDING_PRODUCT="$destination" -e BINDING_TENANT="$tenant" \
  tools /tools/kulpay_balance_binding.py
