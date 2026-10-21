import importlib.util
import os
import pathlib
import unittest
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).with_name("merchant_bindings.py")
SPEC = importlib.util.spec_from_file_location("merchant_bindings", MODULE_PATH)
bindings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bindings)

ENV = {
    "GATEWAY_ACCOUNT_ID": "2nXyZ0aBcDeFgHiJkLmNoPqRsTu",
    "GATEWAY_KULOFFICE_CLIENT_SECRET": "client-secret",
    "KULOFFICE_CHECKOUT_PROVIDER_WAKEUP_SIGNING_SECRETS": "current-secret-0001,old-secret-000001",
    "BINDING_MODE": "platform",
}


class PlatformBindingTest(unittest.TestCase):
    def test_platform_binding_pays_kulpay(self):
        with mock.patch.dict(os.environ, ENV, clear=True):
            body = bindings.platform_body()
        self.assertEqual(body["account_id"], ENV["GATEWAY_ACCOUNT_ID"])
        self.assertEqual((body["mode"], body["method"], body["driver"]), ("live", "kulpay_balance", "kulpay_balance"))
        config = body["config"]
        self.assertEqual(config["destination_account_id"], "platform")
        self.assertEqual(config["destination_product_id"], "platform")
        self.assertEqual(config["application_id"], "kulpay-platform")
        self.assertEqual(config["signing_secret"], "current-secret-0001")
        self.assertEqual(config["client_secret"], "client-secret")

    def test_platform_application_follows_kuloffice(self):
        env = dict(ENV, KULOFFICE_CHECKOUT_PROVIDER_PLATFORM_APPLICATION_ID="kulpay-own")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(bindings.platform_body()["config"]["application_id"], "kulpay-own")

    def test_main_saves_only_the_platform_binding(self):
        saved = []
        with mock.patch.dict(os.environ, ENV, clear=True), mock.patch.object(bindings, "save", saved.append):
            bindings.main()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["label"], "KulPay balance (platform)")


if __name__ == "__main__":
    unittest.main()
