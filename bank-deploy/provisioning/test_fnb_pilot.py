import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE = Path(__file__).with_name("fnb_pilot.py")
SPEC = importlib.util.spec_from_file_location("fnb_pilot", MODULE)
fnb_pilot = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(fnb_pilot)


class FNBPilotTests(unittest.TestCase):
    def test_extracts_the_two_one_time_key_environments(self):
        test_key = "kp_test_sk_" + "A" * 49
        live_key = "kp_live_rk_" + "9" * 49
        self.assertEqual(fnb_pilot.extract_one_time_key("sandbox", f"<code>{test_key}</code>"), test_key)
        self.assertEqual(fnb_pilot.extract_one_time_key("live", f"<code>{live_key}</code>"), live_key)

    def test_live_cash_deposit_route_uses_expanded_fields(self):
        matrix = {"routes": [{"operation": "cash_deposit", "driver": "partner_api", "method": "cash",
                              "mode": "live", "scope": "acc_top", "enabled": True}]}
        self.assertTrue(fnb_pilot.live_cash_deposit_enabled(matrix))
        matrix["routes"][0]["enabled"] = False
        self.assertFalse(fnb_pilot.live_cash_deposit_enabled(matrix))

    def test_percentage_amount_is_decimal_and_fixed_to_two_places(self):
        self.assertEqual(fnb_pilot.percentage_amount("500000", 10), "50000.00")
        self.assertEqual(fnb_pilot.percentage_amount("0.15", 10), "0.02")

    def test_rollback_removes_merchants_then_uses_maker_checker_suspension(self):
        class Gateway:
            def __init__(self):
                self.status = "pilot"
                self.calls = []

            def call(self, method, path, body=None, **_kwargs):
                self.calls.append((method, path, body))
                if method == "GET" and path == "/admin/psps/psp-1":
                    return 200, {"psp": {"id": "psp-1", "status": self.status}}, {}
                if method == "GET" and path.startswith("/admin/approvals?"):
                    return 200, {"data": []}, {}
                if method == "POST" and path == "/admin/psps/psp-1/suspension":
                    return 202, {"approval": {"id": "approval-1"}}, {}
                return 200, {}, {}

        class Checker:
            def __init__(self, gateway):
                self.gateway = gateway
                self.calls = []

            def call(self, method, path, body=None, **_kwargs):
                self.calls.append((method, path, body))
                self.gateway.status = "suspended"
                return 200, {}, {}

        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {
            "GATEWAY_ADMIN_KEY": "maker-key", "GATEWAY_CHECKER_KEY": "checker-key",
        }, clear=False):
            config = {
                "operators": {"create_workforce_users": False},
                "fnb": {"legal_name": "FNB", "commercial_terms": {"limits": {
                    "per_transaction": "500000", "daily": "20000000",
                    "monthly": "400000000", "currency": "MZN",
                }}},
                "pilot": {"limit_percentage": 10, "rollback_reason": "stop pilot"},
            }
            provisioner = fnb_pilot.Provisioner(config, Path(directory))
            provisioner.state["psp_id"] = "psp-1"
            gateway = Gateway()
            checker = Checker(gateway)
            provisioner.admin = gateway
            provisioner.checker = checker

            self.assertEqual(provisioner.rollback(), 0)
            pilot_update = next(call for call in gateway.calls if call[1].endswith("/pilot"))
            self.assertEqual(pilot_update[2]["merchants"], [])
            self.assertEqual(pilot_update[2]["routing_weight"], 1)
            self.assertEqual(checker.calls[0][1], "/admin/approvals/approval-1/decide")
            self.assertEqual(json.loads((Path(directory) / "readiness-report.json").read_text())["outcome"],
                             "pilot_suspended")

    def test_atomic_json_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secrets.json"
            fnb_pilot.atomic_json(path, {"secret": "value"})
            self.assertEqual(json.loads(path.read_text()), {"secret": "value"})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_require_lists_all_missing_values(self):
        with self.assertRaisesRegex(fnb_pilot.ProvisionError, "a, b.c"):
            fnb_pilot.require({}, ["a", "b.c"])

    def test_maker_and_checker_must_be_different(self):
        if fnb_pilot.yaml is None:
            self.skipTest("PyYAML is tested in the provisioner image")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "contract.pdf").write_bytes(b"contract")
            (root / "statement.xml").write_bytes(b"statement")
            (root / "kyb.pdf").write_bytes(b"kyb")
            config = {
                "schema_version": 1,
                "operators": {
                    "maker": {"email": "same@example.com", "first_name": "A", "last_name": "B"},
                    "checker": {"email": "same@example.com", "first_name": "C", "last_name": "D"},
                    "fnb_technical": {"email": "tech@example.com", "first_name": "E", "last_name": "F"},
                },
                "fnb": {
                    "legal_name": "FNB", "registration_number": "1",
                    "licence": {"type": "bank", "number": "1", "issuer": "BM"},
                    "technical_contact": {"name": "T", "email": "t@example.com"},
                    "compliance_contact": {"name": "C", "email": "c@example.com"},
                    "kyb": {"documents": [{"type": "registration", "file": str(root / "kyb.pdf")}],
                            "screenings": {"sanctions": {"subject": "FNB", "reference": "x"},
                                           "pep": {"subject": "FNB", "reference": "y"}}},
                    "commercial_terms": {"contract_ref": "x", "signed_contract_file": str(root / "contract.pdf")},
                    "statement_profile": {"sample_file": str(root / "statement.xml"),
                                          "profile": {"standard": "camt.053", "accounts": ["1"]}},
                },
            }
            path = root / "config.yaml"
            path.write_text(fnb_pilot.yaml.safe_dump(config))
            with self.assertRaisesRegex(fnb_pilot.ProvisionError, "must be different"):
                fnb_pilot.load_config(path)


if __name__ == "__main__":
    unittest.main()
