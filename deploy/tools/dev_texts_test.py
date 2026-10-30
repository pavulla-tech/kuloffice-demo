"""tools/dev_texts.json: well formed, one text per event and channel, and the
texts KulOffice waits for before it acts (gated events) all there.

With KULOFFICE_SRC pointing at a KulOffice checkout, each text that KulOffice's
catalogue also has must use the same variables as the catalogue's default."""

import json
import os
import pathlib
import re
import unittest

TEXTS = pathlib.Path(__file__).with_name("dev_texts.json")
# notificationtemplate.Ready in KulOffice's agents package: without an
# approved SMS no agent application starts and no operator code is sent.
GATED = ["agent.application_received", "agent.more_info", "agent.approved", "agent.rejected", "agent.operator_code"]
VARIABLE = re.compile(r"\{([a-z_]+)\}")


def load():
    with TEXTS.open(encoding="utf-8") as f:
        return json.load(f)


class DevTextsTest(unittest.TestCase):
    def test_one_text_per_event_and_channel(self):
        texts = load()["texts"]
        keys = [(t["event"], t["channel"]) for t in texts]
        self.assertEqual(len(keys), len(set(keys)))
        for t in texts:
            self.assertIn(t["channel"], ("sms", "inbox"))
            self.assertTrue(t["text"].strip())

    def test_the_gated_agent_texts_are_seeded_as_sms(self):
        keys = {(t["event"], t["channel"]) for t in load()["texts"]}
        for event in GATED:
            self.assertIn((event, "sms"), keys)
        self.assertEqual(load()["language"], "pt")

    @unittest.skipUnless(os.environ.get("KULOFFICE_SRC"), "KULOFFICE_SRC not set")
    def test_variables_match_kuloffices_catalogue(self):
        catalogue = (pathlib.Path(os.environ["KULOFFICE_SRC"]) / "internal" / "notificationcatalog" / "catalog.go").read_text(encoding="utf-8")
        checked = 0
        for t in load()["texts"]:
            match = re.search(r'"' + re.escape(t["event"]) + r'":\s*smsOnly\([^,]+,\s*"([^"]*)"\)', catalogue)
            if not match or t["channel"] != "sms":
                continue
            self.assertEqual(set(VARIABLE.findall(t["text"])), set(VARIABLE.findall(match.group(1))), t["event"])
            checked += 1
        self.assertGreaterEqual(checked, len(GATED))


if __name__ == "__main__":
    unittest.main()
