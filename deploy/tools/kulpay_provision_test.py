"""bin/kulpay provision: the steps it runs, in order (read from the script,
since running it needs the whole stack)."""

import pathlib
import re
import unittest

KULPAY = pathlib.Path(__file__).resolve().parent.parent / "bin" / "kulpay"


def function(name):
    text = KULPAY.read_text()
    match = re.search(r"^" + re.escape(name) + r"\(\) \{\n(.*?)^\}", text, re.S | re.M)
    if not match:
        raise AssertionError(name + " not found in bin/kulpay")
    return match.group(1)


class ProvisionTest(unittest.TestCase):
    def assert_in_order(self, body, steps):
        at = -1
        for step in steps:
            found = body.find(step, at + 1)
            self.assertGreater(found, at, step + " missing or out of order")
            at = found

    def test_provision_restores_the_platform_wallet_after_the_gateway_events(self):
        self.assert_in_order(function("cmd_provision"), ["tools/init.sh", "scripts/gateway-kuloffice.sh", "platform_wallet", "scripts/solange-kulpay.sh"])

    def test_the_platform_wallet_is_make_platform_wallet(self):
        body = function("platform_wallet")
        self.assertIn("BINDING_MODE=platform", body)
        self.assertIn("/tools/merchant_bindings.py", body)


if __name__ == "__main__":
    unittest.main()
