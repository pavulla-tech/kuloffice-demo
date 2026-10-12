import contextlib
import importlib.util
import io
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("gateway_kuloffice.py")
SPEC = importlib.util.spec_from_file_location("gateway_kuloffice", MODULE_PATH)
gateway = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gateway)


class FakeGateway:
    def __init__(self, incoming=None, sink=None):
        self.incoming = incoming
        self.sink = sink
        self.calls = []

    def __call__(self, method, path, key, body=None):
        self.calls.append((method, path, key, body))
        if method == "GET" and path == "/webhook-endpoints":
            return 200, {"data": [self.incoming] if self.incoming else []}
        if method == "POST" and path == "/webhook-endpoints":
            return 201, {"id": "wh_1", "secret": "incoming-new"}
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
        self.assertEqual(incoming_create[3]["event_types"], ["incoming_transfer.*"])
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


if __name__ == "__main__":
    unittest.main()
