"""The test platform's sign-in (testes.kulpay.pavulla.com). Idempotent.

A realm of its own, TESTES_REALM (default testes), so the people the test's
manager creates never get a KulPay staff account. In it:
- the realm roles gestor, testador and programador;
- the confidential client kulpay-testes (TESTES_OIDC_CLIENT_SECRET), redirecting
  to TESTES_PUBLIC_URL/api/auth/callback, whose service account may manage
  this realm's users (the platform's «Pessoas» page) and nothing else;
- when TESTES_GESTOR_EMAIL is set and has no account yet, that person with the
  gestor role and a temporary password, printed once.
"""
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

KEYCLOAK = os.environ["KEYCLOAK_URL"].rstrip("/")
REALM = os.environ.get("TESTES_REALM", "testes")
CLIENT = "kulpay-testes"
SECRET = os.environ["TESTES_OIDC_CLIENT_SECRET"]
APP = os.environ.get("TESTES_PUBLIC_URL", "https://testes.kulpay.pavulla.com").rstrip("/")
GESTOR = os.environ.get("TESTES_GESTOR_EMAIL", "").strip().lower()
ROLES = {
    "gestor": "Gere a ronda: pessoas, plano, atribuições, confirmações e defeitos.",
    "testador": "Faz os passos que lhe dão e reporta-os.",
    "programador": "Vê os defeitos e marca os seus como corrigidos.",
}
# What the client's service account may do in this realm (realm-management).
SERVICE_ROLES = ["manage-users", "view-users", "query-users", "view-realm"]


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
            return resp.status, (json.loads(raw) if raw and resp.headers.get("Content-Type", "").startswith("application/json") else {}), resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace"), e.headers


def need(ok, what):
    if not ok:
        sys.exit(f"testes realm: {what}")


def main():
    status, tok, _ = call("POST", "/realms/master/protocol/openid-connect/token", form={
        "grant_type": "password", "client_id": "admin-cli",
        "username": os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        "password": os.environ["KC_BOOTSTRAP_ADMIN_PASSWORD"]})
    need(status == 200, f"Keycloak admin login failed: {status} {tok}")
    t = tok["access_token"]

    status, _, _ = call("GET", f"/admin/realms/{REALM}", t)
    if status == 404:
        status, out, _ = call("POST", "/admin/realms", t, body={
            "realm": REALM, "displayName": "Testes KulPay", "enabled": True,
            "loginWithEmailAllowed": True, "duplicateEmailsAllowed": False, "registrationAllowed": False,
            "resetPasswordAllowed": False, "bruteForceProtected": True, "sslRequired": "external",
            "internationalizationEnabled": True, "supportedLocales": ["pt"], "defaultLocale": "pt",
            "passwordPolicy": "length(8)",
        })
        need(status < 300, f"creating realm {REALM} failed: {status} {out}")
        print(f"  ok  realm '{REALM}' created")
    else:
        print(f"  ok  realm '{REALM}' exists")

    for name, description in ROLES.items():
        status, _, _ = call("GET", f"/admin/realms/{REALM}/roles/{name}", t)
        if status == 404:
            call("POST", f"/admin/realms/{REALM}/roles", t, body={"name": name, "description": description})
            print(f"  ok  role '{name}' created")

    client = {
        "clientId": CLIENT, "name": "Testes KulPay", "enabled": True, "publicClient": False, "protocol": "openid-connect",
        "secret": SECRET, "standardFlowEnabled": True, "implicitFlowEnabled": False, "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": True, "fullScopeAllowed": True,
        "redirectUris": [APP + "/api/auth/callback"], "webOrigins": [APP],
        "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": APP + "/"},
    }
    status, found, _ = call("GET", f"/admin/realms/{REALM}/clients?clientId={CLIENT}", t)
    need(status == 200, f"listing clients failed: {status} {found}")
    if found:
        cid = found[0]["id"]
        call("PUT", f"/admin/realms/{REALM}/clients/{cid}", t, body={**found[0], **client})
        print(f"  ok  client '{CLIENT}' updated")
    else:
        status, out, _ = call("POST", f"/admin/realms/{REALM}/clients", t, body=client)
        need(status < 300, f"creating {CLIENT} failed: {status} {out}")
        cid = call("GET", f"/admin/realms/{REALM}/clients?clientId={CLIENT}", t)[1][0]["id"]
        print(f"  ok  client '{CLIENT}' created")

    # The service account: manage this realm's users, nothing else.
    status, sa, _ = call("GET", f"/admin/realms/{REALM}/clients/{cid}/service-account-user", t)
    need(status == 200, f"no service account: {status} {sa}")
    status, rm, _ = call("GET", f"/admin/realms/{REALM}/clients?clientId=realm-management", t)
    need(status == 200 and rm, "no realm-management client")
    rmid = rm[0]["id"]
    wanted = []
    for name in SERVICE_ROLES:
        status, role, _ = call("GET", f"/admin/realms/{REALM}/clients/{rmid}/roles/{name}", t)
        need(status == 200, f"no realm-management role {name}")
        wanted.append(role)
    call("POST", f"/admin/realms/{REALM}/users/{sa['id']}/role-mappings/clients/{rmid}", t, body=wanted)
    print(f"  ok  service account may {', '.join(SERVICE_ROLES)}")

    if GESTOR:
        status, users, _ = call("GET", f"/admin/realms/{REALM}/users?email={urllib.parse.quote(GESTOR)}&exact=true", t)
        need(status == 200, f"looking up {GESTOR} failed: {status}")
        if users:
            uid = users[0]["id"]
            print(f"  ok  {GESTOR} already has an account")
        else:
            password = secrets.token_urlsafe(9)
            status, out, headers = call("POST", f"/admin/realms/{REALM}/users", t, body={
                "username": GESTOR, "email": GESTOR, "enabled": True, "emailVerified": True,
                "credentials": [{"type": "password", "value": password, "temporary": True}],
                "requiredActions": ["UPDATE_PASSWORD"]})
            need(status < 300, f"creating {GESTOR} failed: {status} {out}")
            uid = headers["Location"].rstrip("/").split("/")[-1]
            print(f"  ok  {GESTOR} created. Temporary password (shown once): {password}")
        status, role, _ = call("GET", f"/admin/realms/{REALM}/roles/gestor", t)
        call("POST", f"/admin/realms/{REALM}/users/{uid}/role-mappings/realm", t, body=[role])
        print(f"  ok  {GESTOR} has the gestor role")


if __name__ == "__main__":
    main()
