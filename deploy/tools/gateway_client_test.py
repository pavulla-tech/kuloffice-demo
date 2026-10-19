import contextlib
import importlib.util
import io
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("gateway_client.py")
SPEC = importlib.util.spec_from_file_location("gateway_client", MODULE_PATH)
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)


class FakeKeycloak:
    def __init__(self, found=None, mappers=None):
        self.found = found or []
        self.mappers = mappers or []
        self.calls = []

    def __call__(self, method, path, token=None, body=None, form=None):
        self.calls.append((method, path, token, body, form))
        if path == "/realms/master/protocol/openid-connect/token":
            return 200, {"access_token": "admin-token"}
        if method == "GET" and path.endswith("/clients?clientId=kulpay-gateway"):
            return 200, self.found
        if method == "GET" and path.endswith("/protocol-mappers/models"):
            return 200, self.mappers
        return (204 if method == "PUT" else 201), None


class GatewayClientTest(unittest.TestCase):
    def setUp(self):
        client.CLIENT = "kulpay-gateway"
        client.SECRET = "gateway-secret"
        client.AUDIENCE = "kulpay-backend"
        client.REALM = "kulpay"

    def run_main(self, fake):
        client.call = fake
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            client.main()
        return output.getvalue()

    def test_creates_confidential_service_account_with_api_audience(self):
        fake = FakeKeycloak()
        self.run_main(fake)
        create = next(call for call in fake.calls if call[0] == "POST" and call[1] == "/admin/realms/kulpay/clients")
        settings = create[3]
        self.assertFalse(settings["publicClient"])
        self.assertTrue(settings["serviceAccountsEnabled"])
        self.assertFalse(settings["standardFlowEnabled"])
        self.assertEqual(settings["secret"], "gateway-secret")
        self.assertEqual(settings["protocolMappers"][0]["config"]["included.client.audience"], "kulpay-backend")

    def test_update_preserves_one_existing_audience_mapper(self):
        mapper = {"name": "aud-kulpay-backend"}
        fake = FakeKeycloak(found=[{"id": "internal-id", "clientId": "kulpay-gateway"}], mappers=[mapper])
        self.run_main(fake)
        updates = [call for call in fake.calls if call[:2] == ("PUT", "/admin/realms/kulpay/clients/internal-id")]
        mapper_posts = [call for call in fake.calls if call[0] == "POST" and call[1].endswith("/protocol-mappers/models")]
        self.assertEqual(len(updates), 1)
        self.assertEqual(mapper_posts, [])

    def test_refuses_an_empty_client_secret(self):
        client.SECRET = ""
        with self.assertRaisesRegex(SystemExit, "GATEWAY_KULOFFICE_CLIENT_SECRET is required"):
            client.main()


if __name__ == "__main__":
    unittest.main()
