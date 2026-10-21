"""The Gateway operator dashboard's client in the workforce realm. Idempotent.

A confidential client, kulpay-gateway-admin, for the Gateway's operator
sign-in (authorization code with PKCE, KULPAY_OIDC_*): the dashboard at
GATEWAY_MGMT_PUBLIC_URL/admin/. Its secret is GATEWAY_OIDC_CLIENT_SECRET,
made once into .env by bin/kulpay. Only staff holding its client role
"operator" get in; grant it with `make operator … GATEWAY=1`. Each operator
signs in as themselves, so the Gateway's four-eyes approvals need two people.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

KEYCLOAK = os.environ["KEYCLOAK_URL"].rstrip("/")
REALM = os.environ.get("WORKFORCE_REALM", "workforce")
CLIENT = os.environ.get("GATEWAY_OIDC_CLIENT_ID", "kulpay-gateway-admin")
DASHBOARD = os.environ.get("GATEWAY_MGMT_PUBLIC_URL", "https://mgnt.kulpay.pavulla.com").rstrip("/")
SECRET = os.environ["GATEWAY_OIDC_CLIENT_SECRET"]
ROLE = ("operator", "Entra no painel de operadores da Gateway.")


def call(method, path, token=None, body=None, form=None):
    headers, data = {}, None
    if form is not None:
        data, headers["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(KEYCLOAK + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def main():
    status, tok = call("POST", "/realms/master/protocol/openid-connect/token", form={
        "grant_type": "password", "client_id": "admin-cli",
        "username": os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        "password": os.environ["KC_BOOTSTRAP_ADMIN_PASSWORD"]})
    if status != 200:
        sys.exit(f"Keycloak admin login failed: {status} {tok}")
    t = tok["access_token"]
    client = {
        "clientId": CLIENT, "name": "Gateway (operadores)", "enabled": True, "publicClient": False,
        "clientAuthenticatorType": "client-secret", "secret": SECRET, "protocol": "openid-connect",
        "standardFlowEnabled": True, "implicitFlowEnabled": False, "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False, "fullScopeAllowed": True,
        "redirectUris": [DASHBOARD + "/admin/callback"], "webOrigins": [DASHBOARD],
        "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": DASHBOARD + "/admin/login"},
    }
    status, found = call("GET", f"/admin/realms/{REALM}/clients?clientId={CLIENT}", t)
    if status != 200:
        sys.exit(f"no {REALM} realm: {status} {found}")
    if found:
        cid = found[0]["id"]
        status, out = call("PUT", f"/admin/realms/{REALM}/clients/{cid}", t, body={**found[0], **client})
        if status >= 300:
            sys.exit(f"updating {CLIENT} failed: {status} {out}")
        print(f"  ok  client '{CLIENT}' updated: redirects to {DASHBOARD}/admin/callback")
    else:
        status, out = call("POST", f"/admin/realms/{REALM}/clients", t, body=client)
        if status >= 300:
            sys.exit(f"creating {CLIENT} failed: {status} {out}")
        cid = call("GET", f"/admin/realms/{REALM}/clients?clientId={CLIENT}", t)[1][0]["id"]
        print(f"  ok  client '{CLIENT}' created: redirects to {DASHBOARD}/admin/callback")
    name, description = ROLE
    status, _ = call("GET", f"/admin/realms/{REALM}/clients/{cid}/roles/{name}", t)
    if status == 404:
        call("POST", f"/admin/realms/{REALM}/clients/{cid}/roles", t, body={"name": name, "description": description})
        print(f"  ok  role '{name}' created")


if __name__ == "__main__":
    main()
