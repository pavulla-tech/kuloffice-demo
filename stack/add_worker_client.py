"""The instruction worker's client in the customer realm. Idempotent.

Confidential, service accounts only (client credentials): kuloffice-worker
authenticates with this client's own service-account token, which kuloffice
treats as a service principal (no user, worker RPCs only) when the client ID
is a configured worker identity (KULOFFICE_INSTRUCTION_WORKERS). Tokens carry
kuloffice's API audience (the realm IdP's client), or kuloffice refuses them.
See kuloffice/docs/instruction-workers.md.
"""
import json, os, sys, urllib.error, urllib.parse, urllib.request

KEYCLOAK = os.environ.get("KEYCLOAK_URL", "http://localhost:8080/auth").rstrip("/")
REALM = os.environ.get("REALM", "demo")
CLIENT = os.environ.get("WORKER_CLIENT_ID", "kuloffice-worker")
SECRET = os.environ.get("WORKER_CLIENT_SECRET", "kuloffice-worker-local-secret")
API_CLIENT = os.environ.get("ADMIN_CLIENT_ID", "demo-backend")


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
        print(f"no '{REALM}' realm: worker client skipped")
        return
    settings = {
        "clientId": CLIENT, "name": "Instruction worker (kuloffice-worker)", "enabled": True,
        "publicClient": False, "secret": SECRET, "serviceAccountsEnabled": True,
        "standardFlowEnabled": False, "directAccessGrantsEnabled": False, "implicitFlowEnabled": False,
        "redirectUris": [], "webOrigins": [],
    }
    mapper = {
        "name": f"aud-{API_CLIENT}", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
        "config": {"included.client.audience": API_CLIENT, "access.token.claim": "true", "id.token.claim": "false"},
    }
    found = must(call("GET", f"/admin/realms/{REALM}/clients?clientId={urllib.parse.quote(CLIENT)}", token), "look up client")
    if found:
        must(call("PUT", f"/admin/realms/{REALM}/clients/{found[0]['id']}", token, {**found[0], **settings}), f"update client {CLIENT}")
        mappers = found[0].get("protocolMappers") or []
        if not any(m.get("name") == mapper["name"] for m in mappers):
            must(call("POST", f"/admin/realms/{REALM}/clients/{found[0]['id']}/protocol-mappers/models", token, mapper), "add audience mapper")
        print(f"client '{CLIENT}' updated; tokens carry aud '{API_CLIENT}'")
        return
    settings["protocolMappers"] = [mapper]
    must(call("POST", f"/admin/realms/{REALM}/clients", token, settings), f"create client {CLIENT}")
    print(f"client '{CLIENT}' created; tokens carry aud '{API_CLIENT}'")


if __name__ == "__main__":
    main()
