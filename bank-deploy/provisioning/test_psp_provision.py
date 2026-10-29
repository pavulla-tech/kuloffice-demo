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

        class PartnerAPI:  # a payment partner's run: no tasks for it
            def call(self, method, path, body=None, **_kwargs):
                calls.append(("partner", method, path, body))
                raise psp.ProvisionError(f"{method} {path} failed: HTTP 404: no run")

        provisioner.partner_api = lambda key: PartnerAPI()
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

    def test_the_simulator_bank_does_the_run_tasks_right_after_the_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.csv").write_text("sample")
            config = {"simulator": {"url": "http://simulator:8085"},
                      "partner": {"short_name": "SIMBANK", "statement_profile": {"sample_file": str(root / "sample.csv")}}}
            provisioner, calls = self.certifying(root, config)

            class Simulator:
                def call(self, method, path, body=None, **_kwargs):
                    calls.append(("simulator", method, path, body))
                    if path == "/api/partner/certification/act":
                        return 200, {"run_id": "run-1", "results": [
                            {"key": "incoming/transfer", "outcome": "performed", "calls": [{"status": 201}]}]}, {}
                    if path == "/api/partner/certification-statement":
                        return 200, "reference,amount,currency,date\nmock_1,100,MZN,2026-10-28\n", {}
                    return 200, {}, {}

            provisioner.simulator = lambda: Simulator()
            with mock.patch.object(psp, "log") as logged:
                self.assertTrue(provisioner.ensure_certification())
            order = [c[:3] for c in calls]
            starts = [i for i, c in enumerate(calls) if c[0] == "gateway" and len(c) == 5]
            acts = [i for i, c in enumerate(order) if c == ("simulator", "POST", "/api/partner/certification/act")]
            waits = [i for i, c in enumerate(order) if c[:2] == ("gateway", "GET") and "/runs/" in c[2]]
            # Once per run, after its start and before its first wait.
            self.assertEqual(len(acts), 2)
            self.assertTrue(starts[0] < acts[0] < waits[0] < starts[1] < acts[1])
            self.assertTrue(any("incoming/transfer: performed HTTP 201" in str(c) for c in logged.call_args_list))
            self.assertFalse(any(c[0] == "partner" for c in calls))

    def test_a_real_bank_is_shown_the_run_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.csv").write_text("sample")
            config = {"partner": {"short_name": "FNB", "statement_profile": {"sample_file": str(root / "sample.csv")}}}
            provisioner, calls = self.certifying(root, config)
            tasks = {"run_id": "run-1", "status": "running", "deadline": "2026-10-28T12:10:00Z", "tasks": [
                {"key": "incoming/name_lookup", "action": "name_lookup", "method": "/v1/name-lookups",
                 "destination": {"type": "alias", "value": "258841234567"}, "currency": "MZN", "done": True},
                {"key": "incoming/transfer", "action": "incoming_transfer", "destination": {"type": "deposit_reference", "value": "AG-1"},
                 "amount_minor": 1234, "currency": "MZN", "partner_reference": "CERT-1", "final": True, "done": False}]}
            keys: list = []

            class PartnerAPI:
                def call(self, method, path, body=None, **_kwargs):
                    calls.append(("partner", method, path, body))
                    return 200, tasks, {}

            def partner_api(key):
                keys.append(key)
                return PartnerAPI()

            provisioner.partner_api = partner_api
            with mock.patch.object(psp, "log") as logged:
                self.assertFalse(provisioner.ensure_certification())
            self.assertEqual(keys, ["kp_test_sk_" + "A" * 49])
            self.assertEqual([c[:3] for c in calls if c[0] == "partner"], [("partner", "GET", "/certification/tasks")])
            self.assertEqual(json.loads((root / "certification-tasks.json").read_text()), tasks)
            lines = [str(c.args[0]) for c in logged.call_args_list]
            self.assertEqual(len([line for line in lines if line.startswith("WAIT  FNB does these sandbox tasks")]), 1)
            self.assertTrue(any("incoming/transfer: incoming_transfer to deposit_reference AG-1, 1234 MZN, reference CERT-1" in line
                                for line in lines))
            self.assertFalse(any("incoming/name_lookup" in line for line in lines))

    def test_the_statement_round_lists_the_partner_task_payments(self):
        # The Gateway keeps its wording; an incoming-funding run's payments are
        # its transfers' and deposits' references and amounts.
        cases = [{"kind": "statement", "status": "failed", "actual":
                  "upload a sample statement (CSV: reference, amount, currency, date) listing: CERT-run1-1 12.34 MZN; CERT-run1-2 12.34 MZN"}]
        self.assertEqual(psp.statement_payments(cases), [
            {"reference": "CERT-run1-1", "amount": "12.34", "currency": "MZN"},
            {"reference": "CERT-run1-2", "amount": "12.34", "currency": "MZN"}])

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

    def test_one_url_for_both_modes_registers_an_endpoint_per_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            url = "http://simulator:8085/partner-webhooks"
            provisioner = psp.Provisioner({"partner": {"short_name": "SIMBANK", "webhooks": {
                "test_url": url, "live_url": url}}}, Path(directory))
            endpoints: list = []

            class API:
                def call(self, method, path, body=None, **_kwargs):
                    if method == "GET":
                        return 200, {"data": list(endpoints)}, {}
                    endpoint = {"id": f"we_{len(endpoints) + 1}", "url": body["url"], "mode": body["mode"]}
                    endpoints.append(endpoint)
                    return 201, {**endpoint, "secret": "whsec_" + body["mode"]}, {}

            provisioner.partner_api = lambda key: API()
            provisioner.ensure_webhook_endpoint("test", "key")
            provisioner.ensure_webhook_endpoint("live", "key")
            self.assertEqual([e["mode"] for e in endpoints], ["test", "live"])
            secrets = json.loads((Path(directory) / "secrets.json").read_text())
            self.assertEqual((secrets["test_webhook_secret"], secrets["live_webhook_secret"]), ("whsec_test", "whsec_live"))

    def test_an_endpoint_whose_secret_was_not_kept_is_rolled(self):
        with tempfile.TemporaryDirectory() as directory:
            url = "http://bank.example/webhooks"
            provisioner = psp.Provisioner({"partner": {"short_name": "FNB", "webhooks": {"live_url": url}}}, Path(directory))
            calls: list = []

            class API:
                def call(self, method, path, body=None, **_kwargs):
                    calls.append((method, path))
                    if method == "GET":
                        return 200, {"data": [{"id": "we_9", "url": url, "mode": "live"}]}, {}
                    return 200, {"endpoint": {"id": "we_9", "secret": "whsec_new"}}, {}

            provisioner.partner_api = lambda key: API()
            provisioner.ensure_webhook_endpoint("live", "key")
            self.assertIn(("POST", "/webhook-endpoints/we_9/roll-secret"), calls)
            self.assertEqual(json.loads((Path(directory) / "secrets.json").read_text())["live_webhook_secret"], "whsec_new")

    def test_the_fnb_dev_config_loads_with_the_stand_in(self):
        if psp.yaml is None:
            self.skipTest("PyYAML is tested in the provisioner image")
        loaded = psp.load_config(MODULE.with_name("fnb-dev") / "fnb-dev.yaml")
        self.assertEqual(loaded["deployment"]["stop_at"], "pilot")
        self.assertEqual(loaded["dev_stand_in"]["simulator_url"], "http://simulator:8085")
        self.assertNotIn("simulator", loaded, "the simulator must never receive FNB's keys")
        self.assertTrue(Path(loaded["partner"]["statement_profile"]["sample_file"]).is_file())
        self.assertTrue(Path(loaded["partner"]["commercial_terms"]["signed_contract_file"]).is_file())
        self.assertEqual([t["type"] for t in loaded["partner"]["capability_matrix"]["types"]], ["NAME_LOOKUP", "CASH_IN"])

    def test_stop_at_sandbox_keeps_the_sandbox_key_and_skips_certification(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner = psp.Provisioner({"deployment": {"stop_at": "sandbox"}, "partner": {"short_name": "FNB"}}, Path(directory))
            done: list = []
            for name in ("require_runtime", "verify_launch_matrix", "ensure_users", "ensure_test_business",
                         "ensure_application", "ensure_kyb", "ensure_commercial", "ensure_capabilities",
                         "ensure_safeguarding_accounts", "ensure_certification", "ensure_pilot"):
                setattr(provisioner, name, lambda name=name: done.append(name) or True)
            provisioner.ensure_sandbox = lambda: done.append("ensure_sandbox") or "kp_test_x"
            self.assertEqual(provisioner.apply(), 0)
            self.assertIn("ensure_sandbox", done)
            self.assertNotIn("ensure_certification", done)
            self.assertNotIn("ensure_pilot", done)
            self.assertEqual(json.loads(provisioner.report_path.read_text())["outcome"], "sandbox_ready")

    def test_the_dev_stand_in_does_the_partners_tasks_with_its_sandbox_key(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner = psp.Provisioner({"partner": {"short_name": "FNB", "commercial_terms": {"settlement": {"account": "FNB-DEV-0001"}}},
                                           "dev_stand_in": {"simulator_url": "http://simulator:8085"}}, Path(directory))
            calls: list = []
            tasks = [
                {"key": "incoming/name_lookup", "action": "name_lookup", "destination": {"type": "deposit_reference", "value": "KPCERT-X"}},
                {"key": "incoming/transfer", "action": "incoming_transfer", "partner_reference": "CERT-1", "amount_minor": 1234,
                 "currency": "MZN", "destination": {"type": "deposit_reference", "value": "KPCERT-X"}},
                {"key": "incoming/transfer_replay", "action": "transfer_replay", "partner_reference": "CERT-1", "amount_minor": 1234,
                 "currency": "MZN", "destination": {"type": "deposit_reference", "value": "KPCERT-X"}},
                {"key": "incoming/cash_deposit", "action": "cash_deposit", "partner_reference": "CERT-2", "amount": "12.34",
                 "currency": "MZN", "destination": {"type": "deposit_reference", "value": "KPCERT-X"}},
                {"key": "incoming/done", "action": "name_lookup", "done": True},
            ]

            class API:
                def call(self, method, path, body=None, headers=None, **_kwargs):
                    calls.append((method, path, body, (headers or {}).get("Idempotency-Key")))
                    if path == "/certification/tasks":
                        return 200, {"tasks": tasks}, {}
                    if path == "/name-lookups":
                        return 200, {"lookup_id": "lk_1"}, {}
                    if path == "/cash-deposits/intents":
                        return 201, {"id": "cdi_1"}, {}
                    return 200, {}, {}

            provisioner.partner_api = lambda key: API()
            provisioner.partner_tasks("run_1", "kp_test_sk_x")
            paths = [(c[0], c[1]) for c in calls]
            self.assertEqual(paths, [("GET", "/certification/tasks"), ("POST", "/name-lookups"), ("POST", "/incoming-transfers"),
                                     ("POST", "/incoming-transfers"), ("POST", "/name-lookups"), ("POST", "/cash-deposits/intents"),
                                     ("POST", "/cash-deposits/intents/cdi_1/confirm")])
            self.assertEqual(calls[2][2], calls[3][2], "the replay is the same report")
            self.assertEqual(calls[5][3], "CERT-2-lk_1")
            self.assertEqual(calls[6][2]["account"], "FNB-DEV-0001")
            self.assertEqual(calls[6][2]["entry_id"], "CERT-2")

    def test_the_simulator_bank_config_loads(self):
        if psp.yaml is None:
            self.skipTest("PyYAML is tested in the provisioner image")
        loaded = psp.load_config(MODULE.with_name("simulator-bank.example.yaml"))
        self.assertEqual(loaded["simulator"]["url"], "http://simulator:8085")
        self.assertTrue(Path(loaded["partner"]["kyb"]["documents"][0]["file"]).is_file())
        self.assertEqual(psp.route_text(psp.launch_routes(loaded)[0]),
                         "incoming_transfer/partner_api/deposit_reference/live/acc_top")

        # The trust account: its camt.053 profile beside the CSV one, handed to
        # the simulator, and the Gateway's safeguarding account.
        extra = loaded["partner"]["statement_profile"]["additional_profiles"]
        self.assertEqual([item["profile"]["id"] for item in extra], ["simbank-trust-eod"])
        self.assertTrue(Path(extra[0]["sample_file"]).is_file())
        self.assertEqual(extra[0]["profile"]["cutoff"], "16:00")
        self.assertEqual(loaded["simulator"]["trust_statement_profile"], "simbank-trust-eod")
        self.assertEqual(loaded["partner"]["safeguarding_accounts"],
                         [{"account": "SIMBANK-TRUST-001", "currency": "MZN", "bank": "Banco Simulado KulPay"}])

    def test_the_fnb_example_documents_the_new_keys_empty(self):
        if psp.yaml is None:
            self.skipTest("PyYAML is tested in the provisioner image")
        raw = psp.yaml.safe_load(MODULE.with_name("fnb-pilot.example.yaml").read_text())
        self.assertEqual(raw["partner"]["statement_profile"]["additional_profiles"], [])
        self.assertEqual(raw["partner"]["safeguarding_accounts"], [])

    def test_additional_profiles_resolve_beside_the_yaml_and_are_checked(self):
        if psp.yaml is None:
            self.skipTest("PyYAML is tested in the provisioner image")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.valid_config(root)
            (root / "trust.xml").write_text("<Document/>")
            config["partner"]["statement_profile"]["profile"]["id"] = "main"
            config["partner"]["statement_profile"]["additional_profiles"] = [
                {"sample_file": "trust.xml", "profile": {"id": "trust", "standard": "camt.053", "accounts": ["T-1"]}}]
            config["simulator"] = {"trust_statement_profile": "trust"}
            config["partner"]["safeguarding_accounts"] = [{"account": "T-1", "currency": "mzn"}]
            loaded = self.load(root, config)
            self.assertEqual(loaded["partner"]["statement_profile"]["additional_profiles"][0]["sample_file"],
                             str(root / "trust.xml"))
            config["simulator"]["trust_statement_profile"] = "other"
            with self.assertRaisesRegex(psp.ProvisionError, "trust_statement_profile"):
                self.load(root, config)
            config["simulator"]["trust_statement_profile"] = "trust"
            config["partner"]["safeguarding_accounts"] = [{"account": "T-1"}]
            with self.assertRaisesRegex(psp.ProvisionError, "3-letter currency"):
                self.load(root, config)

    def test_missing_statement_profiles_are_installed_beside_the_existing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.csv").write_text("csv")
            (root / "trust.xml").write_text("xml")
            config = {"simulator": {"trust_statement_profile": "trust"}, "partner": {"short_name": "SIMBANK", "statement_profile": {
                "sample_file": str(root / "main.csv"), "profile": {"id": "main", "standard": "csv"},
                "additional_profiles": [{"sample_file": str(root / "trust.xml"),
                                         "profile": {"id": "trust", "standard": "camt.053"}}]}}}
            provisioner = psp.Provisioner(config, root)
            provisioner.state["psp_id"] = "psp-1"
            installed: list = [{"id": "main", "standard": "csv", "sample_file_id": "file_main"}]
            calls: list = []

            class API:
                def call(self, method, path, body=None, **_kwargs):
                    calls.append((method, path, body))
                    if method == "GET":
                        return 200, {"version": 1, "profiles": list(installed)}, {}
                    installed[:] = body["profiles"]
                    return 201, {"version": 2}, {}

                def multipart(self, path, fields, files, **_kwargs):
                    calls.append(("POST", path, json.loads(fields["profile"])["id"], files["sample"].read_text()))
                    return {"sample_file_id": "file_" + json.loads(fields["profile"])["id"]}

            provisioner.partner_api = lambda key: API()
            provisioner.ensure_statement_profile("key")
            self.assertEqual([p["id"] for p in installed], ["main", "trust"])
            self.assertEqual(installed[1]["sample_file_id"], "file_trust")
            self.assertEqual([c for c in calls if c[1].endswith("/preview")],
                             [("POST", "/psps/psp-1/statement-profiles/preview", "trust", "xml")])
            self.assertEqual(provisioner.state["statement_profile_id"], "main")
            self.assertEqual(provisioner.state["trust_statement_profile_id"], "trust")
            # Nothing missing: nothing is put again.
            calls.clear()
            provisioner.ensure_statement_profile("key")
            self.assertEqual([c[0] for c in calls], ["GET"])

            # The simulator is handed both profiles.
            handed: list = []

            class Simulator:
                def call(self, method, path, body=None, **_kwargs):
                    handed.append((method, path, body))
                    return 200, {}, {}

            provisioner.simulator = lambda: Simulator()
            provisioner.hand_to_simulator("live", "kp_live_rk_x")
            self.assertEqual(handed[0][1], "/api/partner/setup")
            self.assertEqual(handed[0][2]["statement_profile_id"], "main")
            self.assertEqual(handed[0][2]["trust_statement_profile_id"], "trust")

    def test_a_certified_partner_gets_profiles_added_since(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner = psp.Provisioner({"partner": {"short_name": "SIMBANK"}}, Path(directory))
            provisioner.state["psp_id"] = "psp-1"
            provisioner.secret_values["sandbox_api_key"] = "kp_test_sk_" + "A" * 49
            provisioner.psp = lambda: {"id": "psp-1", "certified_at": "now"}
            used: list = []
            provisioner.ensure_statement_profile = lambda key: used.append(key)
            self.assertTrue(provisioner.ensure_certification())
            self.assertEqual(used, ["kp_test_sk_" + "A" * 49])

    def test_safeguarding_accounts_are_registered_once(self):
        with tempfile.TemporaryDirectory() as directory:
            provisioner = psp.Provisioner({"partner": {"short_name": "SIMBANK", "safeguarding_accounts": [
                {"account": "SIMBANK-TRUST-001", "currency": "mzn", "bank": "Banco Simulado KulPay"}]}}, Path(directory))
            registered: list = []

            class Admin:
                def call(self, method, path, body=None, **_kwargs):
                    assert path == "/admin/safeguarding/accounts", path
                    if method == "GET":
                        return 200, {"data": list(registered), "total": len(registered)}, {}
                    registered.append(body)
                    return 201, dict(body, id="sga_1"), {}

            provisioner.admin = Admin()
            provisioner.ensure_safeguarding_accounts()
            provisioner.ensure_safeguarding_accounts()
            self.assertEqual(registered, [{"account": "SIMBANK-TRUST-001", "currency": "MZN", "bank": "Banco Simulado KulPay"}])
            provisioner.report("pilot_ready")
            report = json.loads((Path(directory) / "readiness-report.json").read_text())
            self.assertEqual(report["safeguarding_accounts"], ["SIMBANK-TRUST-001"])

            # Plan mode only says what it would register.
            planning = psp.Provisioner(provisioner.config, Path(directory) / "plan", dry_run=True)
            planning.admin = None
            planning.ensure_safeguarding_accounts()


if __name__ == "__main__":
    unittest.main()
