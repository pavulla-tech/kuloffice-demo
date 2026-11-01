"""Development stacks: QA test accounts (Orientu OR-2). Idempotent.

Run by bin/kulpay provision on development stacks (DEV_ADMIN_EMAIL set; never in
production) and by `make qa-fixtures`. Each account is made the way a customer
makes one, and approved the way an operator approves one:

- every person signs up on the USSD channel (intaka's /phone-auth/ussd,
  register with a PIN) and signs in with the number and PIN (the ussd-gateway
  client's direct grant, the one path to a customer token without an SMS code).
  Their first GET /v1/customers/me opens a KulPay Lite account;
- the verified people then do the app's KYC (POST /v1/kyc-submissions, the
  selfie), and the development admin (dev_rules.sign_in) claims the review
  case, transcribes the document and approves it, as a reviewer would. That is
  the path of someone who started on USSD and finished KYC in the app;
- the business is onboarded by its owner (POST /v1/customers/{id}/business,
  its documents, finish) and approved by the development admin;
- the restricted role is made from the "viewer" template (no transfers, no
  Orientu) and given by invitation, which the member accepts;
- the second product is a Mo Budget (POST /v1/accounts/{id}/budgets, the PIN);
- balances come from M-Pesa top-ups through the Gateway's simulator binding:
  the simulator's payer gets a balance and its prompt is approved on the
  simulator's API, as QA would on its page.

People (QA_FIXTURE_PHONES, comma separated in this order, overrides the
numbers): requester (verified, asks the family), payer (verified, Conta
Pagamento plus a Mo Budget, owns the business), member (verified, restricted
role in the business and on the requester's account), lite (KulPay Lite). The
business "Loja Teste QA" (approved, its Conta Pagamento).

The PINs are generated here and never printed: they go with the phones,
account ids and handles to QA_FIXTURES_FILE (mode 0600; bin/kulpay mounts the
kit's state/qa-fixtures/ there). A person whose PIN the file lost gets a new
one through Keycloak's admin API.

`reset` (make qa-fixtures RESET=1) also cancels the requester's open Orientu
requests (the open-request cap) before topping the payers up again. Daily-in
allowances are not reset: they are per Maputo day.

With BIOMETRICS_ENABLED=true KulOffice reads the document with MiniAiLive,
which refuses the synthetic images used here: the verified people then stop at
document_rejected (the Lite account and the rest that needs no verified person
are still made). With biometrics off every submission goes to a reviewer, and
this script is that reviewer.
"""
import base64
import datetime
import json
import os
import random
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib

API = os.environ.get("KULOFFICE_URL", "http://kuloffice:8080").rstrip("/")
KEYCLOAK = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080").rstrip("/")
# Customer tokens must name the issuer KulOffice trusts: the public one.
KEYCLOAK_PUBLIC = os.environ.get("KEYCLOAK_PUBLIC_URL", KEYCLOAK).rstrip("/")
REALM = os.environ.get("REALM", "kulpay")
USSD_CLIENT = os.environ.get("USSD_CLIENT_ID", "ussd-gateway")
SIMULATOR = os.environ.get("SIMULATOR_INTERNAL_URL", "http://simulator:8085").rstrip("/")
FILE = os.environ.get("QA_FIXTURES_FILE", "/qa/credentials.json")
# Where the file is on the server, for the one line printed about it.
SHOWN_AS = os.environ.get("QA_FIXTURES_SHOWN_AS", "")
REASON = "development stack: QA fixture (tools/dev_qa_fixtures.py)"
SLEEP = time.sleep
WAIT_SECONDS = int(os.environ.get("QA_FIXTURES_WAIT_SECONDS", "180"))
# Top-ups are made in steps the Lite per-transaction limit allows.
TOP_UP_STEP_MINOR = 500_000
TOP_UPS_PER_RUN = 8

