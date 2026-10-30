import importlib.util
import pathlib
import unittest

SPEC = importlib.util.spec_from_file_location("live_connectors", pathlib.Path(__file__).with_name("live_connectors.py"))
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)


class LiveConnectorsTest(unittest.TestCase):
    def test_both_real_bindings_are_quiet(self):
        rows = [{"method": "mpesa", "driver": "mpesa", "enabled": True}, {"method": "emola", "driver": "emola", "enabled": True},
                {"method": "card", "driver": "simulator", "enabled": True}]
        self.assertEqual(live.warnings(rows, {"card"}), [])

    def test_a_missing_or_disabled_binding_is_named(self):
        found = live.warnings([{"method": "mpesa", "enabled": False}], set())
        self.assertEqual(len(found), 2)
        self.assertIn("no live mpesa binding", found[0])
        self.assertIn("no live emola binding", found[1])

    def test_a_binding_the_simulator_plays_is_not_the_real_one(self):
        rows = [{"method": "mpesa", "enabled": True}, {"method": "emola", "enabled": True}]
        found = live.warnings(rows, {"mpesa", "card"})
        self.assertEqual(len(found), 1)
        self.assertIn("live mpesa is the PSP simulator's", found[0])


    def test_the_simulators_methods_follow_compose(self):
        self.assertEqual(live.simulated_methods(""), {"mpesa", "emola", "card"})
        self.assertEqual(live.simulated_methods("card"), {"card"})
        self.assertEqual(live.simulated_methods("mpesa, card"), {"mpesa", "card"})
        self.assertEqual(live.simulated_methods("mpesa card"), {"mpesa", "card"})


if __name__ == "__main__":
    unittest.main()
