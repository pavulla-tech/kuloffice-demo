"""Lets web apps running on developers' laptops sign in through this Keycloak.

For each origin in DEV_WEB_ORIGINS (e.g. "http://localhost:3000"), the web and
passkey clients get that origin's callback as a redirect URI and the origin as
a web origin, beside the deployed app's. Idempotent: an origin already there
is left alone, and nothing else on the clients changes. Empty: nothing to do.

This is a development stack: a laptop's web app then signs real accounts in,
the same as the deployed one does (the local stack's KEYCLOAK=server).
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

KEYCLOAK = os.environ["KEYCLOAK_URL"].rstrip("/")
REALM = os.environ.get("REALM", "kulpay")
CLIENTS = [os.environ.get("WEB_CLIENT_ID", "kulpay-web"), os.environ.get("PASSKEY_CLIENT_ID", "kulpay-web-passkey")]
ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("DEV_WEB_ORIGINS", "").replace(",", " ").split() if o.strip()]


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
    if not ORIGINS:
        print("  --  no DEV_WEB_ORIGINS: laptops' web apps can't sign in here")
        return
    status, tok = call("POST", "/realms/master/protocol/openid-connect/token", form={
        "grant_type": "password", "client_id": "admin-cli",
        "username": os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        "password": os.environ["KC_BOOTSTRAP_ADMIN_PASSWORD"]})
    if status != 200:
        sys.exit(f"Keycloak admin login failed: {status} {tok}")
    t = tok["access_token"]
    for client_id in CLIENTS:
        status, found = call("GET", f"/admin/realms/{REALM}/clients?clientId={urllib.parse.quote(client_id)}", t)
        if status != 200 or not found:
            print(f"  --  no client '{client_id}' in realm '{REALM}', skipped")
            continue
        client = found[0]
        redirects, origins = list(client.get("redirectUris") or []), list(client.get("webOrigins") or [])
        added = []
        for origin in ORIGINS:
            callback = origin + "/api/auth/callback"
            if callback not in redirects:
                redirects.append(callback)
                added.append(callback)
            if origin not in origins:
                origins.append(origin)
        if not added and all(o in client.get("webOrigins", []) for o in ORIGINS):
            print(f"  ok  '{client_id}' already accepts {', '.join(ORIGINS)}")
            continue
        status, out = call("PUT", f"/admin/realms/{REALM}/clients/{client['id']}", t,
                           body={**client, "redirectUris": redirects, "webOrigins": origins})
        if status >= 300:
            sys.exit(f"updating '{client_id}' failed: {status} {out}")
        print(f"  ok  '{client_id}' now also accepts {', '.join(ORIGINS)}")


if __name__ == "__main__":
    main()
