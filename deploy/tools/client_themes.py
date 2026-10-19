"""The mobile client signs in with the mobile app's login theme. Idempotent.

The realm and every other client use kulpay, the web theme from the provider's
JAR. The mobile app's embedded web views need its own screens, kulpay-mobile
(intaka's demo/theme, shipped in the Keycloak image under that name), so the
mobile client gets it as its login_theme. Only that attribute changes; a
client that doesn't exist is skipped.

MOBILE_CLIENT_ID (default kulpay-mobile; demo-mobile on the local stack),
MOBILE_LOGIN_THEME (default kulpay-mobile).
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

KEYCLOAK = os.environ["KEYCLOAK_URL"].rstrip("/")
REALM = os.environ.get("REALM", "kulpay")
CLIENT = os.environ.get("MOBILE_CLIENT_ID", "kulpay-mobile")
THEME = os.environ.get("MOBILE_LOGIN_THEME", "kulpay-mobile")


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
    status, found = call("GET", f"/admin/realms/{REALM}/clients?clientId={urllib.parse.quote(CLIENT)}", t)
    if status != 200 or not found:
        print(f"  --  no client '{CLIENT}' in realm '{REALM}', skipped")
        return
    client = found[0]
    attributes = dict(client.get("attributes") or {})
    if attributes.get("login_theme") == THEME:
        print(f"  ok  '{CLIENT}' already signs in with the {THEME} theme")
        return
    attributes["login_theme"] = THEME
    status, out = call("PUT", f"/admin/realms/{REALM}/clients/{client['id']}", t, body={**client, "attributes": attributes})
    if status >= 300:
        sys.exit(f"updating '{CLIENT}' failed: {status} {out}")
    print(f"  ok  '{CLIENT}' now signs in with the {THEME} theme")


if __name__ == "__main__":
    main()
