import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE = Path(__file__).with_name("psp_provision.py")
SPEC = importlib.util.spec_from_file_location("psp_provision", MODULE)
psp = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(psp)


class PSPProvisionTests(unittest.TestCase):
    def test_extracts_the_two_one_time_key_environments(self):
        test_key = "kp_test_sk_" + "A" * 49
        live_key = "kp_live_rk_" + "9" * 49
        self.assertEqual(psp.extract_one_time_key("sandbox", f"<code>{test_key}</code>"), test_key)
        self.assertEqual(psp.extract_one_time_key("live", f"<code>{live_key}</code>"), live_key)

    def test_live_cash_deposit_route_uses_expanded_fields(self):
        matrix = {"routes": [{"operation": "cash_deposit", "driver": "partner_api", "method": "cash",
                              "mode": "live", "scope": "acc_top", "enabled": True}]}
        self.assertTrue(psp.live_cash_deposit_enabled(matrix))
        matrix["routes"][0]["enabled"] = False
        self.assertFalse(psp.live_cash_deposit_enabled(matrix))

    def test_percentage_amount_is_decimal_and_fixed_to_two_places(self):
        self.assertEqual(psp.percentage_amount("500000", 10), "50000.00")
        self.assertEqual(psp.percentage_amount("0.15", 10), "0.02")

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
                "partner": {"legal_name": "FNB", "commercial_terms": {"limits": {
                    "per_transaction": "500000", "daily": "20000000",
                    "monthly": "400000000", "currency": "MZN",
                }}},
                "pilot": {"limit_percentage": 10, "rollback_reason": "stop pilot"},
            }
            provisioner = psp.Provisioner(config, Path(directory))
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
            psp.atomic_json(path, {"secret": "value"})
            self.assertEqual(json.loads(path.read_text()), {"secret": "value"})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_require_lists_all_missing_values(self):
        with self.assertRaisesRegex(psp.ProvisionError, "a, b.c"):
            psp.require({}, ["a", "b.c"])

    def valid_config(self, root: Path) -> dict:
        """A complete partner YAML, its evidence files written under root."""
        for name, body in (("contract.pdf", b"contract"), ("statement.csv", b"statement"), ("kyb.pdf", b"kyb")):
            (root / name).write_bytes(body)
        transfer_row = {"methods": ["cash_deposit"], "direction": "inbound", "mode": "sync", "currencies": ["MZN"],
                        "countries": ["MZ"], "partial": False, "three_ds": False, "idempotency": True,
                        "confirmation": "polling", "timeout_ms": 10000}
        return {
            "schema_version": 1,
            "operators": {
                "maker": {"email": "maker@example.com", "first_name": "A", "last_name": "B"},
                "checker": {"email": "checker@example.com", "first_name": "C", "last_name": "D"},
                "partner_technical": {"email": "tech@example.com", "first_name": "E", "last_name": "F"},
            },
            "partner": {
                "short_name": "FNB", "legal_name": "First National Bank", "registration_number": "1",
                "licence": {"type": "bank", "number": "1", "issuer": "BM"},
                "technical_contact": {"name": "T", "email": "t@example.com"},
                "compliance_contact": {"name": "C", "email": "c@example.com"},
                "expected_monthly_volume": 1000, "expected_monthly_value": "10000000",
                "kyb": {"documents": [{"type": "registration", "file": str(root / "kyb.pdf")}],
                        "screenings": {"sanctions": {"subject": "FNB", "reference": "x"},
                                       "pep": {"subject": "FNB", "reference": "y"}}},
                "commercial_terms": {"contract_ref": "x", "signed_contract_file": str(root / "contract.pdf"),
                                     "settlement": {"account": "1"},
                                     "limits": {"per_transaction": "500000", "daily": "20000000", "monthly": "400000000"}},
                "capability_matrix": {
                    "types": [dict(transfer_row, type="NAME_LOOKUP"), dict(transfer_row, type="CASH_IN")],
                    "capabilities": [{"name": "account_funding.incoming", "modes": ["test", "live"], "currencies": ["MZN"]}],
                },
                "statement_profile": {"sample_file": str(root / "statement.csv"),
                                      "profile": {"standard": "csv", "accounts": ["1"]}},
            },
            "pilot": {"routing_weight": 10, "limit_percentage": 10, "credential_valid_days": 90},
            "test_business": {
                "business_name": "Pilot Test Business",
                "biller": {"code": "PILOT", "name": "Pilot Biller"},
                "product": {"code": "POSTPAID", "name": "Postpaid"},
                "invoices": {"rf": {"number": "RF-001", "account_reference": "ACC-RF", "amount": "100.00"},
                             "qr": {"number": "QR-001", "account_reference": "ACC-QR", "amount": "125.00"}},
            },
        }

    def load(self, root: Path, config: dict) -> dict:
        path = root / "config.yaml"
        path.write_text(psp.yaml.safe_dump(config))
        return psp.load_config(path)

    def test_a_complete_partner_yaml_loads(self):
        if psp.yaml is None:
            self.skipTest("PyYAML is tested in the provisioner image")
        with tempfile.TemporaryDirectory() as directory:
            loaded = self.load(Path(directory), self.valid_config(Path(directory)))
            self.assertEqual(loaded["partner"]["short_name"], "FNB")

    def test_maker_and_checker_must_be_different(self):
        if psp.yaml is None:
            self.skipTest("PyYAML is tested in the provisioner image")
        with tempfile.TemporaryDirectory() as directory:
            config = self.valid_config(Path(directory))
            config["operators"]["checker"]["email"] = "maker@example.com"
            with self.assertRaisesRegex(psp.ProvisionError, "must be different"):
                self.load(Path(directory), config)

    def test_a_partner_names_the_live_routes_it_needs(self):
        matrix = {"routes": [
            {"operation": "incoming_transfer", "driver": "partner_api", "method": "deposit_reference", "mode": "live",
             "scope": "acc_top", "enabled": True},
            {"operation": "cash_deposit", "driver": "partner_api", "method": "cash", "mode": "live", "scope": "acc_top",
             "enabled": False},
        ]}
        transfers = [{"operation": "incoming_transfer", "driver": "partner_api", "method": "deposit_reference",
                      "mode": "live", "scope": "acc_top"}]
        self.assertEqual(psp.missing_routes(matrix, transfers), [])
        self.assertEqual(psp.missing_routes(matrix, psp.launch_routes({})), psp.DEFAULT_LAUNCH_ROUTES)
        self.assertEqual(psp.launch_routes({"partner": {"launch_routes": transfers}}), transfers)
        self.assertEqual(psp.route_text(transfers[0]), "incoming_transfer/partner_api/deposit_reference/live/acc_top")


if __name__ == "__main__":
    unittest.main()
