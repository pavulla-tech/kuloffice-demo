"""Provision the Gateway's KulOffice service principal, idempotently.

The Gateway uses client credentials for only two trusted KulOffice surfaces:
checkout-provider calls and Payment Acceptance projection pushes.  Its token
must carry KulOffice's API audience; it is not a customer, staff user, or
instruction worker.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


KEYCLOAK = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080").rstrip("/")
REALM = os.environ.get("REALM", "kulpay")
CLIENT = os.environ.get("GATEWAY_KULOFFICE_CLIENT_ID", "kulpay-gateway")
SECRET = os.environ.get("GATEWAY_KULOFFICE_CLIENT_SECRET", "")
AUDIENCE = os.environ.get("ADMIN_CLIENT_ID", "kulpay-backend")


def call(method, path, token=None, body=None, form=None):
    data, content_type = None, None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        content_type = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        content_type = "application/json"
    request = urllib.request.Request(KEYCLOAK + path, data=data, method=method)
    if content_type:
        request.add_header("Content-Type", content_type)
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")


def must(result, what, ok=(200, 201, 204)):
    status, body = result
    if status not in ok:
        sys.exit(f"{what} failed: {status} {body}")
    return body


def main():
    if not SECRET:
        sys.exit("GATEWAY_KULOFFICE_CLIENT_SECRET is required")
    token = must(
        call(
            "POST",
            "/realms/master/protocol/openid-connect/token",
            form={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
                "password": os.environ.get("KC_BOOTSTRAP_ADMIN_PASSWORD", "admin"),
            },
        ),
        "admin login",
    )["access_token"]
    settings = {
        "clientId": CLIENT,
        "name": "KulPay Gateway to KulOffice",
        "enabled": True,
        "publicClient": False,
        "secret": SECRET,
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "implicitFlowEnabled": False,
        "redirectUris": [],
        "webOrigins": [],
    }
    mapper = {
        "name": f"aud-{AUDIENCE}",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "config": {
            "included.client.audience": AUDIENCE,
            "access.token.claim": "true",
            "id.token.claim": "false",
        },
    }
    found = must(
        call(
            "GET",
            f"/admin/realms/{REALM}/clients?clientId={urllib.parse.quote(CLIENT)}",
            token,
        ),
        "look up Gateway client",
    )
    if found:
        client_id = found[0]["id"]
        must(
            call("PUT", f"/admin/realms/{REALM}/clients/{client_id}", token, {**found[0], **settings}),
            f"update client {CLIENT}",
        )
        mappers = must(
            call("GET", f"/admin/realms/{REALM}/clients/{client_id}/protocol-mappers/models", token),
            "list Gateway client mappers",
        )
        if not any(item.get("name") == mapper["name"] for item in mappers):
            must(
                call("POST", f"/admin/realms/{REALM}/clients/{client_id}/protocol-mappers/models", token, mapper),
                "add Gateway audience mapper",
            )
        print(f"client '{CLIENT}' updated; tokens carry aud '{AUDIENCE}'")
        return
    settings["protocolMappers"] = [mapper]
    must(call("POST", f"/admin/realms/{REALM}/clients", token, settings), f"create client {CLIENT}")
    print(f"client '{CLIENT}' created; tokens carry aud '{AUDIENCE}'")


if __name__ == "__main__":
    main()
