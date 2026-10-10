"""Makes the workforce realm's demo user a kuloffice reviewer. Idempotent.

A Keycloak user in the workforce realm is not a reviewer until kuloffice has
an active operator bound to that user's subject, holding a role. This does
that through kuloffice's own administration API (the bootstrap admin, HTTP
Basic), each step only if it is not done yet:

  1. find the user's subject in the workforce realm;
  2. create the operator and activate it;
  3. bind the user (workforce identity provider + subject) to it;
  4. create the local reviewer role and grant it (and, with
     REVIEWER_ADMIN_ROLE, the admin role: the whole permission catalogue).

It must run before the reviewer's first sign-in: an unbound identity signing
in becomes a customer, and kuloffice never turns a customer into an operator.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

KEYCLOAK = os.environ["KEYCLOAK_URL"].rstrip("/")
REALM = os.environ.get("WORKFORCE_REALM", "workforce")
ISSUER = os.environ["WORKFORCE_ISSUER"]
API = os.environ["KULOFFICE_URL"].rstrip("/")
EMAIL = os.environ["REVIEWER_EMAIL"].strip().lower()
ADMIN = base64.b64encode(f"{os.environ['KULOFFICE_ADMIN_EMAIL']}:{os.environ['KULOFFICE_ADMIN_PASSWORD']}".encode()).decode()
ROLE = os.environ.get("REVIEWER_ROLE", "Revisores (local)")
REASON = os.environ.get("REVIEWER_REASON", "local stack: demo reviewer")
FIRST, LAST = os.environ.get("REVIEWER_FIRST_NAME", "Revisor"), os.environ.get("REVIEWER_LAST_NAME", "Local")

# What a reviewer does: take cases, read the evidence, decide.
PERMISSIONS = [
    ("case", "read"), ("case", "claim"), ("case", "release"), ("case", "progress"),
    ("kyc", "read"), ("kyc", "evidence.read"), ("kyc", "transcribe"),
    ("kyc", "approve"), ("kyc", "reject"), ("kyc", "documents.request"), ("kyc", "reopen"),
]

# The Conta Pagamento back office (kuloffice docs/PRODUCTS.md, Workforce API):
# evidence, closure review, fee waivers, parked operations, the catalogue.
PRODUCT_ROLE = os.environ.get("REVIEWER_PRODUCT_ROLE", "Produtos (local)")
PRODUCT_PERMISSIONS = [
    ("product", "read"), ("product_closure", "review"), ("product_fee", "waive"),
    ("product_operation", "read"), ("product_operation", "retry"),
    ("product_definition", "read"), ("product_definition", "create"), ("product_definition", "update"),
    ("product_definition", "publish"), ("product_definition", "retire"),
]

# An admin (make operator ROLE=ADMIN): every permission in kuloffice's catalogue,
# read live and re-applied on every run, so permissions kuloffice adds later
# reach admins too. Empty: no admin role.
ADMIN_ROLE = os.environ.get("REVIEWER_ADMIN_ROLE", "").strip()


def call(base, method, path, body=None, form=None, auth=None):
    data, headers = None, {}
    if form is not None:
        data, headers["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if auth:
        headers["Authorization"] = auth
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"message": raw.decode(errors="replace")}


def kuloffice(method, path, body=None):
    return call(API, method, path, body=body, auth="Basic " + ADMIN)


def must(result, what):
    status, out = result
    if status >= 300:
        sys.exit(f"{what} failed: {status} {out.get('message', out)}")
    return out


def subject():
    status, tok = call(KEYCLOAK, "POST", "/realms/master/protocol/openid-connect/token", form={
        "grant_type": "password", "client_id": "admin-cli",
        "username": os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        "password": os.environ.get("KC_BOOTSTRAP_ADMIN_PASSWORD", "admin"),
    })
    if status != 200:
        sys.exit(f"Keycloak admin login failed: {status} {tok}")
    status, users = call(KEYCLOAK, "GET", f"/admin/realms/{REALM}/users?email={urllib.parse.quote(EMAIL)}&exact=true",
                         auth="Bearer " + tok["access_token"])
    if status == 404:
        # An intaka checkout without add_workforce_realm.py: nothing to seed.
        print(f"no {REALM} realm: reviewer sign-in is not set up")
        sys.exit(0)
    if status != 200 or not users:
        sys.exit(f"{EMAIL} is not a user of the {REALM} realm (run add_workforce_realm.py first)")
    return users[0]["id"]


def main():
    sub = subject()

    operators = must(kuloffice("GET", "/v1/operators?page=1&limit=100"), "list operators").get("operators", [])
    op = next((o for o in operators if o.get("email", "").lower() == EMAIL), None)
    if not op:
        op = must(kuloffice("POST", "/v1/operators", {"email": EMAIL, "first_name": FIRST, "last_name": LAST}),
                  "create operator")
        print(f"operator {op['id']} created for {EMAIL}")
    if op.get("status") != "active":
        op = must(kuloffice("POST", f"/v1/operators/{op['id']}/transition",
                            {"status": "active", "reason": REASON, "version": int(op.get("version", 1))}),
                  "activate operator")
        print(f"operator {op['id']} activated")

    providers = must(kuloffice("GET", "/v1/system/identity-providers"), "list identity providers")
    found = [p for p in _providers(providers) if p.get("issuer_url") == ISSUER]
    if not found:
        sys.exit(f"no identity provider for {ISSUER}: run the bootstrap first")
    status, out = kuloffice("POST", f"/v1/operators/{op['id']}/identity",
                            {"identity_provider_id": found[0]["id"], "subject": sub, "reason": REASON})
    if status < 300:
        print(f"bound {EMAIL} ({sub}) to operator {op['id']}")
    elif status in (400, 409) and any(w in str(out.get("message", "")).lower() for w in ("already", "conflict")):
        # A second binding of the same subject is refused as a conflict.
        print(f"{EMAIL} already bound")
    else:
        sys.exit(f"bind identity failed: {status} {out.get('message', out)}")

    for name, description, permissions in (
        (ROLE, "KYC reviewers", PERMISSIONS),
        (PRODUCT_ROLE, "Conta Pagamento back office", PRODUCT_PERMISSIONS),
    ):
        if name:  # empty: that role is not wanted (an admin needs neither)
            ensure_role(kuloffice, op, name, description, permissions)
    if ADMIN_ROLE:
        catalogue = must(kuloffice("GET", "/v1/operator-permissions"), "list permissions").get("permissions", [])
        ensure_role(kuloffice, op, ADMIN_ROLE, "Every permission in the catalogue",
                    [(p["resource"], p["action"]) for p in catalogue], current=True)
    print(f"reviewer ready: {EMAIL}")


def ensure_role(kuloffice, op, name, description, permissions, current=False):
    """Creates the role once and grants it to the operator once. With current,
    an existing role's permissions are brought in line with these."""
    roles = must(kuloffice("GET", "/v1/operator-roles"), "list roles").get("roles", [])
    role = next((r for r in roles if r.get("name") == name), None)
    wanted = [{"resource": r, "action": a} for r, a in permissions]
    if not role:
        role = must(kuloffice("POST", "/v1/operator-roles", {
            "name": name, "description": description, "permissions": wanted,
        }), f"create role {name}")
        print(f"role '{name}' created")
    elif current and {(p["resource"], p["action"]) for p in role.get("permissions", [])} != set(permissions):
        role = must(kuloffice("POST", f"/v1/operator-roles/{role['id']}", {
            "description": description, "permissions": wanted, "reason": REASON,
        }), f"update role {name}")
        print(f"role '{name}' updated to {len(wanted)} permissions")
    held = must(kuloffice("GET", f"/v1/operators/{op['id']}/roles"), "list assignments").get("roles", [])
    if not any(r.get("id") == role["id"] for r in held):
        must(kuloffice("POST", f"/v1/operators/{op['id']}/roles/{role['id']}", {"grant": True, "reason": REASON}),
             f"grant role {name}")
        print(f"role '{name}' granted")


def _providers(body):
    """{"oidc": [{"id", "oidc": {"issuer_url", ...}}]} as flat {"id", "issuer_url", ...}."""
    return [p.get("oidc", {}) | {"id": p.get("id")} for p in body.get("oidc", [])]


if __name__ == "__main__":
    main()
