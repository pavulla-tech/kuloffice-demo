"""tools/dev_qa_fixtures.py against a fake stack (Keycloak's USSD endpoints,
KulOffice and the simulator behind one fake `request`): what it makes, that a
second run makes nothing new, that the PINs reach only the 0600 file, and
the refusals it reports instead of hiding."""

import contextlib
import io
import json
import os
import pathlib
import stat
import sys
import tempfile
import unittest
import urllib.parse
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import dev_qa_fixtures as fx  # noqa: E402

PHONES = ["+258840000101", "+258840000102", "+258840000103", "+258840000104"]


class FakeStack:
    """Just enough of Keycloak, KulOffice and the simulator."""

    def __init__(self, reject_documents=False):
        self.users = {}            # msisdn digits -> PIN
        self.accounts = {}         # account id -> dict
        self.by_phone = {}         # phone -> personal account id
        self.cases = {}
        self.subs = {}
        self.roles = {}            # account id -> [role]
        self.invites = []
        self.memberships = []      # (phone, account id, role name, owner)
        self.budgets = {}
        self.requests = {"acc_1": [{"id": "orq_1", "status": "open"}, {"id": "orq_2", "status": "closed"}]}
        self.topups = {}
        self.prompts = {}
        self.calls = []
        self.reject_documents = reject_documents
        self.n = 0

    def new_id(self, prefix):
        self.n += 1
        return f"{prefix}_{self.n}"

    # the one entry point the script uses
    def __call__(self, method, url, body=None, form=None, token=None, scope=None, timeout=60):
        parsed = urllib.parse.urlparse(url)
        path, query = parsed.path, dict(urllib.parse.parse_qsl(parsed.query))
        self.calls.append((method, path, body, form, token, scope))
        if path.startswith("/realms/") or path.startswith("/admin/"):
            return self.keycloak(method, path, query, body, form)
        if url.startswith(fx.SIMULATOR):
            return self.simulator(method, path, body)
        return self.kuloffice(method, path, query, body, token, scope)

    # ── Keycloak ──
    def keycloak(self, method, path, query, body, form):
        if path == "/realms/master/protocol/openid-connect/token":
            return 200, {"access_token": "kc-admin"}
        if path.endswith("/clients") and method == "GET":
            return 200, [{"id": "c1", "clientId": "ussd-gateway"}]
        if path.endswith("/client-secret"):
            return 200, {"value": "ussd-secret"}
        if path.endswith("/protocol/openid-connect/token"):
            if form["grant_type"] == "client_credentials":
                return 200, {"access_token": "ussd-service"}
            if self.users.get(form["username"]) != form["password"]:
                return 401, {"error": "invalid_grant"}
            return 200, {"access_token": "tok:+" + form["username"]}
        if path.endswith("/phone-auth/ussd/status"):
            pin = self.users.get(body["msisdn"], "absent")
            return 200, {"state": "new" if pin == "absent" else ("needs_pin" if pin is None else "ready"), "pin_length": 4}
        if path.endswith("/phone-auth/ussd/register"):
            if fx.weak(body["pin"]):
                return 400, {"error": "pin_sequential"}
            self.users[body["msisdn"]] = body["pin"]
            return 201, {"state": "ready"}
        if path.endswith("/users") and method == "GET":
            return 200, [{"id": "u-" + query["username"]}]
        if path.endswith("/reset-password"):
            self.users[path.split("/")[-2][3:].lstrip("+")] = body["value"]
            return 204, {}
        raise AssertionError((method, path))

    # ── simulator ──
    def simulator(self, method, path, body):
        if path == "/api/accounts":
            return 200, {}
        if path == "/api/state":
            return 200, {"prompts": list(self.prompts.values())}
        if path.endswith("/action"):
            prompt = self.prompts[path.split("/")[3]]
            prompt["state"] = "approved"
            self.topups[prompt["tx"]]["status"] = "applied"
            account = self.accounts[self.topups[prompt["tx"]]["account"]]
            account["balance"] += prompt["amount_minor"]
            return 200, prompt
        raise AssertionError((method, path))

    # ── KulOffice ──
    def kuloffice(self, method, path, query, body, token, scope):
        phone = token[4:] if token and token.startswith("tok:") else None
        if path == "/v1/operators/me":
            return 200, {"id": "op_admin"}
        if path == "/v1/customers/me":
            if phone not in self.by_phone:
                aid = self.new_id("acc")
                self.by_phone[phone] = aid
                self.accounts[aid] = {"id": aid, "type": "personal", "kyc": "lite", "phone": phone, "balance": 0,
                                      "cp": "prd_" + aid, "name": phone}
                self.memberships.append((phone, aid, "Owner", True))
            a = self.accounts[self.by_phone[phone]]
            return 200, {"id": a["id"], "kyc_status": a["kyc"], "status": "active"}
        if path == "/v1/me":
            out = []
            for p, aid, role, owner in self.memberships:
                if p == phone:
                    a = self.accounts[aid]
                    out.append({"account": {"id": aid, "type": a["type"], "name": a["name"], "kyc_status": a["kyc"]},
                                "role": {"name": role, "owner": owner}})
            return 200, {"memberships": out}
        if path == "/v1/kyc-submissions" and method == "POST":
            sid = self.new_id("ksub")
            self.subs[sid] = {"state": "document_rejected" if self.reject_documents else "document_approved",
                              "reason": "document_unreadable", "account": scope}
            return 200, {"id": sid, "state": "document_processing"}
        if path.startswith("/v1/kyc-submissions/"):
            sid = path.split("/")[3]
            if path.endswith("/selfie"):
                self.subs[sid]["state"] = "selfie_approved"
                self.accounts[scope]["kyc"] = "under_review"
                cid = self.new_id("case")
                self.cases[cid] = {"id": cid, "account_id": scope, "owner_id": "", "version": "1", "status": "open"}
                return 200, {"id": sid, "state": "selfie_processing"}
            return 200, dict(self.subs[sid], id=sid)
        if path == "/v1/review-cases":
            open_cases = [c for c in self.cases.values() if c["status"] == "open" and
                          (c["owner_id"] == "op_admin") == (query["queue"] == "mine")]
            return 200, {"cases": open_cases, "has_more": False}
        if path.startswith("/v1/review-cases/"):
            case = self.cases[path.split("/")[3]]
            assert int(body["version"]) == int(case["version"]), "stale version"
            case["version"] = str(int(case["version"]) + 1)
            if path.endswith("/actions"):
                case["owner_id"] = "op_admin"
            elif path.endswith("/transcription"):
                case["details"] = body["details"]
            elif path.endswith("/decision"):
                case["status"] = "approved"
                self.accounts[case["account_id"]]["kyc"] = "verified"
            return 200, dict(case)
        if path.startswith("/v1/accounts/") and path.endswith("/products"):
            a = self.accounts[path.split("/")[3]]
            usable = a["kyc"] in ("lite", "verified")
            return 200, {"products": [{"id": a["cp"], "definition_code": "conta_pagamento", "usable": usable, "handle": "kp" + a["id"]}]}
        if path.endswith("/balance"):
            return 200, {"available_minor": str(self.accounts[path.split("/")[3]]["balance"])}
        if path.endswith("/top-ups") and method == "POST":
            tx = self.new_id("tx")
            self.topups[tx] = {"status": "pending", "account": path.split("/")[3]}
            pid = self.new_id("prm")
            self.prompts[pid] = {"id": pid, "state": "pending", "rail": "mpesa", "operation": "charge",
                                 "payer": body["payer_phone"], "amount_minor": int(body["amount_minor"]), "tx": tx}
            return 200, {"transaction_id": tx, "status": "pending"}
        if "/top-ups/" in path:
            return 200, {"status": self.topups[path.split("/")[-1]]["status"]}
        if path.startswith("/v1/customers/") and path.endswith("/business") and method == "POST":
            bid = self.new_id("acc")
            self.accounts[bid] = {"id": bid, "type": "business", "kyc": "initiated", "balance": 0, "cp": "prd_" + bid,
                                  "name": body["business_details"]["legal_name"], "docs": []}
            self.memberships.append((phone, bid, "Owner", True))
            return 200, {"id": bid, "kyc_status": "initiated"}
        if path == "/v1/business-plans":
            return 200, {"plans": [{"id": "pro", "required_documents": ["NUIT", "REGISTRATION_NUMBER"]}]}
        if path.endswith("/files"):
            self.accounts[path.split("/")[5]]["docs"].append(body["document_type"])
            return 200, {}
        if path.endswith("/finish"):
            bid = path.split("/")[5]
            self.accounts[bid]["kyc"] = "under_review"
            cid = self.new_id("case")
            self.cases[cid] = {"id": cid, "account_id": bid, "owner_id": "", "version": "1", "status": "open"}
            return 200, {"kyc_status": "under_review"}
        if path == "/v1/verification":
            return 200, {"stage": "approved" if self.accounts[scope]["kyc"] == "verified" else "in_review"}
        if path == "/v1/authorization/roles":
            if method == "GET":
                return 200, {"roles": self.roles.get(scope, [])}
            role = {"id": self.new_id("rol"), "name": body["name"], "template": body["template"]}
            self.roles.setdefault(scope, []).append(role)
            return 200, role
        if path.endswith("/invites") and path.startswith("/v1/accounts/"):
            aid = path.split("/")[3]
            if method == "GET":
                return 200, {"invites": [i for i in self.invites if i["account_id"] == aid]}
            inv = {"id": self.new_id("inv"), "account_id": aid, "phone_number": body["phone_number"],
                   "role_id": body["role_id"], "status": "pending"}
            self.invites.append(inv)
            return 200, inv
        if path == "/v1/me/invites":
            return 200, {"invites": [i for i in self.invites if i["phone_number"] == phone and i["status"] == "pending"]}
        if path.startswith("/v1/invites/") and path.endswith("/accept"):
            inv = next(i for i in self.invites if i["id"] == path.split("/")[3])
            assert self.accounts[self.by_phone[phone]]["kyc"] == "verified", "an unverified invitee"
            inv["status"] = "accepted"
            role = next(r for r in self.roles[inv["account_id"]] if r["id"] == inv["role_id"])
            self.memberships.append((phone, inv["account_id"], role["name"], False))
            return 200, {}
        if path.endswith("/budgets"):
            aid = path.split("/")[3]
            if method == "GET":
                return 200, {"budgets": self.budgets.get(aid, [])}
            assert body["pin"] == self.users[self.accounts[aid]["phone"].lstrip("+")]
            b = {"id": self.new_id("bud"), "name": body["name"], "handle": "kp.qa", "status": "active"}
            self.budgets.setdefault(aid, []).append(b)
            self.accounts[aid]["balance"] -= int(body["amount_minor"])
            return 201, {"budget": b}
        if "/orientu/requests" in path:
            aid = path.split("/")[3]
            if method == "GET":
                return 200, {"requests": self.requests.get(aid, []) if query.get("kind") != "personal" else []}
            next(r for r in self.requests[aid] if r["id"] == path.split("/")[-1].split(":")[0])["status"] = "cancelled"
            return 200, {}
        if path.endswith("/limits"):
            return 200, {"daily_in": {"remaining_minor": "1000000"}}
        raise AssertionError((method, path))


