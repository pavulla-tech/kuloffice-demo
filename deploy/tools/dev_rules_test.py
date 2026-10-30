"""tools/dev_rules.py's business policies: an example is proposed and approved
only where the key has no version yet; an operator's version is never replaced."""

import contextlib
import importlib.util
import io
import json
import os
import pathlib
import unittest
from unittest import mock

PATH = pathlib.Path(__file__).with_name("dev_rules.py")
with mock.patch.dict(os.environ, {"WORKFORCE_ISSUER": "http://keycloak/realms/workforce", "DEV_ADMIN_EMAIL": "dev@example.test",
                                  "DEV_ADMIN_PASSWORD": "not-a-secret"}):
    SPEC = importlib.util.spec_from_file_location("dev_rules", PATH)
    rules = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(rules)

WANTED = {"policies": [
    {"key": "account_limits", "document": {"business": {"per_transaction_max_minor": 1}}},
    {"key": "agents", "document": {"enabled": True}},
    {"key": "orientu", "document": {"enabled": True}},
    {"key": "vaquinha", "document": {"enabled": True}},
    {"key": "budgets", "document": {"enabled": True}},
]}


class FakeKulOffice:
    def __init__(self, active=None, versions=None):
        self.active = active or {}
        self.versions = versions or {}
        self.calls = []

    def __call__(self, token, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path == "/v1/business-policies":
            keys = ["account_limits", "agents", "orientu", "vaquinha"]  # budgets: an older KulOffice
            return 200, {"policies": [{"key": k, "active_number": self.active.get(k, 0)} for k in keys]}
        if method == "GET" and path.endswith("/versions"):
            return 200, {"versions": self.versions.get(path.split("/")[3], [])}
        if method == "POST" and path.endswith("/versions"):
            return 200, {"number": 1, "status": "proposed"}
        if method == "POST" and path.endswith(":approve"):
            return 200, {"status": "active"}
        raise AssertionError((method, path))


class SeedPoliciesTest(unittest.TestCase):
    def seed(self, fake):
        rules.call = fake
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            approved = rules.seed_policies("token", WANTED)
        return approved, out.getvalue()

    def test_only_keys_without_any_version_get_the_example(self):
        fake = FakeKulOffice(active={"account_limits": 3},
                             versions={"orientu": [{"number": 1, "status": "rejected", "reason": "operator"}]})
        approved, out = self.seed(fake)
        self.assertEqual(approved, ["agents", "vaquinha"])
        self.assertIn("orientu: an operator's version is there (rejected); left alone", out)
        self.assertIn("budgets: not in this KulOffice, skipped", out)
        proposals = [c for c in fake.calls if c[0] == "POST" and c[1].endswith("/versions")]
        self.assertEqual([c[1] for c in proposals], ["/v1/business-policies/agents/versions", "/v1/business-policies/vaquinha/versions"])
        self.assertEqual(json.loads(proposals[0][2]["document"]), {"enabled": True})
        self.assertFalse(any("account_limits/versions" in c[1] for c in fake.calls if c[0] == "POST"))

    def test_a_proposal_this_script_left_waiting_is_approved_without_a_new_one(self):
        fake = FakeKulOffice(versions={"agents": [{"number": 4, "status": "proposed", "reason": rules.POLICY_REASON}]})
        approved, _ = self.seed(fake)
        self.assertIn("agents", approved)
        self.assertIn(("POST", "/v1/business-policies/agents/versions/4:approve",
                       {"key": "agents", "number": 4, "note": rules.POLICY_REASON}), fake.calls)
        self.assertNotIn(("POST", "/v1/business-policies/agents/versions"), [(c[0], c[1]) for c in fake.calls])

    def test_an_operators_waiting_proposal_is_left_for_the_operators(self):
        fake = FakeKulOffice(versions={"agents": [{"number": 2, "status": "proposed", "reason": "the owner's figures"}]})
        approved, out = self.seed(fake)
        self.assertNotIn("agents", approved)
        self.assertIn("agents: an operator's version is there (proposed)", out)

    def test_the_kits_file_names_every_policy_once(self):
        with open(rules.POLICIES, encoding="utf-8") as f:
            keys = [p["key"] for p in json.load(f)["policies"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), {"account_limits", "claim_send", "orientu", "payment_terms", "merchant_collections",
                                     "agents", "devices", "vaquinha", "budgets", "notifications"})


if __name__ == "__main__":
    unittest.main()
