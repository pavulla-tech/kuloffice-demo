"""scripts/gateway-kuloffice.sh with a stand-in for docker compose: what it
switches on in .env on development and other stacks."""

import os
import pathlib
import subprocess
import tempfile
import unittest

DEPLOY = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = DEPLOY / "scripts" / "gateway-kuloffice.sh"


class GatewayKulOfficeScriptTest(unittest.TestCase):
    def run_script(self, env_text, extra=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            env_file = tmp / ".env"
            env_file.write_text(env_text)
            calls = tmp / "calls"
            fake = tmp / "compose"
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "' + str(calls) + '"\n')
            fake.chmod(0o755)
            env = {**os.environ, "ENV_FILE": str(env_file), "COMPOSE": str(fake)}
            env.pop("GATEWAY_BILLER_PROVISIONING", None)
            env.update(extra or {})
            subprocess.run(["sh", str(SCRIPT)], cwd=tmp, env=env, check=True, capture_output=True, text=True)
            return env_file.read_text(), calls.read_text()

    def test_a_development_stack_provisions_billers_and_takes_incoming_transfers(self):
        env, calls = self.run_script("DEV_ADMIN_EMAIL=dev@example.test\nKULOFFICE_INCOMING_TRANSFERS_ENABLED=false\n")
        self.assertIn("KULOFFICE_INCOMING_TRANSFERS_ENABLED=true\n", env)
        self.assertNotIn("KULOFFICE_INCOMING_TRANSFERS_ENABLED=false", env)
        self.assertIn("KULOFFICE_BILLER_PROVISIONING_ENABLED=true\n", env)
        self.assertIn("-e GATEWAY_BILLER_PROVISIONING=1 ", calls)

    def test_another_stack_is_left_as_it_is(self):
        env, calls = self.run_script("DEV_ADMIN_EMAIL=\nKULOFFICE_INCOMING_TRANSFERS_ENABLED=false\n")
        self.assertIn("KULOFFICE_INCOMING_TRANSFERS_ENABLED=false\n", env)
        self.assertNotIn("KULOFFICE_BILLER_PROVISIONING_ENABLED", env)
        self.assertIn("-e GATEWAY_BILLER_PROVISIONING= ", calls)

    def test_zero_leaves_the_billers_out_on_development(self):
        env, calls = self.run_script("DEV_ADMIN_EMAIL=dev@example.test\n", {"GATEWAY_BILLER_PROVISIONING": "0"})
        self.assertNotIn("KULOFFICE_BILLER_PROVISIONING_ENABLED", env)
        self.assertIn("-e GATEWAY_BILLER_PROVISIONING= ", calls)


if __name__ == "__main__":
    unittest.main()
