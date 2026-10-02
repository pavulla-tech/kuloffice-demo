"""A staff account in the workforce realm, if it is not there yet. Idempotent.

STAFF_EMAIL, STAFF_FIRST_NAME, STAFF_LAST_NAME. A new account gets a temporary
password (STAFF_PASSWORD, or a random one printed once) that must be changed at
the first sign-in. SOLANGE_ROLES (comma separated: viewer, developer, admin)
grants Solange console roles.
"""
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

KEYCLOAK = os.environ["KEYCLOAK_URL"].rstrip("/")
REALM = os.environ.get("WORKFORCE_REALM", "workforce")
CONSOLE_CLIENT = os.environ.get("SOLANGE_CONSOLE_CLIENT_ID", "solange-console")
EMAIL = os.environ["STAFF_EMAIL"].strip().lower()


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
    if "@" not in EMAIL:
        sys.exit("STAFF_EMAIL must be an email address")
    status, tok = call("POST", "/realms/master/protocol/openid-connect/token", form={
        "grant_type": "password", "client_id": "admin-cli",
        "username": os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        "password": os.environ["KC_BOOTSTRAP_ADMIN_PASSWORD"]})
    if status != 200:
        sys.exit(f"Keycloak admin login failed: {status} {tok}")
    t = tok["access_token"]
    users = call("GET", f"/admin/realms/{REALM}/users?email={urllib.parse.quote(EMAIL)}&exact=true", t)[1]
    if users:
        uid = users[0]["id"]
        print(f"  ok  {EMAIL} already has an account")
    else:
        password = os.environ.get("STAFF_PASSWORD") or secrets.token_urlsafe(12)
        status, out = call("POST", f"/admin/realms/{REALM}/users", t, body={
            "username": EMAIL, "email": EMAIL, "emailVerified": True, "enabled": True,
            "firstName": os.environ.get("STAFF_FIRST_NAME", ""), "lastName": os.environ.get("STAFF_LAST_NAME", ""),
            "credentials": [{"type": "password", "value": password, "temporary": True}],
            "requiredActions": ["UPDATE_PASSWORD"]})
        if status >= 300:
            sys.exit(f"creating {EMAIL} failed: {status} {out}")
        uid = call("GET", f"/admin/realms/{REALM}/users?email={urllib.parse.quote(EMAIL)}&exact=true", t)[1][0]["id"]
        print(f"  ok  {EMAIL} created; temporary password (changed at first sign-in): {password}")
    wanted = [r.strip() for r in os.environ.get("SOLANGE_ROLES", "").split(",") if r.strip()]
    if wanted:
        cid = call("GET", f"/admin/realms/{REALM}/clients?clientId={CONSOLE_CLIENT}", t)[1][0]["id"]
        roles = [call("GET", f"/admin/realms/{REALM}/clients/{cid}/roles/{r}", t)[1] for r in wanted]
        if any(not isinstance(r, dict) for r in roles):
            sys.exit(f"unknown Solange role in {wanted} (viewer, developer, admin)")
        call("POST", f"/admin/realms/{REALM}/users/{uid}/role-mappings/clients/{cid}", t, body=roles)
        print(f"  ok  Solange console roles: {', '.join(wanted)}")


if __name__ == "__main__":
    main()
