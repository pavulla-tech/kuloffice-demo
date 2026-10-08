"""The review portal's client in the workforce realm (kulportal2). Idempotent.

Confidential, standard flow with PKCE S256, redirect to PORTAL_URL's callback,
tokens carrying kuloffice's API audience (kuloffice refuses a staff token
whose aud lacks it). Runs after intaka's add_workforce_realm.py has made the
realm; keeps the redirect URIs and secret in step with this stack's settings.
"""
import json, os, sys, urllib.error, urllib.parse, urllib.request

KEYCLOAK = os.environ.get("KEYCLOAK_URL", "http://localhost:8080/auth").rstrip("/")
REALM = os.environ.get("WORKFORCE_REALM", "workforce")
CLIENT = os.environ.get("PORTAL_CLIENT_ID", "kulportal")
SECRET = os.environ.get("PORTAL_CLIENT_SECRET", "kulportal-local-secret")
PORTAL = os.environ.get("PORTAL_URL", "http://localhost:3100").rstrip("/")
API_CLIENT = os.environ.get("API_CLIENT_ID", "kuloffice")


def call(method, path, token=None, body=None, form=None):
    data, ctype = None, None
    if form is not None:
        data, ctype = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif body is not None:
        data, ctype = json.dumps(body).encode(), "application/json"
    req = urllib.request.Request(KEYCLOAK + path, data=data, method=method)
    if ctype:
        req.add_header("Content-Type", ctype)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def must(result, what, ok=(200, 201, 204)):
    status, body = result
    if status not in ok:
        sys.exit(f"{what} failed: {status} {body}")
    return body


def main():
    token = must(call("POST", "/realms/master/protocol/openid-connect/token", form={
        "grant_type": "password", "client_id": "admin-cli",
        "username": os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        "password": os.environ.get("KC_BOOTSTRAP_ADMIN_PASSWORD", "admin"),
    }), "admin login")["access_token"]
    status, _ = call("GET", f"/admin/realms/{REALM}", token)
    if status == 404:
        print(f"no '{REALM}' realm: portal client skipped")
        return
    settings = {
        "clientId": CLIENT, "name": "Review portal (kulportal2)", "enabled": True,
        "publicClient": False, "secret": SECRET, "standardFlowEnabled": True,
        "directAccessGrantsEnabled": False, "implicitFlowEnabled": False, "serviceAccountsEnabled": False,
        "redirectUris": [PORTAL + "/api/auth/callback"], "webOrigins": [PORTAL],
        "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": PORTAL + "/*"},
    }
    found = must(call("GET", f"/admin/realms/{REALM}/clients?clientId={urllib.parse.quote(CLIENT)}", token), "look up client")
    if found:
        must(call("PUT", f"/admin/realms/{REALM}/clients/{found[0]['id']}", token, {**found[0], **settings,
             "attributes": {**found[0].get("attributes", {}), **settings["attributes"]}}), f"update client {CLIENT}")
        print(f"client '{CLIENT}' updated for {PORTAL}")
        return
    settings["protocolMappers"] = [{
        "name": f"aud-{API_CLIENT}", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
        "config": {"included.client.audience": API_CLIENT, "access.token.claim": "true", "id.token.claim": "false"},
    }]
    must(call("POST", f"/admin/realms/{REALM}/clients", token, settings), f"create client {CLIENT}")
    print(f"client '{CLIENT}' created for {PORTAL}; tokens carry aud '{API_CLIENT}'")


if __name__ == "__main__":
    main()
