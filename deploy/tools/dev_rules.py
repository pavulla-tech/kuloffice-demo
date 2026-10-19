"""Development stacks: the notification texts KulOffice's products wait for. Idempotent.

Run by bin/kulpay after the development admin is seeded (DEV_ADMIN_EMAIL and
DEV_ADMIN_PASSWORD; never in production). It signs in as that admin, the way
the token panel does (Keycloak's password form, PKCE, the workforce panel
client), and for every text in dev_texts.json whose event, channel and
language have no approved text yet, proposes it and approves it: one operator
decides on development stacks (KULOFFICE_APPROVALS_SINGLE_OPERATOR). A text an
operator approved is never replaced; a proposal waiting is approved as it is.

The business policies (account_limits, claim_send, orientu) are decided in the
back office: this only reports whether each has an approved version.
"""
import base64
import hashlib
import html
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("KULOFFICE_URL", "http://kuloffice:8080").rstrip("/")
ISSUER = os.environ["WORKFORCE_ISSUER"].rstrip("/")
CLIENT = os.environ.get("WORKFORCE_PANEL_CLIENT", "kulpay-token-panel")
# The panel client's registered redirect; nothing is loaded from it.
REDIRECT = os.environ.get("WORKFORCE_PANEL_REDIRECT", "http://localhost:8765/")
EMAIL, PASSWORD = os.environ["DEV_ADMIN_EMAIL"], os.environ["DEV_ADMIN_PASSWORD"]
TEXTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dev_texts.json")
REASON = "development stack: default text (tools/dev_texts.json)"


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class StopAtRedirect(urllib.request.HTTPRedirectHandler):
    """Follows Keycloak's own redirects; stops at the one to the client's redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if newurl.startswith(REDIRECT):
            raise _Done(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _Done(Exception):
    def __init__(self, url):
        self.url = url


def sign_in():
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(), StopAtRedirect())
    verifier = b64url(secrets.token_bytes(40))
    params = {"client_id": CLIENT, "response_type": "code", "scope": "openid profile email", "redirect_uri": REDIRECT,
              "state": secrets.token_urlsafe(12), "code_challenge": b64url(hashlib.sha256(verifier.encode()).digest()),
              "code_challenge_method": "S256", "login_hint": EMAIL}

    def page(url, data=None):
        try:
            with opener.open(urllib.request.Request(url, data=data), timeout=30) as r:
                return r.read().decode(errors="replace"), None
        except _Done as done:
            return None, urllib.parse.parse_qs(urllib.parse.urlparse(done.url).query).get("code", [None])[0]

    body, _ = page(f"{ISSUER}/protocol/openid-connect/auth?{urllib.parse.urlencode(params)}")
    form = re.search(r'<form[^>]*action="([^"]+)"', body or "")
    if not form or 'name="password"' not in body:
        sys.exit("error: Keycloak did not show its password form for the development admin")
    _, code = page(html.unescape(form.group(1)),
                   urllib.parse.urlencode({"username": EMAIL, "password": PASSWORD, "credentialId": ""}).encode())
    if not code:
        sys.exit("error: the development admin's sign-in did not finish (wrong DEV_ADMIN_PASSWORD, or a required action)")
    req = urllib.request.Request(f"{ISSUER}/protocol/openid-connect/token", urllib.parse.urlencode({
        "grant_type": "authorization_code", "client_id": CLIENT, "code": code, "redirect_uri": REDIRECT,
        "code_verifier": verifier}).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def call(token, method, path, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"message": raw[:300]}


def main():
    with open(TEXTS, encoding="utf-8") as f:
        wanted = json.load(f)
    language = wanted["language"]
    token = sign_in()

    status, out = call(token, "GET", "/v1/business-policies")
    if status == 200:
        active = {p.get("key") for p in out.get("policies", []) if p.get("active_number")}
        for key in ("account_limits", "claim_send", "orientu"):
            if key not in active:
                print(f"  note  business policy {key}: none approved (back office, Políticas)")

    def templates(state):
        status, out = call(token, "GET", f"/v1/notification-templates?status={state}&language={language}")
        if status != 200:
            sys.exit(f"error: listing {state} texts: {status} {out}")
        return {(t["event"], t["channel"]): t for t in out.get("templates", [])}

    active, proposed = templates("active"), templates("proposed")
    made = kept = 0
    for text in wanted["texts"]:
        key = (text["event"], text["channel"])
        if key in active:
            kept += 1
            continue
        if key in proposed:
            tid = proposed[key]["id"]
        else:
            status, out = call(token, "POST", "/v1/notification-templates", {
                "event": text["event"], "channel": text["channel"], "language": language, "text": text["text"], "reason": REASON})
            if status >= 300:
                print(f"  warn  {text['event']} ({text['channel']}): not proposed: {status} {out.get('message', out)}")
                continue
            tid = out["id"]
        status, out = call(token, "POST", f"/v1/notification-templates/{tid}:approve", {"note": REASON})
        if status >= 300:
            print(f"  warn  {text['event']} ({text['channel']}): not approved: {status} {out.get('message', out)}"
                  " (is KULOFFICE_APPROVALS_SINGLE_OPERATOR=true?)")
            continue
        made += 1
    print(f"  ok  notification texts ({language}): {made} approved now, {kept} already in force")


if __name__ == "__main__":
    main()
