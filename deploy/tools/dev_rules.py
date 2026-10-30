"""Development stacks: the notification texts and business policies KulOffice's products wait for. Idempotent.

Run by bin/kulpay after the development admin is seeded (DEV_ADMIN_EMAIL and
DEV_ADMIN_PASSWORD; never in production). It signs in as that admin, the way
the token panel does (Keycloak's password form, PKCE, the workforce panel
client), and for every text in dev_texts.json whose event, channel and
language have no approved text yet, proposes it and approves it: one operator
decides on development stacks (KULOFFICE_APPROVALS_SINGLE_OPERATOR). A text an
operator approved is never replaced; a proposal waiting is approved as it is.

Then, for every business policy in dev_policies.json (complete example
documents, validated against KulOffice's validators by
tools/dev_policies_check/check.sh) whose key has no version at all yet, it
proposes the example and approves it (dev: nothing off). A key with any
version an operator made (in force, waiting, rejected or retired) is left
alone; a proposal this script left waiting is approved. A key the running
KulOffice does not register is skipped.

Last, the QR codes' general template: when the back office has none chosen
(or the one chosen is gone from Solange), it signs in to Solange's console
client as the same admin, creates the template "KulPay (dev)" in Solange's
staff API unless a template of that name is there, and makes it the back
office's general template (Códigos QR → Modelo geral). A choice an operator
made is never changed.
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
POLICIES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dev_policies.json")
REASON = "development stack: default text (tools/dev_texts.json)"
POLICY_REASON = "development stack: example policy (tools/dev_policies.json)"
SOLANGE = os.environ.get("SOLANGE_INTERNAL_URL", "http://solange:8090").rstrip("/")
CONSOLE_CLIENT = os.environ.get("SOLANGE_CONSOLE_CLIENT_ID", "solange-console")
CONSOLE_URL = os.environ.get("SOLANGE_CONSOLE_PUBLIC_URL", "").rstrip("/")
QR_NOTE = "development stack: KulPay (dev) template (tools/dev_rules.py)"
# The console's "KulPay" preset in the logo's palette (deep teal, tick green).
QR_TEMPLATE = {
    "name": "KulPay (dev)", "modules": "dots", "fg": "#002F34", "bg": "#FFFFFF", "eye": "#002F34",
    "centre": "subject_icon", "error_correction": "Q", "frame_text": "Leia para pagar",
    "style": {"eye_frame": "rounded", "eye_ball": "dot", "frame": "badge", "frame_colour": "#002F34",
              "frame_text_colour": "#9AE665", "frame_icon": "phone"},
}


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class StopAtRedirect(urllib.request.HTTPRedirectHandler):
    """Follows Keycloak's own redirects; stops at the one to the client's redirect."""

    def __init__(self, redirect):
        super().__init__()
        self.redirect = redirect

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if newurl.startswith(self.redirect):
            raise _Done(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _Done(Exception):
    def __init__(self, url):
        self.url = url


def sign_in(client=CLIENT, redirect=REDIRECT):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(), StopAtRedirect(redirect))
    verifier = b64url(secrets.token_bytes(40))
    params = {"client_id": client, "response_type": "code", "scope": "openid profile email", "redirect_uri": redirect,
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
        "grant_type": "authorization_code", "client_id": client, "code": code, "redirect_uri": redirect,
        "code_verifier": verifier}).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def call(token, method, path, body=None, base=API):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
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


def seed_texts(token, wanted):
    language = wanted["language"]

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


def seed_policies(token, wanted):
    """Each example policy whose key has no version yet: proposed, then
    approved. Returns the keys approved now."""
    status, out = call(token, "GET", "/v1/business-policies")
    if status != 200:
        print(f"  warn  business policies not listed: {status} {out.get('message', out)}")
        return []
    registered = {p.get("key"): p for p in out.get("policies", [])}
    approved, kept = [], []
    for policy in wanted["policies"]:
        key = policy["key"]
        current = registered.get(key)
        if current is None:
            print(f"  note  business policy {key}: not in this KulOffice, skipped")
            continue
        if current.get("active_number"):
            kept.append(key)
            continue
        status, out = call(token, "GET", f"/v1/business-policies/{key}/versions")
        if status != 200:
            print(f"  warn  business policy {key}: versions not listed: {status} {out.get('message', out)}")
            continue
        versions = out.get("versions", [])
        ours = next((v for v in versions if v.get("status") == "proposed" and v.get("reason") == POLICY_REASON), None)
        if versions and ours is None:
            states = ", ".join(sorted({v.get("status", "?") for v in versions}))
            print(f"  note  business policy {key}: an operator's version is there ({states}); left alone")
            continue
        if ours is None:
            status, out = call(token, "POST", f"/v1/business-policies/{key}/versions", {
                "key": key, "document": json.dumps(policy["document"], ensure_ascii=False), "reason": POLICY_REASON})
            if status >= 300:
                print(f"  warn  business policy {key}: not proposed: {status} {out.get('message', out)}")
                continue
            ours = out
        number = ours.get("number")
        status, out = call(token, "POST", f"/v1/business-policies/{key}/versions/{number}:approve",
                           {"key": key, "number": number, "note": POLICY_REASON})
        if status >= 300:
            print(f"  warn  business policy {key}: version {number} not approved: {status} {out.get('message', out)}"
                  " (is KULOFFICE_APPROVALS_SINGLE_OPERATOR=true?)")
            continue
        approved.append(key)
    print(f"  ok  business policies: {len(approved)} approved now ({', '.join(approved) or 'none'}), {len(kept)} already in force")
    return approved


def seed_qr_template(token, solange_sign_in):
    """The back office's general QR template, when none is chosen: KulPay
    (dev), made in Solange if missing. Returns the template id set, or ""."""
    status, out = call(token, "GET", "/v1/workforce/qr/templates")
    if status != 200:
        print(f"  warn  QR templates not listed: {status} {out.get('message', out)} (is Solange connected? make solange-kulpay)")
        return ""
    chosen = (out.get("general") or {}).get("template_id", "")
    known = {t.get("id") for t in out.get("templates", [])}
    if chosen and chosen in known:
        print("  ok  QR general template: already chosen")
        return ""
    if not CONSOLE_URL:
        print("  note  QR general template: SOLANGE_CONSOLE_PUBLIC_URL is empty; choose one in the back office (Códigos QR → Modelo geral)")
        return ""
    try:
        staff = solange_sign_in()
    except SystemExit as error:
        print(f"  warn  Solange console sign-in: {error}; choose the template in the back office (Códigos QR → Modelo geral)")
        return ""
    status, out = call(staff, "GET", "/staff/v1/templates", base=SOLANGE)
    if status != 200:
        print(f"  warn  Solange's templates not listed: {status} {out.get('message', out)}")
        return ""
    template = next((t for t in out.get("data", []) if t.get("name") == QR_TEMPLATE["name"]), None)
    if template is None:
        status, out = call(staff, "POST", "/staff/v1/templates", QR_TEMPLATE, base=SOLANGE)
        if status >= 300:
            print(f"  warn  Solange refused the {QR_TEMPLATE['name']} template: {status} {out.get('message', out)}")
            return ""
        template = out.get("template") or {}
        print(f"  ok  Solange template {QR_TEMPLATE['name']} created")
    status, out = call(token, "PUT", "/v1/workforce/qr/general-template", {"template_id": template["id"], "note": QR_NOTE})
    if status >= 300:
        print(f"  warn  QR general template not set: {status} {out.get('message', out)}")
        return ""
    print(f"  ok  QR general template: {QR_TEMPLATE['name']} ({template['id']})")
    return template["id"]


def main():
    with open(TEXTS, encoding="utf-8") as f:
        texts = json.load(f)
    with open(POLICIES, encoding="utf-8") as f:
        policies = json.load(f)
    token = sign_in()
    seed_texts(token, texts)
    seed_policies(token, policies)
    seed_qr_template(token, lambda: sign_in(CONSOLE_CLIENT, CONSOLE_URL + "/api/auth/callback"))


if __name__ == "__main__":
    main()
