import contextlib
import importlib.util
import io
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("gateway_kuloffice.py")
SPEC = importlib.util.spec_from_file_location("gateway_kuloffice", MODULE_PATH)
gateway = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gateway)
gateway.ACCOUNT_ID = "acc_kuloffice"
gateway.CHECKER_KEY = "checker-key"

ACTIVE_BILLER = {"id": "bil_1", "code": "KULPAY", "tenant_id": "acc_kuloffice", "status": "active"}
INVOICE_PRODUCT = {"code": "FATURA", "amount_rule": "presented", "enabled": True}


class FakeGateway:
    def __init__(self, incoming=None, sink=None, biller=ACTIVE_BILLER, approvals=(), products=(INVOICE_PRODUCT,)):
        self.incoming = incoming
        self.sink = sink
        self.biller = dict(biller) if biller else None
        self.products = [dict(p) for p in products] if biller else []
        self.approvals = list(approvals)
        self.calls = []

    def __call__(self, method, path, key, body=None):
        self.calls.append((method, path, key, body))
        if method == "GET" and path == "/webhook-endpoints":
            return 200, {"data": [self.incoming] if self.incoming else []}
        if method == "POST" and path == "/webhook-endpoints":
            return 201, {"id": "wh_1", "secret": "incoming-new"}
        if method == "PATCH" and path.startswith("/webhook-endpoints/"):
            self.incoming = {**self.incoming, **(body or {})}
            return 200, self.incoming
        if method == "POST" and path.endswith("/roll-secret") and path.startswith("/webhook-endpoints/"):
            return 200, {"endpoint": {"secret": "incoming-rolled"}}
        if method == "GET" and path == "/admin/service-event-sinks":
            return 200, {"data": [self.sink] if self.sink else []}
        if method == "POST" and path == "/admin/service-event-sinks":
            return 201, {"id": "sink_1", "secret": "service-new"}
        if method == "PATCH" and path.startswith("/admin/service-event-sinks/"):
            return 200, {**self.sink, **(body or {})}
        if method == "POST" and path.endswith("/roll-secret") and path.startswith("/admin/service-event-sinks/"):
            return 200, {"secret": "service-rolled"}
        if method == "POST" and path.startswith("/admin/accounts/") and path.endswith("/keys"):
            return 201, {"key": {"id": "key_1", "secret": "partners-new"}}
        if method == "GET" and path == "/admin/billers/KULPAY":
            if self.biller is None:
                raise RuntimeError("GET /admin/billers/KULPAY failed: 404 {\"error\":\"not_found\"}")
            return 200, {"biller": self.biller, "products": self.products}
        if method == "POST" and path == "/admin/billers/KULPAY/products":
            self.products.append(dict(body))
            return 201, body
        if method == "PUT" and path == "/admin/accounts/acc_kuloffice/cash-in-incoming":
            return 200, {"enabled": True}
        if method == "PATCH" and path == "/admin/billers/KULPAY":
            self.biller = {**self.biller, **body}
            return 200, self.biller
        if method == "POST" and path == "/admin/billers":
            self.biller = {**body, "id": "bil_new", "status": "draft"}
            return 201, self.biller
        if method == "GET" and path.startswith("/admin/approvals?"):
            return 200, {"data": self.approvals}
        if method == "POST" and path == "/admin/billers/KULPAY/status":
            return 202, {"approval": {"id": "apr_new"}}
        if method == "POST" and path.startswith("/admin/approvals/") and path.endswith("/decide"):
            self.biller["status"] = "active"
            return 200, {"approval": {"id": path.split("/")[3], "status": "approved"}}
        raise AssertionError((method, path, body))


