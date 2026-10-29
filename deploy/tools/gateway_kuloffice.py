"""Provision Gateway event delivery to KulOffice without printing secrets,
and KulOffice's own Gateway biller (created and activated when missing).

Stdout is deliberately machine-only KEY=value output captured by the host
wrapper. Human progress goes to stderr. Existing endpoints are reused; if an
existing endpoint's one-time secret is absent from the deployment environment,
the helper rolls it with a grace period and returns the replacement.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


BASE = os.environ.get("GATEWAY_MANAGEMENT_URL", "http://gateway:9091/v1").rstrip("/")
ACCOUNT_KEY = os.environ.get("GATEWAY_API_KEY", "")
ADMIN_KEY = os.environ.get("GATEWAY_ADMIN_KEY", "")
MODE = os.environ.get("GATEWAY_MODE", "live")
URL = os.environ.get("GATEWAY_KULOFFICE_EVENT_URL", "http://kuloffice:8080/v1/integrations/kulpay-gateway/events")
HAVE_INCOMING_SECRET = bool(os.environ.get("KULOFFICE_INCOMING_TRANSFERS_WEBHOOK_SECRETS", "").strip())
HAVE_SERVICE_SECRET = bool(os.environ.get("KULOFFICE_PAYMENT_ACCEPTANCE_WEBHOOK_SECRETS", "").strip())
# KulOffice's account endpoint: its incoming transfers, its businesses'
# bills (KulOffice being their Gateway biller), its payers' biller
# accounts (other billers offered to KulPay customers; their bills are
# bill_invoice.delivered and .reminded), and the billers it provisions as
# LSPs (their technical status and technical contact, KO-1/KO-2).
ACCOUNT_EVENTS = ["incoming_transfer.*", "bill_invoice.*", "bill_remittance.*", "bill_subscription.*",
                  "biller.integration_status", "biller.technical_contact_replaced"]
ACCOUNT_ID = os.environ.get("GATEWAY_ACCOUNT_ID", "")
# A cash deposit a partner takes for one of KulOffice's references is also
# recorded as an incoming transfer to KulOffice, which credits the customer.
# A Gateway setting, so a Gateway reset loses it: every run restores it (dev:
# nothing off). GATEWAY_CASH_IN_INCOMING=0 leaves it alone.
CASH_IN_INCOMING = os.environ.get("GATEWAY_CASH_IN_INCOMING", "").strip() != "0"
# GATEWAY_BILLER_PROVISIONING=1 (make gateway-billers): the partners key
# KulOffice provisions approved billers with (service:partners:write, an
# operator-only scope, issued by the admin key on KulOffice's own account).
BILLER_PROVISIONING = os.environ.get("GATEWAY_BILLER_PROVISIONING", "") == "1"
HAVE_PARTNERS_KEY = bool(os.environ.get("KULOFFICE_BILLER_PROVISIONING_GATEWAY_API_KEY", "").strip())
# KulOffice's own biller: businesses' bills and payment requests are
# presented at the Gateway under it (BillerByTenant on KulOffice's account);
# without it POST /v1/biller/invoices answers 403 not_a_biller. A Gateway
# reset loses it, so every run recreates and activates it when missing.
# Activation is maker/checker: the admin key requests, the checker approves.
CHECKER_KEY = os.environ.get("GATEWAY_CHECKER_KEY", "")
BILLER_CODE = os.environ.get("GATEWAY_KULOFFICE_BILLER_CODE", "").strip().upper() or "KULPAY"
BILLER = {
    "code": BILLER_CODE,
    "name": "KulPay",
    "category": "other",
    "country": "MZ",
    "support_email": "developers@pavulla.com",
    "presentment_modes": ["push"],
    "remit_bank": os.environ.get("GATEWAY_KULOFFICE_REMIT_BANK", "").strip() or "FNB",
    "remit_account": os.environ.get("GATEWAY_KULOFFICE_REMIT_ACCOUNT", "").strip() or "0028000090002922",
    "remit_frequency": os.environ.get("GATEWAY_KULOFFICE_REMIT_FREQUENCY", "").strip() or "daily",
}
# The Gateway activates a biller only with an enabled product whose amount the
# biller presents: KulOffice's invoices.
BILLER_PRODUCT = {
    "code": "FATURA",
    "name": "Factura",
    "shape": "postpaid",
    "currency": "MZN",
    "amount_rule": "presented",
    "reference_label": "Número da factura",
    "reference_pattern": "^[A-Z0-9-]{3,40}$",
    "reference_example": "F-20261029-1631",
    "model": "agent",
    "fee_bearer": "biller",
    "enabled": True,
}


def request(method, path, key, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + key)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} failed: {error.code} {detail}") from error


def data_rows(body):
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        return body["data"]
    return []


def ensure_incoming_endpoint():
    _, listed = request("GET", "/webhook-endpoints", ACCOUNT_KEY)
    rows = data_rows(listed)
    def receives_incoming(endpoint):
        types = endpoint.get("event_types") or []
        return "incoming_transfer.*" in types or "*" in types

    existing = next(
        (
            endpoint
            for endpoint in rows
            if endpoint.get("mode") == MODE and endpoint.get("url") == URL and endpoint.get("status") == "active" and receives_incoming(endpoint)
        ),
        None,
    )
    if existing is None:
        stale = next(
            (
                endpoint
                for endpoint in rows
                if endpoint.get("mode") == MODE and endpoint.get("status") == "active" and receives_incoming(endpoint)
            ),
            None,
        )
        if stale is not None:
            raise RuntimeError(
                "an active incoming-transfer endpoint already targets "
                + str(stale.get("url"))
                + "; remove or migrate it explicitly before provisioning "
                + URL
            )
        _, created = request(
            "POST",
            "/webhook-endpoints",
            ACCOUNT_KEY,
            {"url": URL, "event_types": ACCOUNT_EVENTS},
        )
        secret = created.get("secret", "") if isinstance(created, dict) else ""
        if not secret:
            raise RuntimeError("Gateway created the incoming-transfer endpoint without returning its secret")
        print("incoming-transfer endpoint created", file=sys.stderr)
        return secret
    print("incoming-transfer endpoint already present", file=sys.stderr)
    types = existing.get("event_types") or []
    if "*" not in types and any(t not in types for t in ACCOUNT_EVENTS):
        request("PATCH", f"/webhook-endpoints/{existing['id']}", ACCOUNT_KEY,
                {"event_types": sorted(set(types) | set(ACCOUNT_EVENTS))})
        print("incoming-transfer endpoint now also takes the bills' events", file=sys.stderr)
    if HAVE_INCOMING_SECRET:
        return ""
    _, rolled = request(
        "POST",
        f"/webhook-endpoints/{existing['id']}/roll-secret",
        ACCOUNT_KEY,
        {"grace": "24h"},
    )
    endpoint = rolled.get("endpoint", {}) if isinstance(rolled, dict) else {}
    secret = endpoint.get("secret", "")
    if not secret:
        raise RuntimeError("Gateway rolled the incoming-transfer endpoint without returning its secret")
    print("incoming-transfer secret recovered by a 24h grace rotation", file=sys.stderr)
    return secret


def ensure_service_sink():
    _, listed = request("GET", "/admin/service-event-sinks", ADMIN_KEY)
    existing = next((sink for sink in data_rows(listed) if sink.get("mode") == MODE), None)
    if existing is None:
        _, created = request(
            "POST",
            "/admin/service-event-sinks",
            ADMIN_KEY,
            {"mode": MODE, "url": URL, "event_types": ["payment.*"]},
        )
        secret = created.get("secret", "") if isinstance(created, dict) else ""
        if not secret:
            raise RuntimeError("Gateway created the service event sink without returning its secret")
        print("platform payment-event sink created", file=sys.stderr)
        return secret
    if existing.get("url") != URL or not existing.get("enabled", False) or "payment.*" not in (existing.get("event_types") or []):
        request(
            "PATCH",
            f"/admin/service-event-sinks/{existing['id']}",
            ADMIN_KEY,
            {"url": URL, "event_types": ["payment.*"], "enabled": True},
        )
        print("platform payment-event sink updated", file=sys.stderr)
    else:
        print("platform payment-event sink already present", file=sys.stderr)
    if HAVE_SERVICE_SECRET:
        return ""
    _, rolled = request(
        "POST",
        f"/admin/service-event-sinks/{existing['id']}/roll-secret",
        ADMIN_KEY,
        {"grace": "24h"},
    )
    secret = rolled.get("secret", "") if isinstance(rolled, dict) else ""
    if not secret:
        raise RuntimeError("Gateway rolled the service event sink without returning its secret")
    print("service-event secret recovered by a 24h grace rotation", file=sys.stderr)
    return secret


def ensure_cash_in_incoming():
    if not ACCOUNT_ID:
        raise RuntimeError("GATEWAY_ACCOUNT_ID is required to take cash deposits")
    request("PUT", f"/admin/accounts/{ACCOUNT_ID}/cash-in-incoming", ADMIN_KEY, {"enabled": True})
    print("cash deposits for KulOffice's references are recorded as incoming transfers", file=sys.stderr)


def ensure_partners_key():
    """Issues KulOffice's partners key once; an existing one is kept."""
    if HAVE_PARTNERS_KEY:
        print("partners key already set", file=sys.stderr)
        return ""
    if not ACCOUNT_ID:
        raise RuntimeError("GATEWAY_ACCOUNT_ID is required to issue the partners key")
    _, created = request(
        "POST",
        f"/admin/accounts/{ACCOUNT_ID}/keys",
        ADMIN_KEY,
        {"name": "kuloffice-partners", "scopes": ["service:partners:write"]},
    )
    key = created.get("key", {}) if isinstance(created, dict) else {}
    secret = key.get("secret", "")
    if not secret:
        raise RuntimeError("Gateway issued the partners key without returning its secret")
    print("partners key issued", file=sys.stderr)
    return secret


