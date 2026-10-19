"""Operator roles through KulOffice's role API (bin/kulpay operator-roles).

The same audited calls the back office's Roles screen makes, as the env admin
(HTTP Basic). KO_URL, KO_USER and KO_PASS come from bin/kulpay.

    operator_roles.py                 list the roles and what each is missing
    operator_roles.py grant ROLE...   give each role every operator permission
                                      KulOffice offers now (new releases add some)
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ["KO_URL"]
AUTH = base64.b64encode(f'{os.environ["KO_USER"]}:{os.environ["KO_PASS"]}'.encode()).decode()


def call(method, path, body=None):
    request = urllib.request.Request(
        URL + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Basic " + AUTH, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        hint = " (is KULOFFICE_ADMIN_BASIC_ENABLED=true?)" if e.code == 401 else ""
        sys.exit(f"error: {method} {path}: {e.code}{hint} {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        sys.exit(f"error: KulOffice at {URL} did not answer: {e.reason}")


def keys(permissions):
    return {(p["resource"], p["action"]) for p in permissions or []}


def main(args):
    catalogue = keys(call("GET", "/v1/operator-permissions").get("permissions"))
    roles = call("GET", "/v1/operator-roles").get("roles") or []
    if not args:
        for role in roles:
            missing = catalogue - keys(role.get("permissions"))
            print(f'{role["name"]!r}: {len(catalogue) - len(missing)}/{len(catalogue)} permissions'
                  + (f', missing {", ".join(sorted(f"{r}:{a}" for r, a in missing))}' if missing else ""))
        return
    if args[0] != "grant" or len(args) < 2:
        sys.exit("usage: kulpay operator-roles [grant ROLE...]")
    for name in args[1:]:
        role = next((r for r in roles if r["name"] == name), None)
        if role is None:
            sys.exit(f"error: no role named {name!r} (kulpay operator-roles lists them)")
        missing = catalogue - keys(role.get("permissions"))
        if not missing:
            print(f"{name!r}: already has all {len(catalogue)} permissions")
            continue
        # Every permission in the catalogue: the role's current ones are all
        # in it (KulOffice refuses unknown ones), so this only adds.
        permissions = [{"resource": r, "action": a} for r, a in sorted(catalogue | keys(role.get("permissions")))]
        updated = call("POST", f'/v1/operator-roles/{role["id"]}', {
            "id": role["id"],
            "description": role.get("description", ""),
            "permissions": permissions,
            "reason": "kulpay operator-roles grant: every operator permission (development stack)",
        })
        left = catalogue - keys(updated.get("permissions"))
        added = ", ".join(sorted(f"{r}:{a}" for r, a in missing))
        print(f"{name!r}: added {added}" if not left else f"{name!r}: NOT all added, still missing {sorted(left)}")


if __name__ == "__main__":
    main(sys.argv[1:])
