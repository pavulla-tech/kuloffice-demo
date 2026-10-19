"""Remove the setup script's unused demo client from the production realm."""
import json
import os
import sys
import urllib.parse
import urllib.request

base = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080").rstrip("/")
realm = os.environ.get("REALM", "kulpay")
client = sys.argv[1]


def request(method, path, token=None, form=None):
    data = urllib.parse.urlencode(form).encode() if form else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if form:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


token = request(
    "POST",
    "/realms/master/protocol/openid-connect/token",
    form={
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        "password": os.environ["KC_BOOTSTRAP_ADMIN_PASSWORD"],
    },
)["access_token"]
found = request(
    "GET",
    f"/admin/realms/{realm}/clients?clientId={urllib.parse.quote(client)}",
    token,
)
for item in found:
    request("DELETE", f"/admin/realms/{realm}/clients/{item['id']}", token)
if found:
    print(f"removed non-production client '{client}'")
