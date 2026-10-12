"""Write a merchant's kulpay_balance binding on the Gateway (scripts/kulpay-balance.sh).

The binding calls KulOffice as the Gateway's service client and verifies
KulOffice's signed checkout wake-ups with the mode's signing secret (IG-45).
Nothing secret is printed: only the binding's id, mode and callback path.
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("GATEWAY_MANAGEMENT_URL", "http://gateway:9091/v1").rstrip("/")
REALM = os.environ.get("REALM", "kulpay")


def need(name):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"{name} is empty in .env")
    return value


def first_secret(name):
    return need(name).split(",")[0].strip()


def main():
    mode = need("BINDING_MODE")
    if mode not in ("live", "test"):
        sys.exit(f"unknown environment {mode}")
    wakeup = "KULOFFICE_CHECKOUT_PROVIDER_WAKEUP_SIGNING_SECRETS" if mode == "live" else "KULOFFICE_CHECKOUT_PROVIDER_WAKEUP_TEST_SIGNING_SECRETS"
    body = {
        "account_id": need("BINDING_TENANT"),
        "mode": mode,
        "method": "kulpay_balance",
        "driver": "kulpay_balance",
        "label": "KulPay balance",
        "enabled": True,
        "config": {
            "base_url": os.environ.get("KULOFFICE_URL", "http://kuloffice:8080"),
            "token_url": f"http://keycloak:8080/realms/{REALM}/protocol/openid-connect/token",
            "client_id": os.environ.get("GATEWAY_KULOFFICE_CLIENT_ID", "kulpay-gateway"),
            "client_secret": need("GATEWAY_KULOFFICE_CLIENT_SECRET"),
            "audience": os.environ.get("ADMIN_CLIENT_ID", "kulpay-backend"),
            "signing_secret": first_secret(wakeup),
            "destination_account_id": need("BINDING_ACCOUNT"),
            "destination_product_id": need("BINDING_PRODUCT"),
            "application_id": need("BINDING_APP"),
        },
    }
    req = urllib.request.Request(BASE + "/admin/connectors", data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", "Bearer " + need("GATEWAY_ADMIN_KEY"))
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as response:
            view = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        sys.exit(f"the Gateway refused the binding: {error.code} {error.read().decode(errors='replace')}")
    print(f"kulpay_balance binding {view.get('id', '?')} ({mode}) for {body['config']['application_id']}"
          f" on tenant {body['account_id']}; callback {view.get('callback_url') or view.get('callback_path') or '-'}")


if __name__ == "__main__":
    main()
