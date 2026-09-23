import os
import tempfile
import time
import unittest

import run_detail


class TestParseRun(unittest.TestCase):
    def test_every_name_the_boards_actually_have(self):
        cases = {
            "mmlupro100-e2b": ("e2b", "s1", "off", None),
            "mmlupro100-e4b-s2": ("e4b", "s2", "off", None),
            "mmlupro100-e2b-s3-think": ("e2b", "s3", "on", None),
            "mmlupro100-e2b.bak": ("e2b", "s1", "off", "bak"),
            "mmlupro100-e2b-smoke": ("e2b", "s1", "off", "smoke"),
            "failed/mmlupro100-e4b-s2-oom-20260921-1303":
                ("e4b", "s2", "off", "oom-20260921-1303"),
            "archive/mmlupro100-e4b-s1-before-rerun-20260922-0950":
                ("e4b", "s1", "off", "before-rerun-20260922-0950"),
        }
        for name, want in cases.items():
            p = run_detail.parse_run(name)
            self.assertEqual((p["model"], p["subset"], p["thinking"], p["tag"]),
                             want, name)

    def test_other_benchmarks_are_not_forced_into_the_pattern(self):
        self.assertIsNone(run_detail.parse_run("tiny1024-e2b"))


class TestMeasuredDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = run_detail.ROOT
        run_detail.ROOT = self.tmp.name
        self.addCleanup(setattr, run_detail, "ROOT", self.old)
        for name in ("mmlupro-e4b-s1-20260921-035846",
                     "mmlupro-e4b-s1-20260922-095215",
                     "mmlupro-e4b-s1-think-20260930-010000",
                     "mmlupro-e4b-s2-20260921-131646",
                     "failed/mmlupro-e4b-s3-20260921-122643-oom"):
            os.makedirs(os.path.join(self.tmp.name, "measured", name))

    def base(self, d):
        return os.path.basename(d) if d else None

    def test_a_thinking_run_never_borrows_the_baselines_telemetry(self):
        # The latent S2 bug: -s1-think-<stamp> did not parse, fell back to
        # s1 and matched whichever s1 run was newest.
        self.assertEqual(self.base(run_detail.measured_dir("e4b", "s1", "on")),
                         "mmlupro-e4b-s1-think-20260930-010000")
        self.assertEqual(self.base(run_detail.measured_dir("e4b", "s1", "off")),
                         "mmlupro-e4b-s1-20260922-095215")

    def test_an_archived_run_gets_its_own_telemetry_not_its_reruns(self):
        ended = time.mktime(time.strptime("20260922-0950", "%Y%m%d-%H%M"))
        self.assertEqual(
            self.base(run_detail.measured_dir("e4b", "s1", "off", ended)),
            "mmlupro-e4b-s1-20260921-035846")

    def test_failed_measured_runs_are_searched_too(self):
        self.assertEqual(self.base(run_detail.measured_dir("e4b", "s3", "off")),
                         "mmlupro-e4b-s3-20260921-122643-oom")

    def test_no_match_is_none_not_a_guess(self):
        self.assertIsNone(run_detail.measured_dir("e2b", "s2", "off"))
