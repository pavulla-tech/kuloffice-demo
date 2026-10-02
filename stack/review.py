"""Decides an account's KYC review as the demo reviewer, through the review-case API.

  make review ACCOUNT=acc_...                        approve
  make review ACCOUNT=acc_... OUTCOME=reject MESSAGE="Documento ilegível"
  make review ACCOUNT=acc_... OUTCOME=request_documents MESSAGE="..." DOCS="REGISTRATION_NUMBER:NUEL legível"

What a reviewer would do: sign in to the workforce realm (through the token
panel's password sign-in, which knows how to drive Keycloak's form), find the
account's open case, claim it unless they already own it, and decide it.

Runs on the host, against the stack's published ports.
"""
import json
import os
import sys
import urllib.error
import urllib.request

PANEL = os.environ.get("PANEL_URL", "http://localhost:8765").rstrip("/")
API = os.environ.get("KULOFFICE_URL", "http://localhost:18080").rstrip("/")
# As kuloffice knows the workforce issuer: from inside the stack, where the
# panel signs in too.
ISSUER = os.environ["WORKFORCE_ISSUER"]
CLIENT = os.environ.get("WORKFORCE_PANEL_CLIENT", "kulpay-token-panel")
EMAIL, PASSWORD = os.environ["REVIEWER_EMAIL"], os.environ["REVIEWER_PASSWORD"]
ACCOUNT = os.environ.get("ACCOUNT", "").strip()
OUTCOME = os.environ.get("OUTCOME", "approve").strip() or "approve"
REASON = os.environ.get("REASON", "").strip() or f"local stack: {OUTCOME} by make review"
MESSAGE = os.environ.get("MESSAGE", "").strip()
DOCS = os.environ.get("DOCS", "").strip()


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
        sys.exit(f"{what} failed: {status} {out.get('message', out)}")
    return out


def documents():
    """DOCS="TYPE:description;TYPE:description" -> [{type, description}]."""
    out = []
    for item in filter(None, (d.strip() for d in DOCS.split(";"))):
        kind, _, description = item.partition(":")
        if not description.strip():
            sys.exit(f'DOCS item "{item}" is not TYPE:description')
        out.append({"type": kind.strip(), "description": description.strip()})
    return out


def main():
    if not ACCOUNT:
        sys.exit("usage: make review ACCOUNT=acc_... [OUTCOME=approve|reject|request_documents] [MESSAGE=...] [DOCS=...]")
    if OUTCOME not in ("approve", "reject", "request_documents"):
        sys.exit(f"OUTCOME must be approve, reject or request_documents, not {OUTCOME}")
    if OUTCOME == "reject" and not MESSAGE:
        sys.exit("a rejection needs MESSAGE, the reason the customer is shown")
    docs = documents()
    if (OUTCOME == "request_documents") != bool(docs):
        sys.exit("request_documents needs DOCS, and only it takes them")

    tokens = must(call("POST", PANEL + "/login/password",
                       {"issuer": ISSUER, "client": CLIENT, "username": EMAIL, "password": PASSWORD}),
                  "reviewer sign-in")
    token = tokens.get("access_token") or sys.exit(f"reviewer sign-in returned no token: {tokens}")
    me = must(call("GET", API + "/v1/operators/me", token=token), "who am I")
    me_id = me.get("id") or me.get("operator", {}).get("id")

    case = None
    for queue in ("mine", "unassigned"):
        page = 1
        while case is None:
            out = must(call("GET", f"{API}/v1/review-cases?queue={queue}&page={page}&limit=100", token=token),
                       f"list {queue} cases")
            case = next((c for c in out.get("cases", []) if c.get("account_id") == ACCOUNT), None)
            if not out.get("has_more"):
                break
            page += 1
        if case:
            break
    if not case:
        sys.exit(f"no open case for {ACCOUNT} that {EMAIL} may take (already decided, or owned by someone else)")
    print(f"case {case['id']} ({case.get('kind')}, {case.get('status')}) for {ACCOUNT}")

    if case.get("owner_id") != me_id:
        case = must(call("POST", f"{API}/v1/review-cases/{case['id']}/actions",
                         {"action": "claim", "version": int(case["version"]), "reason": REASON}, token),
                    "claim case")
        print(f"claimed by {EMAIL}")

    body = {"outcome": OUTCOME, "reason": REASON, "version": int(case["version"])}
    if MESSAGE:
        body["customer_message"] = MESSAGE
    if docs:
        body["documents"] = docs
    status, out = call("POST", f"{API}/v1/review-cases/{case['id']}/decision", body, token)
    if status == 503:
        # Approval is recorded; provisioning the customer failed and is retried.
        print(f"{OUTCOME} recorded, provisioning pending: {out.get('message', out)}")
        print(f"retry: POST /v1/review-cases/{case['id']}/decision/retry (kuloffice also resumes it)")
        return
    if status >= 300:
        hint = " - the identity details are missing or expired; transcribe them first" \
            if "detail" in str(out.get("message", "")).lower() else ""
        sys.exit(f"decision failed: {status} {out.get('message', out)}{hint}")
    print(f"{OUTCOME}: case now {out.get('status')}")


if __name__ == "__main__":
    main()