class ProvisioningTest(unittest.TestCase):
    def setUp(self):
        gateway.ACCOUNT_KEY = "account-key"
        gateway.ADMIN_KEY = "admin-key"
        gateway.MODE = "live"
        gateway.URL = "http://kuloffice:8080/v1/integrations/kulpay-gateway/events"

    def run_main(self, fake, have_incoming=False, have_service=False):
        gateway.request = fake
        gateway.HAVE_INCOMING_SECRET = have_incoming
        gateway.HAVE_SERVICE_SECRET = have_service
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            gateway.main()
        return stdout.getvalue(), stderr.getvalue()

    def test_creates_both_feeds_and_outputs_only_environment_assignments(self):
        fake = FakeGateway()
        stdout, stderr = self.run_main(fake)
        self.assertEqual(
            stdout.splitlines(),
            [
                "KULOFFICE_INCOMING_TRANSFERS_WEBHOOK_SECRETS=incoming-new",
                "KULOFFICE_PAYMENT_ACCEPTANCE_WEBHOOK_SECRETS=service-new",
            ],
        )
        self.assertNotIn("incoming-new", stderr)
        self.assertNotIn("service-new", stderr)
        incoming_create = next(call for call in fake.calls if call[:2] == ("POST", "/webhook-endpoints"))
        self.assertEqual(incoming_create[2], "account-key")
        self.assertEqual(
            incoming_create[3]["event_types"], ["incoming_transfer.*", "bill_invoice.*", "bill_remittance.*", "bill_subscription.*", "biller.integration_status", "biller.technical_contact_replaced"]
        )
        sink_create = next(call for call in fake.calls if call[:2] == ("POST", "/admin/service-event-sinks"))
        self.assertEqual(sink_create[2], "admin-key")
        self.assertEqual(sink_create[3]["event_types"], ["payment.*"])

    def test_reuses_existing_feeds_when_the_deployment_has_their_secrets(self):
        fake = FakeGateway(
            incoming={"id": "wh_1", "mode": "live", "url": gateway.URL, "status": "active", "event_types": ["incoming_transfer.*"]},
            sink={"id": "sink_1", "mode": "live", "url": gateway.URL, "enabled": True, "event_types": ["payment.*"]},
        )
        stdout, _ = self.run_main(fake, have_incoming=True, have_service=True)
        self.assertEqual(stdout, "")
        self.assertFalse(any(path.endswith("/roll-secret") for _, path, _, _ in fake.calls))

    def test_recovers_missing_secrets_with_graceful_rotation_and_repairs_sink(self):
        fake = FakeGateway(
            incoming={"id": "wh_1", "mode": "live", "url": gateway.URL, "status": "active", "event_types": ["incoming_transfer.*"]},
            sink={"id": "sink_1", "mode": "live", "url": "http://old/events", "enabled": False, "event_types": ["payment.succeeded"]},
        )
        stdout, _ = self.run_main(fake)
        self.assertIn("KULOFFICE_INCOMING_TRANSFERS_WEBHOOK_SECRETS=incoming-rolled", stdout)
        self.assertIn("KULOFFICE_PAYMENT_ACCEPTANCE_WEBHOOK_SECRETS=service-rolled", stdout)
        patch = next(call for call in fake.calls if call[:2] == ("PATCH", "/admin/service-event-sinks/sink_1"))
        self.assertEqual(patch[3]["url"], gateway.URL)
        self.assertTrue(patch[3]["enabled"])
        rotations = [call for call in fake.calls if call[1].endswith("/roll-secret")]
        self.assertEqual(len(rotations), 2)
        self.assertTrue(all(call[3] == {"grace": "24h"} for call in rotations))

    def test_refuses_to_duplicate_an_incoming_feed_at_another_url(self):
        fake = FakeGateway(
            incoming={"id": "wh_old", "mode": "live", "url": "https://old.example/events", "status": "active", "event_types": ["incoming_transfer.*"]}
        )
        gateway.request = fake
        gateway.HAVE_INCOMING_SECRET = True
        with self.assertRaisesRegex(RuntimeError, "remove or migrate it explicitly"):
            gateway.ensure_incoming_endpoint()
        self.assertFalse(any(call[:2] == ("POST", "/webhook-endpoints") for call in fake.calls))


class AccountEventsTest(unittest.TestCase):
    def setUp(self):
        gateway.ACCOUNT_KEY = "account-key"
        gateway.ADMIN_KEY = "admin-key"
        gateway.MODE = "live"
        gateway.URL = "http://kuloffice:8080/v1/integrations/kulpay-gateway/events"
        gateway.HAVE_INCOMING_SECRET = True

    def test_a_new_endpoint_takes_the_bills_events(self):
        fake = FakeGateway()
        gateway.request = fake
        gateway.HAVE_INCOMING_SECRET = False
        with contextlib.redirect_stderr(io.StringIO()):
            gateway.ensure_incoming_endpoint()
        created = [c for c in fake.calls if c[0] == "POST" and c[1] == "/webhook-endpoints"][0]
        self.assertEqual(
            created[3]["event_types"], ["incoming_transfer.*", "bill_invoice.*", "bill_remittance.*", "bill_subscription.*", "biller.integration_status", "biller.technical_contact_replaced"]
        )

    def test_an_existing_endpoint_is_subscribed_to_the_bills_events(self):
        fake = FakeGateway(incoming={"id": "wh_1", "mode": "live", "url": gateway.URL, "status": "active", "event_types": ["incoming_transfer.*"]})
        gateway.request = fake
        with contextlib.redirect_stderr(io.StringIO()):
            gateway.ensure_incoming_endpoint()
        patched = [c for c in fake.calls if c[0] == "PATCH"]
        self.assertEqual(len(patched), 1)
        self.assertEqual(
            patched[0][3]["event_types"],
            ["bill_invoice.*", "bill_remittance.*", "bill_subscription.*", "biller.integration_status", "biller.technical_contact_replaced",
             "incoming_transfer.*"]
        )

    def test_an_endpoint_with_everything_is_left_alone(self):
        fake = FakeGateway(incoming={"id": "wh_1", "mode": "live", "url": gateway.URL, "status": "active", "event_types": ["*"]})
        gateway.request = fake
        with contextlib.redirect_stderr(io.StringIO()):
            gateway.ensure_incoming_endpoint()
        self.assertEqual([c for c in fake.calls if c[0] == "PATCH"], [])


