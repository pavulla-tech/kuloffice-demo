"""Solange's console client in the workforce realm, with its roles. Idempotent.

A public PKCE client, solange-console, redirecting to the console's callback.
Its client roles - viewer, developer, admin - decide what staff may do in the
console; grant them in the admin console, or with `make operator SOLANGE=…`.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

KEYCLOAK = os.environ["KEYCLOAK_URL"].rstrip("/")
REALM = os.environ.get("WORKFORCE_REALM", "workforce")
CLIENT = os.environ.get("SOLANGE_CONSOLE_CLIENT_ID", "solange-console")
CONSOLE = os.environ["SOLANGE_CONSOLE_PUBLIC_URL"].rstrip("/")
ROLES = {
    "viewer": "Vê códigos, leituras, webhooks e estatísticas nos dois modos.",
    "developer": "Também cria e muda códigos e modelos, cria chaves de teste e reenvia webhooks.",
    "admin": "Também gere aplicações, chaves de produção e webhooks.",
}


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
        "clientId": CLIENT, "name": "Solange", "enabled": True, "publicClient": True, "protocol": "openid-connect",
        "standardFlowEnabled": True, "implicitFlowEnabled": False, "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False, "fullScopeAllowed": True,
        "redirectUris": [CONSOLE + "/api/auth/callback"], "webOrigins": [CONSOLE],
        "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": CONSOLE + "/entrar"},
    }
    status, found = call("GET", f"/admin/realms/{REALM}/clients?clientId={CLIENT}", t)
    if status != 200:
        sys.exit(f"no {REALM} realm: {status} {found}")
    if found:
        cid = found[0]["id"]
        call("PUT", f"/admin/realms/{REALM}/clients/{cid}", t, body={**found[0], **client})
        print(f"  ok  client '{CLIENT}' updated: redirects to {CONSOLE}/api/auth/callback")
    else:
        status, out = call("POST", f"/admin/realms/{REALM}/clients", t, body=client)
        if status >= 300:
            sys.exit(f"creating {CLIENT} failed: {status} {out}")
        cid = call("GET", f"/admin/realms/{REALM}/clients?clientId={CLIENT}", t)[1][0]["id"]
        print(f"  ok  client '{CLIENT}' created: redirects to {CONSOLE}/api/auth/callback")
    for name, description in ROLES.items():
        status, _ = call("GET", f"/admin/realms/{REALM}/clients/{cid}/roles/{name}", t)
        if status == 404:
            call("POST", f"/admin/realms/{REALM}/clients/{cid}/roles", t, body={"name": name, "description": description})
            print(f"  ok  role '{name}' created")


if __name__ == "__main__":
    main()
