import tempfile
import unittest

from jobqueue import kinds, paths


class TestKinds(unittest.TestCase):
    def setUp(self):
        self.reg = kinds.load()
        self.pi = paths.Paths("/home/mitlab/Research", "pi")
        self.jetson = paths.Paths("/home/ari/research", "jetson")

    def test_registry_ships_mmlupro_and_raw(self):
        self.assertIn("mmlupro", self.reg)
        self.assertIn("raw", self.reg)

    def test_validate_accepts_known_params(self):
        got = kinds.validate(self.reg, "mmlupro",
                             {"model": "e4b", "subset": "s2", "thinking": "off"})
        self.assertEqual(got["model"], "e4b")

    def test_validate_fills_defaults(self):
        got = kinds.validate(self.reg, "mmlupro", {"model": "e2b", "subset": "s1"})
        self.assertEqual(got["thinking"], "off")

    def test_validate_rejects_unknown_kind(self):
        with self.assertRaises(kinds.ValidationError):
            kinds.validate(self.reg, "nonsense", {})

    def test_validate_rejects_bad_enum_value(self):
        with self.assertRaises(kinds.ValidationError) as cm:
            kinds.validate(self.reg, "mmlupro",
                           {"model": "e9b", "subset": "s1", "thinking": "off"})
        self.assertIn("e9b", str(cm.exception))

    def test_validate_rejects_unexpected_param(self):
        with self.assertRaises(kinds.ValidationError):
            kinds.validate(self.reg, "mmlupro",
                           {"model": "e2b", "subset": "s1", "colour": "green"})

    def test_pi_command_uses_the_pi_run_script(self):
        got = kinds.resolve(self.reg, "mmlupro",
                            {"model": "e4b", "subset": "s2", "thinking": "off"}, self.pi)
        self.assertEqual(got["label"], "mmlupro-e4b-s2")
        self.assertEqual(got["output_dir"], "mmlupro100-e4b-s2")
        self.assertIn("./std_mmlupro.sh e4b", got["command"])
        self.assertIn("SUBSET=s2", got["command"])
        self.assertNotIn("SRVLOG", got["env"])

    def test_jetson_command_sets_srvlog_from_the_output_dir(self):
        got = kinds.resolve(self.reg, "mmlupro",
                            {"model": "e4b", "subset": "s2", "thinking": "off"},
                            self.jetson)
        self.assertIn("./std_mmlupro_jetson.sh e4b", got["command"])
        self.assertEqual(got["env"]["SRVLOG"],
                         "/home/ari/research/stdbench/mmlupro100-e4b-s2/server.log")

    def test_thinking_on_appends_think_to_output_dir_and_srvlog(self):
        got = kinds.resolve(self.reg, "mmlupro",
                            {"model": "e4b", "subset": "s2", "thinking": "on"},
                            self.jetson)
        # Both gain the suffix. The label becomes the measured directory name,
        # which run_detail.py:42 uses to match a run to its telemetry; if a
        # thinking run were labelled the same as the baseline it would collide.
        self.assertEqual(got["label"], "mmlupro-e4b-s2-think")
        self.assertEqual(got["output_dir"], "mmlupro100-e4b-s2-think")
        self.assertTrue(got["env"]["SRVLOG"].endswith("mmlupro100-e4b-s2-think/server.log"))

    def test_thinking_selects_a_different_baseline(self):
        off = kinds.resolve(self.reg, "mmlupro",
                            {"model": "e2b", "subset": "s1", "thinking": "off"}, self.pi)
        on = kinds.resolve(self.reg, "mmlupro",
                           {"model": "e2b", "subset": "s1", "thinking": "on"}, self.pi)
        self.assertEqual(off["baseline"], "mmlupro-baseline")
        self.assertEqual(on["baseline"], "mmlupro-thinking-on")

    def test_a_thinking_run_cannot_collide_with_its_baseline(self):
        """run_detail.py:42 finds a run's telemetry by matching the measured
        directory name, which is built from the label. Two labels that differ
        only by condition would make that lookup return whichever ran last."""
        off = kinds.resolve(self.reg, "mmlupro",
                            {"model": "e4b", "subset": "s2", "thinking": "off"},
                            self.jetson)
        on = kinds.resolve(self.reg, "mmlupro",
                           {"model": "e4b", "subset": "s2", "thinking": "on"},
                           self.jetson)
        self.assertNotEqual(off["label"], on["label"])
        self.assertNotEqual(off["output_dir"], on["output_dir"])

    def test_raw_kind_wraps_a_free_command(self):
        got = kinds.resolve(self.reg, "raw",
                            {"label": "smoke", "command": "./std_run.sh queue"}, self.pi)
        self.assertEqual(got["label"], "smoke")
        self.assertIn("./std_run.sh queue", got["command"])
        self.assertIsNone(got["baseline"])

    def test_raw_label_rejects_shell_metacharacters(self):
        with self.assertRaises(kinds.ValidationError):
            kinds.validate(self.reg, "raw", {"label": "a; rm -rf /", "command": "true"})


class TestBoardMemory(unittest.TestCase):
    def setUp(self):
        self.reg = kinds.load()

    def resolve(self, board, model):
        p = paths.Paths("/tmp/x", board)
        return kinds.resolve(self.reg, "mmlupro",
                             {"model": model, "subset": "s1", "thinking": "on"}, p)

    def test_the_jetson_e4b_threshold_is_its_own(self):
        # 5,400 refused an idle Jetson at 5,257 MB on 2026-09-24; a waived
        # run then started at 5,239 and never fell below 441 MB free.
        self.assertEqual(self.resolve("jetson", "e4b")["memory_mb"], 5200)

    def test_the_pi_and_e2b_keep_the_kind_default(self):
        self.assertEqual(self.resolve("pi", "e4b")["memory_mb"], 5400)
        self.assertEqual(self.resolve("jetson", "e2b")["memory_mb"], 3900)

if __name__ == "__main__":
    unittest.main()
