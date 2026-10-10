"""Reviews Conta Pagamento closure requests as the demo reviewer (kuloffice's
workforce product API; the review portal has no closure screen yet).
  make closure                                   list the requests waiting
  make closure ACCOUNT=acc_...                   approve that account's request
  make closure ACCOUNT=acc_... OUTCOME=reject REASON="Saldo por levantar"
Signs in like make review (the token panel's password sign-in), claims the
request unless this reviewer already holds it, then decides it.
"""
import json, os, sys, urllib.error, urllib.request

PANEL = os.environ.get("PANEL_URL", "http://localhost:8765").rstrip("/")
API = os.environ.get("KULOFFICE_URL", "http://localhost:18080").rstrip("/")
ISSUER = os.environ["WORKFORCE_ISSUER"]
CLIENT = os.environ.get("WORKFORCE_PANEL_CLIENT", "kulpay-token-panel")
EMAIL, PASSWORD = os.environ["REVIEWER_EMAIL"], os.environ["REVIEWER_PASSWORD"]
ACCOUNT = os.environ.get("ACCOUNT", "").strip()
OUTCOME = (os.environ.get("OUTCOME", "") or "approve").strip()
REASON = os.environ.get("REASON", "").strip() or f"local stack: {OUTCOME} by make closure"


def call(method, url, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, None if body is None else json.dumps(body).encode(), headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"message": raw.decode(errors="replace")}
    except urllib.error.URLError as e:
        sys.exit(f"{url} unreachable: {e.reason} (is the stack up?)")


def must(result, what):
    status, out = result
    if status >= 300:
        sys.exit(f"{what}: {status} {out.get('message', out)}")
    return out


def main():
    if OUTCOME not in ("approve", "reject"):
        sys.exit("OUTCOME is approve or reject")
    token = must(call("POST", PANEL + "/login/password", {"issuer": ISSUER, "client": CLIENT, "username": EMAIL, "password": PASSWORD}),
                 "reviewer sign-in").get("access_token") or sys.exit("reviewer sign-in returned no token")
    me = must(call("GET", API + "/v1/operators/me", token=token), "who am I")
    me_id = me.get("id") or me.get("operator", {}).get("id")

    waiting = []
    for status in ("awaiting_review", "in_review"):
        waiting += must(call("GET", f"{API}/v1/product-closure-requests?status={status}", token=token), "list requests").get("requests", [])
    owners = {}
    for r in waiting:
        if r["product_id"] not in owners:
            evidence = must(call("GET", f"{API}/v1/workforce/products/{r['product_id']}", token=token), "product evidence")
            owners[r["product_id"]] = evidence.get("product", {}).get("account_id", "")
    if not ACCOUNT:
        if not waiting:
            print("no closure requests waiting")
        for r in waiting:
            print(f"{owners[r['product_id']]}  {r['status']:<15}  {r['id']}  reason: {r.get('reason', '')}")
        return

    request = next((r for r in waiting if owners[r["product_id"]] == ACCOUNT), None)
    if not request:
        sys.exit(f"no closure request waiting for {ACCOUNT} (make closure lists them)")
    if request["status"] == "in_review" and request.get("assigned_reviewer") != me_id:
        sys.exit(f"{request['id']} is claimed by another reviewer")
    if request["status"] == "awaiting_review":
        request = must(call("POST", f"{API}/v1/product-closure-requests/{request['id']}/claim", {"version": request["version"]}, token), "claim")
    decided = must(call("POST", f"{API}/v1/product-closure-requests/{request['id']}/review",
                        {"approve": OUTCOME == "approve", "reason": REASON, "version": request["version"]}, token), OUTCOME)
    print(f"{OUTCOME}: request {decided['id']} is now {decided['status']}"
          + (f" ({decided.get('provider_state')})" if decided.get("provider_state") else ""))


if __name__ == "__main__":
    main()