class Run(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.file = os.path.join(self.dir, "qa", "credentials.json")
        patches = [mock.patch.object(fx, "FILE", self.file), mock.patch.object(fx, "SLEEP", lambda s: None),
                   mock.patch.object(fx, "WARNINGS", []), mock.patch.object(fx, "admin_reviewer", lambda: fx.Reviewer("admin")),
                   mock.patch.dict(os.environ, {"QA_FIXTURE_PHONES": ""})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def state(self):
        with open(self.file, encoding="utf-8") as f:
            return json.load(f)

    def run_with(self, stack, *args):
        out = io.StringIO()
        with mock.patch.object(fx, "request", stack), contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = fx.run(*args)
        return code, out.getvalue()

    def test_makes_every_fixture_through_the_customer_and_reviewer_apis(self):
        stack = FakeStack()
        code, out = self.run_with(stack)
        self.assertEqual(code, 0, out)
        state = self.state()
        people = state["people"]
        self.assertEqual({k: people[k]["phone"] for k in people}, dict(zip(["requester", "payer", "member", "lite"], PHONES)))
        kyc = {people[k]["phone"]: stack.accounts[people[k]["account_id"]]["kyc"] for k in people}
        self.assertEqual(kyc, {PHONES[0]: "verified", PHONES[1]: "verified", PHONES[2]: "verified", PHONES[3]: "lite"})
        # the verified people were transcribed with fake details, by the claiming admin
        transcribed = [c["details"] for c in stack.cases.values() if "details" in c]
        self.assertEqual(len(transcribed), 3)
        self.assertTrue(all(d["id_number"].startswith("QATESTE") for d in transcribed))
        business = stack.accounts[state["business"]["account_id"]]
        self.assertEqual((business["type"], business["kyc"], business["docs"]), ("business", "verified", ["NUIT", "REGISTRATION_NUMBER"]))
        # balances: payer 30 000 then 1 000 into the budget; lite 15 000; business 30 000
        self.assertEqual(stack.accounts[people["payer"]["account_id"]]["balance"], 3_000_000 - 100_000)
        self.assertEqual(stack.accounts[people["lite"]["account_id"]]["balance"], 1_500_000)
        self.assertEqual(business["balance"], 3_000_000)
        self.assertTrue(all(p["amount_minor"] <= fx.TOP_UP_STEP_MINOR for p in stack.prompts.values()))
        self.assertEqual(people["payer"]["second_product"]["kind"], "mo_budget")
        # the member holds the viewer-template role in the business and on the requester's account
        member = [(aid, role) for p, aid, role, owner in stack.memberships if p == PHONES[2] and not owner]
        self.assertEqual(sorted(aid for aid, _ in member), sorted([business["id"], people["requester"]["account_id"]]))
        self.assertTrue(all(role == fx.ROLE["name"] for _, role in member))
        self.assertTrue(all(r["template"] == "viewer" for roles in stack.roles.values() for r in roles))
        # Orientu requests are left alone without reset
        self.assertEqual(stack.requests["acc_1"][0]["status"], "open")

    def test_pins_reach_only_the_0600_file(self):
        stack = FakeStack()
        code, out = self.run_with(stack)
        self.assertEqual(stat.S_IMODE(os.stat(self.file).st_mode), 0o600)
        people = self.state()["people"]
        for person in people.values():
            self.assertRegex(person["pin"], r"^\d{4}$")
            self.assertNotIn(person["pin"], out.replace(person["phone"], ""))
            self.assertNotIn(person["phone"], out)
        self.assertIn(f"credentials in {self.file}", out)

    def test_a_second_run_makes_nothing_new(self):
        stack = FakeStack()
        self.run_with(stack)
        before = (len(stack.accounts), len(stack.cases), len(stack.prompts), len(stack.invites), sum(map(len, stack.budgets.values())),
                  sum(map(len, stack.roles.values())))
        pins = {k: v["pin"] for k, v in self.state()["people"].items()}
        code, out = self.run_with(stack)
        self.assertEqual(code, 0, out)
        # only the budget's 1 000 is topped back up on the payer
        after = (len(stack.accounts), len(stack.cases), len(stack.prompts) - 1, len(stack.invites), sum(map(len, stack.budgets.values())),
                 sum(map(len, stack.roles.values())))
        self.assertEqual(before, after)
        self.assertEqual(pins, {k: v["pin"] for k, v in self.state()["people"].items()})
        self.assertIn("member: already in business's team", out)

    def test_a_lost_pin_is_replaced_through_the_admin_api(self):
        stack = FakeStack()
        self.run_with(stack)
        state = self.state()
        state["people"]["lite"].pop("pin")
        fx.save(state)
        code, _ = self.run_with(stack)
        new = self.state()["people"]["lite"]["pin"]
        self.assertEqual(code, 0)
        self.assertEqual(stack.users[PHONES[3].lstrip("+")], new)
        self.assertTrue(any(c[1].endswith("/reset-password") for c in stack.calls))
        self.assertFalse(fx.weak(new))

    def test_reset_cancels_only_the_requesters_open_requests(self):
        stack = FakeStack()
        self.run_with(stack)
        stack.requests[self.state()["people"]["requester"]["account_id"]] = stack.requests.pop("acc_1")
        code, out = self.run_with(stack, True)
        self.assertEqual(code, 0)
        self.assertEqual([r["status"] for r in next(iter(stack.requests.values()))], ["cancelled", "closed"])
        self.assertIn("1 open Orientu requests cancelled", out)

    def test_biometrics_refusing_the_synthetic_document_is_reported_and_the_rest_still_made(self):
        stack = FakeStack(reject_documents=True)
        code, out = self.run_with(stack)
        self.assertEqual(code, 1)
        self.assertIn("document_rejected", out)
        self.assertIn("biometrics off", out)
        people = self.state()["people"]
        self.assertEqual(stack.accounts[people["lite"]["account_id"]]["balance"], 1_500_000)
        self.assertNotIn("business", self.state())

    def test_qa_fixture_phones_must_name_every_person(self):
        with mock.patch.dict(os.environ, {"QA_FIXTURE_PHONES": "+258840000201,+258840000202"}):
            with self.assertRaises(SystemExit):
                fx.phones()


class Pins(unittest.TestCase):
    def test_weak_pins_are_never_generated(self):
        for weak in ("1111", "1234", "9876", "0123"):
            self.assertTrue(fx.weak(weak), weak)
        self.assertFalse(fx.weak("2580"))
        self.assertFalse(any(fx.weak(fx.new_pin()) for _ in range(500)))

    def test_the_synthetic_image_is_a_png(self):
        data = fx.png(4, 3, (1, 2, 3))
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(b"IEND", data)


if __name__ == "__main__":
    unittest.main()