def pending_biller_approval(biller_id):
    query = urllib.parse.urlencode({"subject_id": biller_id, "pending": "1"})
    _, listed = request("GET", "/admin/approvals?" + query, ADMIN_KEY)
    row = next((row for row in data_rows(listed) if row.get("kind") == "bill.biller_status"), None)
    return row.get("id", "") if row else ""


def ensure_kuloffice_biller():
    """KulOffice's biller on its own account, active; returns what was done."""
    if not ACCOUNT_ID or not CHECKER_KEY:
        raise RuntimeError("GATEWAY_ACCOUNT_ID and GATEWAY_CHECKER_KEY are required for KulOffice's biller")
    code = BILLER["code"]
    done = []
    try:
        _, current = request("GET", f"/admin/billers/{code}", ADMIN_KEY)
        biller = (current or {}).get("biller") or {}
        products = (current or {}).get("products") or []
    except RuntimeError as error:
        if "failed: 404 " not in str(error):
            raise
        _, biller = request("POST", "/admin/billers", ADMIN_KEY, {**BILLER, "tenant_id": ACCOUNT_ID})
        biller = biller or {}
        products = []
        done.append("created")
    if not biller.get("tenant_id") and biller.get("code"):
        # Made by hand without its organisation (the dashboard's form allows
        # it): KulOffice's code, so it is claimed for KulOffice's account.
        _, biller = request("PATCH", f"/admin/billers/{code}", ADMIN_KEY, {"tenant_id": ACCOUNT_ID})
        biller = biller or {}
        done.append("claimed for KulOffice's account")
    if biller.get("tenant_id") != ACCOUNT_ID:
        raise RuntimeError(
            f"Gateway biller {code} belongs to another account ({biller.get('tenant_id') or 'none'}); "
            "left unchanged. Free the code or set GATEWAY_KULOFFICE_BILLER_CODE"
        )
    if not any(p.get("enabled") and p.get("amount_rule") == "presented" for p in products):
        request("POST", f"/admin/billers/{code}/products", ADMIN_KEY, BILLER_PRODUCT)
        done.append("invoice product added")
    if biller.get("status") != "active":
        if not biller.get("id"):
            raise RuntimeError(f"Gateway returned biller {code} without its id")
        approval_id = pending_biller_approval(biller["id"])
        if not approval_id:
            _, prepared = request("POST", f"/admin/billers/{code}/status", ADMIN_KEY,
                                  {"status": "active", "reason": "KulOffice's own biller (kit provisioning)"})
            approval_id = ((prepared or {}).get("approval") or {}).get("id", "")
            if not approval_id:
                raise RuntimeError(f"Gateway did not return an approval for activating biller {code}")
            done.append("activation requested")
        request("POST", f"/admin/approvals/{approval_id}/decide", CHECKER_KEY,
                {"approve": True, "reason": "KulOffice's own biller (kit provisioning)"})
        done.append("activated")
    summary = ", ".join(done) if done else "already active"
    print(f"KulOffice biller {code}: {summary}", file=sys.stderr)
    return summary


def main():
    if not ACCOUNT_KEY or not ADMIN_KEY:
        sys.exit("GATEWAY_API_KEY and GATEWAY_ADMIN_KEY are required")
    if MODE not in ("live", "test"):
        sys.exit("GATEWAY_MODE must be live or test")
    incoming = ensure_incoming_endpoint()
    service = ensure_service_sink()
    ensure_kuloffice_biller()
    if CASH_IN_INCOMING:
        ensure_cash_in_incoming()
    partners = ensure_partners_key() if BILLER_PROVISIONING else ""
    if incoming:
        print("KULOFFICE_INCOMING_TRANSFERS_WEBHOOK_SECRETS=" + incoming)
    if service:
        print("KULOFFICE_PAYMENT_ACCEPTANCE_WEBHOOK_SECRETS=" + service)
    if partners:
        print("KULOFFICE_BILLER_PROVISIONING_GATEWAY_API_KEY=" + partners)


if __name__ == "__main__":
    main()