class PartnersKeyTest(unittest.TestCase):
    def setUp(self):
        gateway.ACCOUNT_KEY = "account-key"
        gateway.ADMIN_KEY = "admin-key"
        gateway.MODE = "live"
        gateway.URL = "http://kuloffice:8080/v1/integrations/kulpay-gateway/events"
        gateway.ACCOUNT_ID = "acc_kuloffice"
        gateway.HAVE_INCOMING_SECRET = True
        gateway.HAVE_SERVICE_SECRET = True

    def run_main(self, fake):
        gateway.request = fake
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            gateway.main()
        return stdout.getvalue(), stderr.getvalue()

    def test_issues_the_partners_key_once_on_kuloffices_account(self):
        gateway.BILLER_PROVISIONING, gateway.HAVE_PARTNERS_KEY = True, False
        fake = FakeGateway(
            incoming={"id": "wh_1", "mode": "live", "url": gateway.URL, "status": "active", "event_types": ["*"]},
            sink={"id": "sink_1", "mode": "live", "url": gateway.URL, "enabled": True, "event_types": ["payment.*"]},
        )
        stdout, stderr = self.run_main(fake)
        self.assertEqual(stdout.splitlines(), ["KULOFFICE_BILLER_PROVISIONING_GATEWAY_API_KEY=partners-new"])
        self.assertNotIn("partners-new", stderr)
        issued = next(c for c in fake.calls if c[1] == "/admin/accounts/acc_kuloffice/keys")
        self.assertEqual(issued[2], "admin-key")
        self.assertEqual(issued[3]["scopes"], ["service:partners:write"])

        gateway.HAVE_PARTNERS_KEY = True
        fake = FakeGateway(
            incoming={"id": "wh_1", "mode": "live", "url": gateway.URL, "status": "active", "event_types": ["*"]},
            sink={"id": "sink_1", "mode": "live", "url": gateway.URL, "enabled": True, "event_types": ["payment.*"]},
        )
        stdout, _ = self.run_main(fake)
        self.assertEqual(stdout, "")
        self.assertFalse(any(c[1].startswith("/admin/accounts/") and c[1].endswith("/keys") for c in fake.calls))

    def tearDown(self):
        gateway.BILLER_PROVISIONING, gateway.HAVE_PARTNERS_KEY = False, False