PEOPLE = [
    {"key": "requester", "label": "Requerente (KYC completo): pede à família", "tier": "verified",
     "first_name": "Rita", "last_name": "Requerente Teste", "sex": "F", "fund_minor": 0},
    {"key": "payer", "label": "Pagador (KYC completo): Conta Pagamento e Mo Budget; dono da empresa", "tier": "verified",
     "first_name": "Paulo", "last_name": "Pagador Teste", "sex": "M", "fund_minor": 3_000_000},
    {"key": "member", "label": "Membro de equipa (KYC completo) com papel restrito", "tier": "verified",
     "first_name": "Marta", "last_name": "Membro Teste", "sex": "F", "fund_minor": 0},
    {"key": "lite", "label": "Conta KulPay Lite (USSD, sem KYC)", "tier": "lite", "fund_minor": 1_500_000},
]
# Test numbers, one per person (QA_FIXTURE_PHONES overrides them in order).
DEFAULT_PHONES = ["+258840000101", "+258840000102", "+258840000103", "+258840000104"]
BUSINESS = {"legal_name": "Loja Teste QA, Lda", "short_name": "Loja Teste QA", "plan": "pro", "fund_minor": 3_000_000,
            "email": "loja.teste@example.test", "nuit": "400000001", "registration": "QA-REG-0001"}
ROLE = {"name": "QA restrito (sem Orientu)", "template": "viewer",
        "description": "QA fixture: reads the account; may not send money or act on Orientu"}
BUDGET = {"name": "qa", "amount_minor": 100_000}

WARNINGS = []


def warn(message):
    WARNINGS.append(message)
    print(f"  warn  {message}", flush=True)


def ok(message):
    print(f"  ok  {message}", flush=True)


# ── HTTP ─────────────────────────────────────────────────────────────────────

def request(method, url, body=None, form=None, token=None, scope=None, timeout=60):
    """(status, JSON or {"message": text}); never raises for an HTTP status."""
    headers, data = {}, None
    if form is not None:
        data, headers["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    if scope:
        headers["x-scope-id"] = scope
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"message": raw[:300]}
    except urllib.error.URLError as e:
        return 0, {"message": f"{url}: {e.reason}"}


def ko(token, method, path, body=None, scope=None):
    return request(method, API + path, body=body, token=token, scope=scope)


def why(out):
    return out.get("message") or out.get("error_description") or out.get("error") or out


# ── the credentials file ─────────────────────────────────────────────────────

