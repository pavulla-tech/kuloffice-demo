"""Write a merchant's bindings on the Gateway (scripts/merchant-bindings.sh).

In live mode KulPay balance calls KulOffice as the Gateway's service client
and verifies KulOffice's signed checkout wake-ups (IG-45); in test mode it is
the Gateway's mock rail, so test payments never reach KulOffice.
A live application also gets M-Pesa at the PSP simulator, configured as the
simulator's own `bind` does for KulOffice's account (dev servers only).
BINDING_MODE=platform (make platform-wallet) binds KulPay balance live for the
Gateway's platform account (GATEWAY_ACCOUNT_ID), for KulPay's own purchases
at the hosted checkout: destination "platform", KulOffice's platform
application id; KulOffice moves the money into its external funds balance.
Nothing secret is printed: only each binding's id, mode and callback path.
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("GATEWAY_MANAGEMENT_URL", "http://gateway:9091/v1").rstrip("/")
REALM = os.environ.get("REALM", "kulpay")
# KulOffice's sentinel destination for a platform checkout.
PLATFORM = "platform"


def need(name):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"{name} is empty in .env")
    return value


def first_secret(name):
    return need(name).split(",")[0].strip()


def main():
    mode = need("BINDING_MODE")
    if mode == "platform":
        save(platform_body())
        return
    if mode not in ("live", "test"):
        sys.exit(f"unknown environment {mode}")
    if mode == "test":
        # Test mode is the Gateway's own: KulPay balance is its mock rail
        # (succeeds unless the request names a failure scenario), like every
        # other method in test mode. KulOffice is never called for it.
        save({"account_id": need("BINDING_TENANT"), "mode": "test", "method": "kulpay_balance", "driver": "mock",
              "label": "KulPay balance (test)", "enabled": True, "config": {}})
        return
    body = kulpay_balance(need("BINDING_TENANT"), mode, need("BINDING_ACCOUNT"), need("BINDING_PRODUCT"), need("BINDING_APP"))
    save(body)
    if mode == "live":
        sim = os.environ.get("SIMULATOR_URL", "http://simulator:8085").rstrip("/")
        try:
            with urllib.request.urlopen(sim + "/mpesa/public-key", timeout=15) as response:
                public_key = response.read().decode().strip()
        except (urllib.error.URLError, OSError) as error:
            sys.exit(f"the PSP simulator did not answer ({error}); M-Pesa not bound")
        save({
            "account_id": body["account_id"], "mode": "live", "method": "mpesa", "driver": "mpesa",
            "label": "mpesa (PSP simulator)", "enabled": True,
            "config": {"api_key": "simulator", "public_key": public_key, "service_provider_code": "171717",
                       "base_url": sim + "/mpesa", "timeout": "90s"},
        })


def kulpay_balance(tenant, mode, account, product, application, label="KulPay balance"):
    """A live KulPay balance binding: the Gateway calls KulOffice as its
    service client and verifies KulOffice's signed wake-ups."""
    return {
        "account_id": tenant,
        "mode": mode,
        "method": "kulpay_balance",
        "driver": "kulpay_balance",
        "label": label,
        "enabled": True,
        "config": {
            "base_url": os.environ.get("KULOFFICE_URL", "http://kuloffice:8080"),
            "token_url": f"http://keycloak:8080/realms/{REALM}/protocol/openid-connect/token",
            "client_id": os.environ.get("GATEWAY_KULOFFICE_CLIENT_ID", "kulpay-gateway"),
            "client_secret": need("GATEWAY_KULOFFICE_CLIENT_SECRET"),
            "audience": os.environ.get("ADMIN_CLIENT_ID", "kulpay-backend"),
            "signing_secret": first_secret("KULOFFICE_CHECKOUT_PROVIDER_WAKEUP_SIGNING_SECRETS"),
            "destination_account_id": account,
            "destination_product_id": product,
            "application_id": application,
        },
    }


def platform_body():
    """The platform account's live KulPay balance binding (KulPay's own
    purchases: bills on Gateway invoice links, recharges)."""
    application = os.environ.get("KULOFFICE_CHECKOUT_PROVIDER_PLATFORM_APPLICATION_ID", "").strip() or "kulpay-platform"
    return kulpay_balance(need("GATEWAY_ACCOUNT_ID"), "live", PLATFORM, PLATFORM, application, label="KulPay balance (platform)")


def save(body):
    req = urllib.request.Request(BASE + "/admin/connectors", data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", "Bearer " + need("GATEWAY_ADMIN_KEY"))
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as response:
            view = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        sys.exit(f"the Gateway refused the {body['method']} binding: {error.code} {error.read().decode(errors='replace')}")
    print(f"{body['method']} binding {view.get('id', '?')} ({body['mode']}) on tenant {body['account_id']};"
          f" callback {view.get('callback_url') or view.get('callback_path') or '-'}")


if __name__ == "__main__":
    main()
