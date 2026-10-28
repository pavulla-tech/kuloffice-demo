import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from typing import Any
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

    def test_statement_payments_read_both_gateway_wordings(self):
        listing = [{"kind": "statement", "status": "failed", "actual":
                    "upload a sample statement (CSV: reference, amount, currency, date) listing: mock_1 100 MZN; mock_2 5.5 MZN"}]
        self.assertEqual(psp.statement_payments(listing), [
            {"reference": "mock_1", "amount": "100", "currency": "MZN"},
            {"reference": "mock_2", "amount": "5.5", "currency": "MZN"}])
        missing = [{"kind": "statement", "status": "failed",
                    "actual": "2 row(s) parsed; 0 of 1 payments matched; missing: mock_9 12.5"}]
        self.assertEqual(psp.statement_payments(missing), [{"reference": "mock_9", "amount": "12.5", "currency": "MZN"}])
        self.assertEqual(psp.statement_payments([{"kind": "statement", "status": "passed", "actual": "ok"}]), [])

    def certifying(self, directory: Path, config: dict) -> tuple[Any, list]:
        """A provisioner whose Gateway fails round 1 on the statement alone."""
        calls: list = []

        class Gateway:
            def __init__(self):
                self.runs = []

            def call(self, method, path, body=None, **_kwargs):
                calls.append(("gateway", method, path, body))
                if path == "/admin/psps/psp-1":
                    certified = bool(self.runs) and self.runs[-1]["status"] == "passed"
                    return 200, {"psp": {"id": "psp-1", "status": "certification",
                                         "certified_at": "now" if certified else None}}, {}
                if path == "/admin/psps/psp-1/certification/runs" and method == "GET":
                    return 200, {"data": []}, {}
                if path.startswith("/admin/psps/psp-1/certification/runs/"):
                    run = next(r for r in self.runs if r["id"] == path.rsplit("/", 1)[1])
                    if run["status"] == "failed":
                        cases = [{"key": "statement/sample", "kind": "statement", "status": "failed", "mandatory": True,
                                  "actual": "1 row(s) parsed; 0 of 1 payments matched; missing: mock_1 100"}]
                    else:
                        cases = [{"key": "statement/sample", "kind": "statement", "status": "passed", "mandatory": True}]
                    return 200, {"run": run, "cases": cases}, {}
                raise AssertionError(path)

            def multipart(self, path, fields, files, **_kwargs):
                calls.append(("gateway", "POST", path, fields, {k: v.read_text() for k, v in files.items()}))
                run = {"id": f"run-{len(self.runs) + 1}", "status": "failed" if not self.runs else "passed",
                       "rerun_of": fields.get("rerun_of", "")}
                self.runs.append(run)
                return run

        provisioner = psp.Provisioner(config, directory)
        provisioner.state.update({"psp_id": "psp-1", "statement_profile_id": "sp-1"})
        provisioner.secret_values["sandbox_api_key"] = "kp_test_sk_" + "A" * 49
        provisioner.admin = Gateway()
        provisioner.ensure_statement_profile = lambda key: None
        provisioner.ensure_webhook_endpoint = lambda mode, key: None
        return provisioner, calls

    def test_the_simulator_bank_answers_the_second_round(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.csv").write_text("sample")
            config = {"simulator": {"url": "http://simulator:8085"},
                      "partner": {"short_name": "SIMBANK", "statement_profile": {"sample_file": str(root / "sample.csv")}}}
            provisioner, calls = self.certifying(root, config)

            class Simulator:
                def call(self, method, path, body=None, **_kwargs):
                    calls.append(("simulator", method, path, body))
                    if path == "/api/partner/certification-statement":
                        return 200, "reference,amount,currency,date\nmock_1,100,MZN,2026-10-28\n", {}
                    return 200, {}, {}

            provisioner.simulator = lambda: Simulator()
            self.assertTrue(provisioner.ensure_certification())
            setup = next(c for c in calls if c[:3] == ("simulator", "PUT", "/api/partner/setup"))
            self.assertEqual(setup[3]["mode"], "test")
            asked = next(c for c in calls if c[2] == "/api/partner/certification-statement")
            self.assertEqual(asked[3], {"payments": [{"reference": "mock_1", "amount": "100", "currency": "MZN"}]})
            runs = [c for c in calls if c[0] == "gateway" and len(c) == 5]
            self.assertEqual(runs[0][4]["statement"], "sample")
            self.assertEqual(runs[1][3], {"rerun_of": "run-1"})
            self.assertIn("mock_1,100,MZN", runs[1][4]["statement"])

    def test_a_real_bank_is_asked_for_its_statement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.csv").write_text("sample")
            config = {"partner": {"short_name": "FNB", "statement_profile": {"sample_file": str(root / "sample.csv")}}}
            provisioner, calls = self.certifying(root, config)
            self.assertFalse(provisioner.ensure_certification())
            request = json.loads((root / "statement-request.json").read_text())
            self.assertEqual(request["payments"], [{"reference": "mock_1", "amount": "100", "currency": "MZN"}])
            self.assertEqual(len([c for c in calls if len(c) == 5]), 1)

            # FNB's statement arrives: the next apply repeats the failed run with it.
            (root / "fnb.csv").write_text("reference,amount,currency,date\nmock_1,100,MZN,2026-10-28\n")
            config["partner"]["certification_statement_file"] = str(root / "fnb.csv")
            gateway = provisioner.admin
            gateway.call = (lambda original: lambda method, path, body=None, **kw: (
                (200, {"data": [gateway.runs[-1]]}, {}) if method == "GET" and path.endswith("/runs")
                else original(method, path, body, **kw)))(gateway.call)
            self.assertTrue(provisioner.ensure_certification())
            self.assertEqual([c for c in calls if len(c) == 5][-1][3:], ({"rerun_of": "run-1"}, {"statement": (root / "fnb.csv").read_text()}))

    def test_the_webhook_endpoint_is_registered_once_and_its_secret_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner = psp.Provisioner({"partner": {"short_name": "SIMBANK", "webhooks": {
                "test_url": "http://simulator:8085/partner-webhooks"}}}, Path(directory))
            endpoints: list = []

            class API:
                def call(self, method, path, body=None, **_kwargs):
                    if method == "GET":
                        return 200, {"data": list(endpoints)}, {}
                    endpoints.append({"id": "we_1", "url": body["url"]})
                    return 201, {"id": "we_1", "url": body["url"], "secret": "whsec_x"}, {}

            provisioner.partner_api = lambda key: API()
            provisioner.ensure_webhook_endpoint("test", "key")
            provisioner.ensure_webhook_endpoint("test", "key")
            provisioner.ensure_webhook_endpoint("live", "key")
            self.assertEqual(len(endpoints), 1)
            self.assertEqual(json.loads((Path(directory) / "secrets.json").read_text())["test_webhook_secret"], "whsec_x")

    def test_the_simulator_bank_config_loads(self):
        if psp.yaml is None:
            self.skipTest("PyYAML is tested in the provisioner image")
        loaded = psp.load_config(MODULE.with_name("simulator-bank.example.yaml"))
        self.assertEqual(loaded["simulator"]["url"], "http://simulator:8085")
        self.assertTrue(Path(loaded["partner"]["kyb"]["documents"][0]["file"]).is_file())
        self.assertEqual(psp.route_text(psp.launch_routes(loaded)[0]),
                         "incoming_transfer/partner_api/deposit_reference/live/acc_top")


if __name__ == "__main__":
    unittest.main()