def load():
    try:
        with open(FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(state):
    """Writes the file 0600, replacing it whole (never a half-written file)."""
    state["updated_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    directory = os.path.dirname(FILE) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    tmp = os.path.join(directory, "." + os.path.basename(FILE) + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except BaseException:
        os.unlink(tmp)
        raise
    os.replace(tmp, FILE)


# ── PINs and images ──────────────────────────────────────────────────────────

def weak(pin):
    """What intaka's PIN policy refuses: all one digit, or a straight run."""
    steps = {int(b) - int(a) for a, b in zip(pin, pin[1:])}
    return len(set(pin)) == 1 or steps in ({1}, {-1})


def new_pin(length=4):
    rng = random.SystemRandom()
    while True:
        pin = "".join(rng.choice("0123456789") for _ in range(length))
        if not weak(pin):
            return pin


def png(width, height, rgb):
    """A plain PNG: the synthetic document and selfie (biometrics off only)."""
    row = b"\x00" + bytes(rgb) * width
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def image(name, rgb):
    data = png(640, 400, rgb)
    return {"filename": name, "content_type": "image/png", "size": str(len(data)), "data": base64.b64encode(data).decode()}


def digits(phone):
    return phone.lstrip("+")


# ── Keycloak: USSD sign-up and sign-in ───────────────────────────────────────

class Keycloak:
    def __init__(self):
        self.admin = None
        self.secret = None
        self.gateway = None

    def admin_token(self):
        if self.admin is None:
            status, out = request("POST", KEYCLOAK + "/realms/master/protocol/openid-connect/token", form={
                "grant_type": "password", "client_id": "admin-cli",
                "username": os.environ.get("KC_ADMIN_USER") or os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
                "password": os.environ.get("KC_ADMIN_PASSWORD") or os.environ.get("KC_BOOTSTRAP_ADMIN_PASSWORD", "")})
            if status != 200:
                raise Stop(f"Keycloak admin sign-in failed: {status} {why(out)}")
            self.admin = out["access_token"]
        return self.admin

    def ussd_secret(self):
        """The ussd-gateway client's secret, read from Keycloak (make init made it)."""
        if self.secret is None:
            t = self.admin_token()
            status, found = request("GET", f"{KEYCLOAK}/admin/realms/{REALM}/clients?clientId={USSD_CLIENT}", token=t)
            if status != 200 or not found:
                raise Stop(f"no {USSD_CLIENT} client in realm {REALM} (make init)")
            status, out = request("GET", f"{KEYCLOAK}/admin/realms/{REALM}/clients/{found[0]['id']}/client-secret", token=t)
            if status != 200 or not out.get("value"):
                raise Stop(f"{USSD_CLIENT}'s secret not readable: {status} {why(out)}")
            self.secret = out["value"]
        return self.secret

    def ussd(self, path, body):
        if self.gateway is None:
            status, out = request("POST", f"{KEYCLOAK_PUBLIC}/realms/{REALM}/protocol/openid-connect/token", form={
                "grant_type": "client_credentials", "client_id": USSD_CLIENT, "client_secret": self.ussd_secret()})
            if status != 200:
                raise Stop(f"the USSD client's own token: {status} {why(out)}")
            self.gateway = out["access_token"]
        return request("POST", f"{KEYCLOAK_PUBLIC}/realms/{REALM}/phone-auth/ussd/{path}", body=body, token=self.gateway)

    def sign_in(self, phone, pin):
        return request("POST", f"{KEYCLOAK_PUBLIC}/realms/{REALM}/protocol/openid-connect/token", form={
            "grant_type": "password", "client_id": USSD_CLIENT, "client_secret": self.ussd_secret(),
            "username": digits(phone), "password": pin, "scope": "openid"})

    def reset_pin(self, phone, pin):
        """A new PIN for an existing account whose PIN the file lost."""
        t = self.admin_token()
        status, users = request("GET", f"{KEYCLOAK}/admin/realms/{REALM}/users?username={urllib.parse.quote(phone)}&exact=true", token=t)
        if status != 200 or not users:
            raise Stop(f"Keycloak has no user for a fixture number ({status})")
        status, out = request("PUT", f"{KEYCLOAK}/admin/realms/{REALM}/users/{users[0]['id']}/reset-password", token=t,
                              body={"type": "password", "value": pin, "temporary": False})
        if status >= 300:
            raise Stop(f"setting a fixture's PIN failed: {status} {why(out)}")


class Stop(Exception):
    """This fixture cannot go on; the others may."""


def ensure_signed_up(kc, person, record, state):
    """The number has a USSD account and record['pin'] signs it in. Returns a token."""
    phone = record["phone"]
    status, out = kc.ussd("status", {"msisdn": digits(phone)})
    if status != 200:
        raise Stop(f"USSD status: {status} {why(out)}")
    length = int(out.get("pin_length") or 4)
    account_state = out.get("state")
    if account_state == "unavailable":
        raise Stop("the number's Keycloak account is disabled")
    if account_state in ("new", "needs_pin"):
        for _ in range(5):
            pin = new_pin(length)
            status, out = kc.ussd("register" if account_state == "new" else "pin", {"msisdn": digits(phone), "pin": pin})
            if status in (200, 201):
                record["pin"] = pin
                save(state)
                break
            if status != 400 or not str(out.get("error", "")).startswith("pin"):
                raise Stop(f"USSD {'register' if account_state == 'new' else 'pin'}: {status} {why(out)}")
        else:
            raise Stop("no PIN the realm accepts after five tries")
    elif not record.get("pin"):
        record["pin"] = new_pin(length)
        kc.reset_pin(phone, record["pin"])
        save(state)
    status, out = kc.sign_in(phone, record["pin"])
    if status == 401 and account_state == "ready":
        # The file's PIN is stale (set again by hand): a new one.
        record["pin"] = new_pin(length)
        kc.reset_pin(phone, record["pin"])
        save(state)
        status, out = kc.sign_in(phone, record["pin"])
    if status != 200:
        raise Stop(f"sign-in with the PIN: {status} {why(out)}")
    return out["access_token"]


# ── KulOffice: accounts, KYC and review ──────────────────────────────────────

def wait(what, check, seconds=None):
    """Polls check() every 2 s until it returns something truthy."""
    deadline = time.monotonic() + (WAIT_SECONDS if seconds is None else seconds)
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise Stop(f"timed out waiting for {what}")
        SLEEP(2)


def conta_pagamento(token, account_id):
    status, out = ko(token, "GET", f"/v1/accounts/{account_id}/products", scope=account_id)
    if status != 200:
        return None
    return next((p for p in out.get("products", []) if p.get("definition_code") == "conta_pagamento"), None)


def wait_usable(token, account_id, what):
    product = wait(f"{what}'s Conta Pagamento", lambda: (lambda p: p if p and p.get("usable") else None)(conta_pagamento(token, account_id)))
    return {"id": product["id"], "handle": product.get("handle", "")}


def submit_kyc(token, account_id):
    """The app's KYC capture: the document, then the selfie."""
    status, sub = ko(token, "POST", "/v1/kyc-submissions", {
        "doc_type": "BI", "image1": image("frente.png", (200, 210, 220)), "image2": image("verso.png", (210, 200, 190))}, scope=account_id)
    if status >= 300:
        raise Stop(f"document not sent: {status} {why(sub)}")

    def settled(states):
        def check():
            status, out = ko(token, "GET", f"/v1/kyc-submissions/{sub['id']}", scope=account_id)
            return out if status == 200 and out.get("state") in states else None
        return check

    read = wait("the document check", settled({"document_approved", "document_rejected", "try_again_later", "failed"}))
    if read["state"] != "document_approved":
        hint = " (BIOMETRICS_ENABLED=true reads the document; synthetic images pass only with biometrics off)" \
            if read["state"] == "document_rejected" else ""
        raise Stop(f"KYC document {read['state']}: {read.get('reason') or read.get('message')}{hint}")
    status, out = ko(token, "POST", f"/v1/kyc-submissions/{sub['id']}/selfie", {"image": image("selfie.png", (180, 150, 130))}, scope=account_id)
    if status >= 300:
        raise Stop(f"selfie not sent: {status} {why(out)}")
    done = wait("the selfie check", settled({"selfie_approved", "selfie_rejected", "try_again_later", "failed"}))
    if done["state"] != "selfie_approved":
        raise Stop(f"KYC selfie {done['state']}: {done.get('reason') or done.get('message')}")


class Reviewer:
    """The development admin, deciding review cases as a reviewer would."""

    def __init__(self, token):
        self.token = token
        status, me = ko(token, "GET", "/v1/operators/me")
        if status != 200:
            raise Stop(f"the development admin is not an operator: {status} {why(me)}")
        self.id = me.get("id") or (me.get("operator") or {}).get("id")

    def case(self, account_id):
        for queue in ("mine", "unassigned"):
            page = 1
            while True:
                status, out = ko(self.token, "GET", f"/v1/review-cases?queue={queue}&page={page}&limit=100")
                if status != 200:
                    raise Stop(f"review cases not listed: {status} {why(out)}")
                found = next((c for c in out.get("cases", []) if c.get("account_id") == account_id), None)
                if found:
                    return found
                if not out.get("has_more"):
                    break
                page += 1
        return None

    def approve(self, account_id, details=None):
        case = wait("the review case", lambda: self.case(account_id), 90)
        if case.get("status") == "deciding":
            # An approval of an earlier run waits for the customer's provisioning.
            ko(self.token, "POST", f"/v1/review-cases/{case['id']}/decision/retry", {})
            return
        if case.get("owner_id") != self.id:
            status, case = ko(self.token, "POST", f"/v1/review-cases/{case['id']}/actions",
                              {"action": "claim", "version": int(case["version"]), "reason": REASON})
            if status >= 300:
                raise Stop(f"review case not claimed: {status} {why(case)}")
        if details:
            status, out = ko(self.token, "POST", f"/v1/review-cases/{case['id']}/transcription",
                             {"version": int(case["version"]), "reason": REASON, "details": details})
            if status >= 300:
                raise Stop(f"document not transcribed: {status} {why(out)}")
            case = out
        status, out = ko(self.token, "POST", f"/v1/review-cases/{case['id']}/decision",
                         {"outcome": "approve", "reason": REASON, "version": int(case["version"])})
        if status == 503:
            # Approval recorded, the customer's provisioning retried.
            ko(self.token, "POST", f"/v1/review-cases/{case['id']}/decision/retry", {})
        elif status >= 300:
            raise Stop(f"approval refused: {status} {why(out)}")


def transcription(person, record):
    expires = (datetime.date.today() + datetime.timedelta(days=5 * 365)).isoformat()
    return {"document_type": "BI", "first_name": person["first_name"], "last_name": person["last_name"],
            "date_of_birth": "1990-01-01", "sex": person["sex"], "nationality": "Moçambicana",
            "id_number": "QATESTE" + digits(record["phone"])[-6:], "expires_at": expires,
            "street": "Avenida de Teste, 1", "city": "Maputo", "country": "MZ", "postal_code": "1100"}


def ensure_person(kc, reviewer, person, state):
    record = state["people"][person["key"]]
    token = ensure_signed_up(kc, person, record, state)
    status, me = ko(token, "GET", "/v1/customers/me")
    if status != 200:
        raise Stop(f"GET /v1/customers/me: {status} {why(me)}")
    account_id = record["account_id"] = me["id"]
    kyc = me.get("kyc_status")
    if person["tier"] == "verified" and kyc != "verified":
        if reviewer is None:
            raise Stop("the development admin could not sign in; KYC not reviewed")
        if kyc in ("lite", "initiated"):
            submit_kyc(token, account_id)
        elif kyc not in ("under_review", "submitted"):
            raise Stop(f"KYC is {kyc}; a fixture in that state needs a new number (QA_FIXTURE_PHONES)")
        reviewer.approve(account_id, transcription(person, record))
        ok(f"{person['key']}: KYC approved")
    record["conta_pagamento"] = wait_usable(token, account_id, person["key"])
    record["tier"] = person["tier"]
    save(state)
    ok(f"{person['key']}: {person['tier']}, Conta Pagamento usable")
    return token


# ── the business ─────────────────────────────────────────────────────────────

def owned_business(token):
    status, me = ko(token, "GET", "/v1/me")
    for m in me.get("memberships", []) if status == 200 else []:
        account = m.get("account") or {}
        if account.get("type") == "business" and (m.get("role") or {}).get("owner") and \
                account.get("name") in (BUSINESS["legal_name"], BUSINESS["short_name"]):
            return account
    return None


def ensure_business(owner_token, owner, reviewer, state):
    record = state.setdefault("business", {})
    owner_id = owner["account_id"]
    found = owned_business(owner_token)
    details = {"legal_name": BUSINESS["legal_name"], "short_name": BUSINESS["short_name"], "country": "MZ",
               "state_province": "Maputo Cidade", "city": "Maputo", "line": "Avenida de Teste, 2",
               "registration_number": BUSINESS["registration"], "vat_number": BUSINESS["nuit"]}
    if found is None:
        status, out = ko(owner_token, "POST", f"/v1/customers/{owner_id}/business", {
            "description": "QA fixture business", "domain": "qa.example.test", "business_type": BUSINESS["plan"],
            "person_of_contact": {"first_name": "Paulo", "last_name": "Pagador Teste", "phone_number": owner["phone"],
                                  "email": BUSINESS["email"]},
            "business_details": details,
            "first_collection_method": {"collection_method_type": "mobile_wallet", "mobile_wallet_type": "kulpay",
                                        "phone_number": owner["phone"]}}, scope=owner_id)
        if status >= 300:
            raise Stop(f"business not started: {status} {why(out)}")
        found = {"id": out["id"], "kyc_status": out.get("kyc_status")}
    business_id = record["account_id"] = found["id"]
    record.update(name=BUSINESS["short_name"], owner="payer")
    save(state)
    if found.get("kyc_status") in (None, "", "initiated"):
        status, plans = ko(owner_token, "GET", "/v1/business-plans")
        plan = next((p for p in plans.get("plans", []) if p.get("id") == BUSINESS["plan"]), {}) if status == 200 else {}
        for doc in plan.get("required_documents") or ["NUIT", "REGISTRATION_NUMBER"]:
            data = png(400, 560, (240, 240, 240))
            status, out = ko(owner_token, "POST", f"/v1/customers/{owner_id}/business/{business_id}/files", {
                "document_type": doc, "file": {"filename": doc.lower() + ".png", "content_type": "image/png",
                                               "size": str(len(data)), "data": base64.b64encode(data).decode()}}, scope=business_id)
            if status >= 300:
                raise Stop(f"business document {doc} not uploaded: {status} {why(out)}")
        status, out = ko(owner_token, "PUT", f"/v1/customers/{owner_id}/business/{business_id}/finish", {}, scope=business_id)
        if status >= 300:
            raise Stop(f"business not submitted: {status} {why(out)}")
        found["kyc_status"] = out.get("kyc_status", "under_review")
    if found.get("kyc_status") != "verified":
        status, progress = ko(owner_token, "GET", "/v1/verification", scope=business_id)
        if not (status == 200 and progress.get("stage") == "approved"):
            if reviewer is None:
                raise Stop("the development admin could not sign in; business not reviewed")
            reviewer.approve(business_id)
            ok("business: approved")
    record["conta_pagamento"] = wait_usable(owner_token, business_id, "the business")
    save(state)
    ok(f"business: {BUSINESS['short_name']}, Conta Pagamento usable")
    return business_id


# ── the restricted role ──────────────────────────────────────────────────────

def ensure_restricted_member(owner_token, account_id, member_token, member, where, state):
    """ROLE on account_id, held by the member through an accepted invitation."""
    status, me = ko(member_token, "GET", "/v1/me")
    held = next((m for m in me.get("memberships", []) if (m.get("account") or {}).get("id") == account_id), None) \
        if status == 200 else None
    roles = state.setdefault("restricted_roles", {})
    if held:
        roles[where] = {"account_id": account_id, "role": (held.get("role") or {}).get("name", "")}
        save(state)
        ok(f"member: already in {where}'s team")
        return
    status, out = ko(owner_token, "GET", "/v1/authorization/roles?limit=100", scope=account_id)
    if status != 200:
        raise Stop(f"{where}'s roles not listed: {status} {why(out)}")
    role = next((r for r in out.get("roles", []) if r.get("name") == ROLE["name"]), None)
    if role is None:
        status, role = ko(owner_token, "POST", "/v1/authorization/roles", {
            "name": ROLE["name"], "description": ROLE["description"], "template": ROLE["template"]}, scope=account_id)
        if status >= 300:
            raise Stop(f"restricted role not made on {where}: {status} {why(role)}")
    status, out = ko(owner_token, "GET", f"/v1/accounts/{account_id}/invites", scope=account_id)
    pending = [i for i in out.get("invites", []) if i.get("phone_number") == member["phone"] and i.get("status") == "pending"] \
        if status == 200 else []
    if not pending:
        status, out = ko(owner_token, "POST", f"/v1/accounts/{account_id}/invites",
                         {"phone_number": member["phone"], "role_id": role["id"]}, scope=account_id)
        if status >= 300:
            raise Stop(f"member not invited to {where}: {status} {why(out)}")
    status, out = ko(member_token, "GET", "/v1/me/invites")
    invite = next((i for i in out.get("invites", []) if i.get("account_id") == account_id), None) if status == 200 else None
    if invite is None:
        raise Stop(f"the member does not see the invitation to {where}")
    status, out = ko(member_token, "POST", f"/v1/invites/{invite['id']}/accept", {"token": ""})
    if status >= 300:
        raise Stop(f"invitation to {where} not accepted: {status} {why(out)}")
    roles[where] = {"account_id": account_id, "role": ROLE["name"], "role_id": role["id"]}
    save(state)
    ok(f"member: {ROLE['name']} in {where}'s team")


# ── money ────────────────────────────────────────────────────────────────────

def available(token, account_id, product_id):
    status, out = ko(token, "GET", f"/v1/accounts/{account_id}/products/{product_id}/balance", scope=account_id)
    if status != 200:
        raise Stop(f"balance not read: {status} {why(out)}")
    return int(out.get("available_minor") or out.get("amount_minor") or 0)


def top_up(token, account_id, product_id, amount, phone):
    """One M-Pesa top-up through the simulator; True once applied."""
    request("POST", SIMULATOR + "/api/accounts", {"rail": "mpesa", "payer": digits(phone), "balance": "10000000.00",
                                                  "name": "QA Teste"})
    status, tu = ko(token, "POST", f"/v1/accounts/{account_id}/products/{product_id}/top-ups", {
        "amount_minor": str(amount), "currency": "MZN", "idempotency_key": str(uuid.uuid4()),
        "method": "mpesa", "payer_phone": digits(phone)}, scope=account_id)
    if status >= 300:
        raise Stop(f"top-up refused: {status} {why(tu)}")
    approved = set()

    def check():
        status, out = ko(token, "GET", f"/v1/accounts/{account_id}/top-ups/{tu['transaction_id']}", scope=account_id)
        state = out.get("status") if status == 200 else ""
        if state == "applied":
            return True
        if state in ("rejected", "action_required"):
            raise Stop(f"top-up {state} ({out.get('collection_status')})")
        status, sim = request("GET", SIMULATOR + "/api/state")
        for p in sim.get("prompts", []) if status == 200 else []:
            if p.get("state") == "pending" and p.get("rail") == "mpesa" and p.get("operation") == "charge" and \
                    p.get("payer") == digits(phone) and int(p.get("amount_minor", 0)) == amount and p["id"] not in approved:
                request("POST", f"{SIMULATOR}/api/prompts/{p['id']}/action", {"action": "approve"})
                approved.add(p["id"])
        return None

    return wait("a top-up", check)


def fund(token, account_id, product_id, target, phone, what):
    if target <= 0:
        return
    have = available(token, account_id, product_id)
    made = 0
    while have < target and made < TOP_UPS_PER_RUN:
        top_up(token, account_id, product_id, min(TOP_UP_STEP_MINOR, target - have), phone)
        made += 1
        have = available(token, account_id, product_id)
    if have < target:
        warn(f"{what}: {have / 100:.2f} of {target / 100:.2f} MZN after {made} top-ups (run again)")
    else:
        ok(f"{what}: at least {target / 100:.2f} MZN ({made} top-ups now)")


def ensure_budget(token, record, state):
    account_id = record["account_id"]
    status, out = ko(token, "GET", f"/v1/accounts/{account_id}/budgets", scope=account_id)
    if status != 200:
        raise Stop(f"budgets not listed: {status} {why(out)}")
    budget = next((b for b in out.get("budgets", []) if b.get("name") == BUDGET["name"] and b.get("status") != "closed"), None)
    if budget is None:
        status, budget = ko(token, "POST", f"/v1/accounts/{account_id}/budgets", {
            "name": BUDGET["name"], "amount_minor": str(BUDGET["amount_minor"]), "auth_mode": "app",
            "pin": record["pin"]}, scope=account_id)
        if status >= 300:
            raise Stop(f"Mo Budget not made: {status} {why(budget)}")
        budget = budget.get("budget", budget)
    record["second_product"] = {"kind": "mo_budget", "id": budget.get("id", ""), "handle": budget.get("handle", "")}
    save(state)
    ok("payer: second product, a Mo Budget")


def cancel_open_requests(token, account_id):
    cancelled = 0
    for kind in ("", "personal"):
        status, out = ko(token, "GET", f"/v1/accounts/{account_id}/orientu/requests?role=mine&status=open&limit=100"
                         + (f"&kind={kind}" if kind else ""), scope=account_id)
        for r in out.get("requests", []) if status == 200 else []:
            if r.get("status") != "open":
                continue
            status, res = ko(token, "POST", f"/v1/accounts/{account_id}/orientu/requests/{r['id']}:cancel", {}, scope=account_id)
            if status < 300:
                cancelled += 1
            else:
                warn(f"request {r['id']} not cancelled: {status} {why(res)}")
    ok(f"requester: {cancelled} open Orientu requests cancelled")


# ── the run ──────────────────────────────────────────────────────────────────

def phones():
    given = [p.strip() for p in os.environ.get("QA_FIXTURE_PHONES", "").split(",") if p.strip()]
    if given and len(given) != len(PEOPLE):
        raise SystemExit(f"QA_FIXTURE_PHONES needs {len(PEOPLE)} numbers ({', '.join(p['key'] for p in PEOPLE)})")
    return given or DEFAULT_PHONES


def step(what, fn, *args):
    try:
        return fn(*args)
    except Stop as error:
        warn(f"{what}: {error}")
        return None


def admin_reviewer():
    try:
        import dev_rules  # the development admin's sign-in (WORKFORCE_ISSUER, DEV_ADMIN_*)
        return Reviewer(dev_rules.sign_in())
    except (SystemExit, Stop, OSError, KeyError) as error:
        warn(f"development admin: {error}")
        return None


def run(reset=False):
    state = load()
    state.setdefault("people", {})
    state["about"] = ("QA test accounts (Orientu OR-2), made by tools/dev_qa_fixtures.py. Sign in on USSD or with the "
                      "ussd-gateway client's password grant (number, PIN); the web asks the number's SMS code.")
    for person, phone in zip(PEOPLE, phones()):
        record = state["people"].setdefault(person["key"], {})
        if record.get("phone") not in (None, phone):
            record.clear()  # another number: start that person over
        record.update(label=person["label"], phone=phone)
    save(state)
    kc = Keycloak()
    reviewer = admin_reviewer()
    tokens = {}
    for person in PEOPLE:
        token = step(person["key"], ensure_person, kc, reviewer, person, state)
        if token:
            tokens[person["key"]] = token
    people = state["people"]
    business_id = None
    if "payer" in tokens:
        business_id = step("business", ensure_business, tokens["payer"], people["payer"], reviewer, state)
    if reset and "requester" in tokens:
        step("reset", cancel_open_requests, tokens["requester"], people["requester"]["account_id"])
    for person in PEOPLE:
        if person["key"] in tokens:
            record = people[person["key"]]
            step(f"{person['key']}'s balance", fund, tokens[person["key"]], record["account_id"],
                 record["conta_pagamento"]["id"], person["fund_minor"], record["phone"], person["key"])
    if business_id:
        step("business balance", fund, tokens["payer"], business_id, state["business"]["conta_pagamento"]["id"],
             BUSINESS["fund_minor"], people["payer"]["phone"], "business")
    if "payer" in tokens:
        step("payer's Mo Budget", ensure_budget, tokens["payer"], people["payer"], state)
    if "member" in tokens:
        if business_id:
            step("restricted role (business)", ensure_restricted_member, tokens["payer"], business_id,
                 tokens["member"], people["member"], "business", state)
        if "requester" in tokens:
            step("restricted role (requester)", ensure_restricted_member, tokens["requester"],
                 people["requester"]["account_id"], tokens["member"], people["member"], "requester", state)
    for key, token in tokens.items():
        account_id = people[key]["account_id"]
        status, out = ko(token, "GET", f"/v1/accounts/{account_id}/limits", scope=account_id)
        if status == 200 and out.get("daily_in"):
            left = int(out["daily_in"].get("remaining_minor") or 0)
            people[key]["daily_in_left_minor"] = left
            print(f"  note  {key}: {left / 100:.2f} MZN of daily-in left today (Maputo day)")
    save(state)
    print(f"QA test accounts: credentials in {SHOWN_AS or FILE} (mode 0600; not printed)")
    if WARNINGS:
        print(f"{len(WARNINGS)} fixture step(s) not done; run again (make qa-fixtures) once fixed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run(reset="reset" in sys.argv[1:]))
