"""Warns when KulOffice's Gateway account has no live M-Pesa or e-Mola binding.

The real connectors are set by hand in the Gateway dashboard (Connectors, live
mode; kuloffice Manual 08, step 8): their credentials never live in the kit. A
Gateway reset loses them, so bin/kulpay provision runs this to say so. It only
reads: the bindings' method, driver and state (the Gateway never returns their
credentials). Exit 0 always, unless the Gateway cannot be asked.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("GATEWAY_MANAGEMENT_URL", "http://gateway:9091/v1").rstrip("/")
METHODS = ("mpesa", "emola")


def bindings():
    account = os.environ.get("GATEWAY_ACCOUNT_ID", "").strip()
    key = os.environ.get("GATEWAY_ADMIN_KEY", "").strip()
    if not account or not key:
        sys.exit("GATEWAY_ACCOUNT_ID and GATEWAY_ADMIN_KEY are required")
    query = urllib.parse.urlencode({"mode": "live", "account_id": account})
    req = urllib.request.Request(f"{BASE}/admin/connectors?{query}", headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read() or b"{}").get("data") or []
    except (urllib.error.URLError, OSError, ValueError) as error:
        sys.exit(f"the Gateway's live connectors could not be read: {getattr(error, 'code', '') or error}")


def warnings(rows, simulated):
    out = []
    for method in METHODS:
        live = [r for r in rows if r.get("method") == method and r.get("enabled")]
        if not live:
            out.append(f"warning: no live {method} binding on KulOffice's Gateway account: set the real one in the Gateway "
                       "dashboard (Connectors, live; Manual 08 step 8)")
        elif method in simulated:
            out.append(f"warning: live {method} is the PSP simulator's (SIMULATOR_BIND_METHODS lists it): real {method} "
                       "needs the dashboard, and SIMULATOR_BIND_METHODS without it")
    return out


def main():
    simulated = {m.strip() for m in os.environ.get("SIMULATOR_BIND_METHODS", "").split(",") if m.strip()}
    found = warnings(bindings(), simulated)
    for line in found:
        print("  " + line)
    if not found:
        print("  ok  live M-Pesa and e-Mola bindings on KulOffice's Gateway account")


if __name__ == "__main__":
    main()
