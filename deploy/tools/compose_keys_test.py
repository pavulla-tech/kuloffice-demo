"""The Gateway keys docker-compose.yml writes: the KulOffice service key holds
exactly the operator-issued service scopes it needs, and never accounts:write."""

import pathlib
import re
import unittest


COMPOSE = pathlib.Path(__file__).resolve().parent.parent / "docker-compose.yml"


def key_scopes(key_id):
    text = COMPOSE.read_text()
    block = re.search(r"- id: " + re.escape(key_id) + r"\n(.*?)(?=\n\s*- id: |\n\s*EOF)", text, re.S)
    if block is None:
        raise AssertionError("no key " + key_id + " in docker-compose.yml")
    scopes = re.search(r"^\s*scopes: \[(.*)\]\s*$", block.group(1), re.M)
    if scopes is None:
        raise AssertionError("key " + key_id + " lists no scopes")
    return [s.strip() for s in scopes.group(1).split(",")]


class ServiceKeyScopesTest(unittest.TestCase):
    def test_service_key_holds_the_provisioning_scopes(self):
        self.assertEqual(
            sorted(key_scopes("kuloffice-service")),
            sorted([
                "service:payments:read",
                "service:settlements:read",
                "service:fees:write",
                "service:webhooks:write",
                "service:accounts:write",
                "service:applications:write",
                "service:keys:write",
                "service:connector-sessions:write",
            ]),
        )

    def test_service_key_never_crosses_tenants_by_accounts_write(self):
        scopes = key_scopes("kuloffice-service")
        for forbidden in ("accounts:write", "admin:write", "admin:read", "keys:manage"):
            self.assertNotIn(forbidden, scopes)
        self.assertTrue(all(s.startswith("service:") for s in scopes), scopes)

    def test_account_key_has_no_service_scope(self):
        self.assertFalse(any(s.startswith("service:") for s in key_scopes("kuloffice")))


if __name__ == "__main__":
    unittest.main()
