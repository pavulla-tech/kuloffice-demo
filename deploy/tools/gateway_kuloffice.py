"""Provision Gateway event delivery to KulOffice without printing secrets.

Stdout is deliberately machine-only KEY=value output captured by the host
wrapper. Human progress goes to stderr. Existing endpoints are reused; if an
existing endpoint's one-time secret is absent from the deployment environment,
the helper rolls it with a grace period and returns the replacement.
"""

import json
import os
import sys
import urllib.error
import urllib.request


BASE = os.environ.get("GATEWAY_MANAGEMENT_URL", "http://gateway:9091/v1").rstrip("/")
ACCOUNT_KEY = os.environ.get("GATEWAY_API_KEY", "")
ADMIN_KEY = os.environ.get("GATEWAY_ADMIN_KEY", "")
MODE = os.environ.get("GATEWAY_MODE", "live")
URL = os.environ.get("GATEWAY_KULOFFICE_EVENT_URL", "http://kuloffice:8080/v1/integrations/kulpay-gateway/events")
HAVE_INCOMING_SECRET = bool(os.environ.get("KULOFFICE_INCOMING_TRANSFERS_WEBHOOK_SECRETS", "").strip())
HAVE_SERVICE_SECRET = bool(os.environ.get("KULOFFICE_PAYMENT_ACCEPTANCE_WEBHOOK_SECRETS", "").strip())
# KulOffice's account endpoint: its incoming transfers, and its businesses'
# bills, KulOffice being their Gateway biller.
ACCOUNT_EVENTS = ["incoming_transfer.*", "bill_invoice.*", "bill_remittance.*"]
ACCOUNT_ID = os.environ.get("GATEWAY_ACCOUNT_ID", "")
# GATEWAY_CASH_IN_INCOMING=1 (make cash-deposits): a cash deposit a partner
# takes for one of KulOffice's references is also recorded as an incoming
# transfer to KulOffice, which credits the customer.
CASH_IN_INCOMING = os.environ.get("GATEWAY_CASH_IN_INCOMING", "") == "1"


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


def main():
    if not ACCOUNT_KEY or not ADMIN_KEY:
        sys.exit("GATEWAY_API_KEY and GATEWAY_ADMIN_KEY are required")
    if MODE not in ("live", "test"):
        sys.exit("GATEWAY_MODE must be live or test")
    incoming = ensure_incoming_endpoint()
    service = ensure_service_sink()
    if CASH_IN_INCOMING:
        ensure_cash_in_incoming()
    if incoming:
        print("KULOFFICE_INCOMING_TRANSFERS_WEBHOOK_SECRETS=" + incoming)
    if service:
        print("KULOFFICE_PAYMENT_ACCEPTANCE_WEBHOOK_SECRETS=" + service)


if __name__ == "__main__":
    main()