class KulOfficeBillerTest(unittest.TestCase):
    def setUp(self):
        gateway.ADMIN_KEY = "admin-key"
        gateway.ACCOUNT_ID = "acc_kuloffice"
        gateway.CHECKER_KEY = "checker-key"

    def ensure(self, fake):
        gateway.request = fake
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            summary = gateway.ensure_kuloffice_biller()
        return summary, stderr.getvalue()

    def test_a_missing_biller_is_created_activated_and_approved(self):
        fake = FakeGateway(biller=None)
        summary, stderr = self.ensure(fake)
        self.assertEqual(summary, "created, invoice product added, activation requested, activated")
        self.assertEqual(stderr.strip(), "KulOffice biller KULPAY: created, invoice product added, activation requested, activated")
        self.assertNotIn("admin-key", stderr)
        self.assertNotIn("checker-key", stderr)
        steps = [(c[0], c[1].split("?")[0], c[2]) for c in fake.calls]
        self.assertEqual(steps, [
            ("GET", "/admin/billers/KULPAY", "admin-key"),
            ("POST", "/admin/billers", "admin-key"),
            ("POST", "/admin/billers/KULPAY/products", "admin-key"),
            ("GET", "/admin/approvals", "admin-key"),
            ("POST", "/admin/billers/KULPAY/status", "admin-key"),
            ("POST", "/admin/approvals/apr_new/decide", "checker-key"),
        ])
        created = fake.calls[1][3]
        self.assertEqual(created, {
            "code": "KULPAY", "name": "KulPay", "category": "other", "country": "MZ",
            "support_email": "developers@pavulla.com", "tenant_id": "acc_kuloffice",
            "presentment_modes": ["push"], "remit_bank": "FNB", "remit_account": "0028000090002922",
            "remit_frequency": "daily",
        })
        product = fake.calls[2][3]
        self.assertEqual((product["code"], product["amount_rule"], product["shape"], product["enabled"]),
                         ("FATURA", "presented", "postpaid", True))
        self.assertIn("subject_id=bil_new", fake.calls[3][1])
        self.assertEqual(fake.calls[4][3]["status"], "active")
        self.assertTrue(fake.calls[5][3]["approve"])

    def test_an_active_biller_without_an_invoice_product_gets_one(self):
        fake = FakeGateway(products=[{"code": "OTHER", "amount_rule": "fixed", "enabled": True}])
        summary, _ = self.ensure(fake)
        self.assertEqual(summary, "invoice product added")
        self.assertEqual([c[:2] for c in fake.calls], [("GET", "/admin/billers/KULPAY"), ("POST", "/admin/billers/KULPAY/products")])

    def test_an_active_biller_is_only_read(self):
        fake = FakeGateway()
        summary, _ = self.ensure(fake)
        self.assertEqual(summary, "already active")
        self.assertEqual([c[:2] for c in fake.calls], [("GET", "/admin/billers/KULPAY")])

    def test_a_biller_made_by_hand_without_its_organisation_is_claimed(self):
        fake = FakeGateway(biller={"id": "bil_1", "code": "KULPAY", "status": "active"})
        summary, _ = self.ensure(fake)
        self.assertEqual(summary, "claimed for KulOffice's account")
        patch = next(c for c in fake.calls if c[0] == "PATCH")
        self.assertEqual((patch[1], patch[2], patch[3]), ("/admin/billers/KULPAY", "admin-key", {"tenant_id": "acc_kuloffice"}))

    def test_a_biller_of_another_tenant_fails_without_changes(self):
        fake = FakeGateway(biller={**ACTIVE_BILLER, "tenant_id": "acc_someone_else", "status": "draft"})
        gateway.request = fake
        with self.assertRaisesRegex(RuntimeError, "belongs to another account"):
            gateway.ensure_kuloffice_biller()
        self.assertEqual([c[:2] for c in fake.calls], [("GET", "/admin/billers/KULPAY")])

    def test_a_pending_activation_is_approved_without_a_second_request(self):
        fake = FakeGateway(
            biller={**ACTIVE_BILLER, "status": "draft"},
            approvals=[{"id": "apr_other", "kind": "bill.product_limits"},
                       {"id": "apr_pending", "kind": "bill.biller_status"}],
        )
        summary, _ = self.ensure(fake)
        self.assertEqual(summary, "activated")
        self.assertFalse(any(c[1] == "/admin/billers/KULPAY/status" for c in fake.calls))
        decided = [c for c in fake.calls if c[1].endswith("/decide")]
        self.assertEqual([(c[1], c[2]) for c in decided], [("/admin/approvals/apr_pending/decide", "checker-key")])

    def test_main_turns_cash_deposits_on_unless_told_not_to(self):
        gateway.ACCOUNT_KEY, gateway.MODE = "account-key", "live"
        gateway.HAVE_INCOMING_SECRET = gateway.HAVE_SERVICE_SECRET = True
        for on in (True, False):
            fake = FakeGateway(
                incoming={"id": "wh_1", "mode": "live", "url": gateway.URL, "status": "active", "event_types": ["*"]},
                sink={"id": "sink_1", "mode": "live", "url": gateway.URL, "enabled": True, "event_types": ["payment.*"]},
            )
            gateway.request, gateway.CASH_IN_INCOMING = fake, on
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                gateway.main()
            put = ("PUT", "/admin/accounts/acc_kuloffice/cash-in-incoming") in [c[:2] for c in fake.calls]
            self.assertEqual(put, on)
        gateway.CASH_IN_INCOMING = True

    def test_main_ensures_the_biller(self):
        gateway.ACCOUNT_KEY, gateway.MODE = "account-key", "live"
        gateway.HAVE_INCOMING_SECRET = gateway.HAVE_SERVICE_SECRET = True
        fake = FakeGateway(
            incoming={"id": "wh_1", "mode": "live", "url": gateway.URL, "status": "active", "event_types": ["*"]},
            sink={"id": "sink_1", "mode": "live", "url": gateway.URL, "enabled": True, "event_types": ["payment.*"]},
            biller=None,
        )
        gateway.request = fake
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            gateway.main()
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(fake.biller["status"], "active")


if __name__ == "__main__":
    unittest.main()
