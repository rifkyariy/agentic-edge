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

    def test_the_engine_comes_from_the_name(self):
        # S3: mmlupro-lg writes mmlupro100-lg-<model>-<subset>[-think]. Before
        # the engine was parsed these fell through every view, and a looser
        # pattern would have filed them under the llama.cpp cells.
        cases = {
            "mmlupro100-e4b-s2": ("llama.cpp", "e4b", "s2", "off", None),
            "mmlupro100-lg-e2b-s1": ("little-gemma", "e2b", "s1", "off", None),
            "mmlupro100-lg-e4b-s3-think": ("little-gemma", "e4b", "s3", "on", None),
            "failed/mmlupro100-lg-e4b-s2-oom-20260926-0101":
                ("little-gemma", "e4b", "s2", "off", "oom-20260926-0101"),
        }
        for name, want in cases.items():
            p = run_detail.parse_run(name)
            self.assertEqual((p["engine"], p["model"], p["subset"], p["thinking"],
                              p["tag"]), want, name)


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
                     "failed/mmlupro-e4b-s3-20260921-122643-oom",
                     "mmlupro-lg-e4b-s1-20260926-010000",
                     "mmlupro-lg-e4b-s1-think-20260926-090000"):
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

    def test_engines_never_share_telemetry(self):
        # The little-gemma runs are newer; llama.cpp must not borrow them,
        # and they must not borrow llama.cpp's.
        self.assertEqual(self.base(run_detail.measured_dir("e4b", "s1", "off")),
                         "mmlupro-e4b-s1-20260922-095215")
        self.assertEqual(
            self.base(run_detail.measured_dir("e4b", "s1", "off", engine="little-gemma")),
            "mmlupro-lg-e4b-s1-20260926-010000")
        self.assertEqual(
            self.base(run_detail.measured_dir("e4b", "s1", "on", engine="little-gemma")),
            "mmlupro-lg-e4b-s1-think-20260926-090000")
        self.assertIsNone(run_detail.measured_dir("e4b", "s2", "off", engine="little-gemma"))

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


class TestPaired(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = run_detail.ROOT
        run_detail.ROOT = self.tmp.name
        self.addCleanup(setattr, run_detail, "ROOT", self.old)

    def run_dir(self, name, samples=None, done=True):
        d = os.path.join(self.tmp.name, "stdbench", name)
        os.makedirs(os.path.join(d, "model"))
        if done:
            open(os.path.join(d, ".done"), "w").close()
        if samples is not None:
            import json
            with open(os.path.join(d, "model", "samples_mmlu_pro_law_x.jsonl"), "w") as f:
                for qid, ok, resp in samples:
                    f.write(json.dumps({"doc": {"question_id": qid},
                                        "resps": [[resp]], "exact_match": ok}) + "\n")

    def test_correctness_is_keyed_by_mmlu_pro_question_id(self):
        self.run_dir("mmlupro100-e2b-s1-think",
                     [(70, 1.0, "the answer is (B)"), (12, 0.0, "I think... no")])
        r, = run_detail.paired()["runs"]
        self.assertEqual((r["model"], r["subset"], r["thinking"]), ("e2b", "s1", "on"))
        self.assertEqual(r["correct"], {"70": 1, "12": 0})
        self.assertEqual(r["no_answer"], 1)

    def test_a_run_without_samples_is_listed_not_dropped(self):
        self.run_dir("mmlupro100-e4b-s2", None, done=False)
        r, = run_detail.paired()["runs"]
        self.assertIsNone(r["correct"])
        self.assertFalse(r["done"])

    def test_smoke_tests_and_bak_copies_are_not_candidates(self):
        self.run_dir("mmlupro100-e2b-smoke", [(1, 1.0, "the answer is (A)")])
        self.run_dir("mmlupro100-e2b.bak", [(1, 1.0, "the answer is (A)")])
        self.assertEqual(run_detail.paired()["runs"], [])

    def test_each_run_says_which_engine_served_it(self):
        self.run_dir("mmlupro100-e2b-s1", [(70, 1.0, "the answer is (B)")])
        self.run_dir("mmlupro100-lg-e2b-s1", [(70, 0.0, "the answer is (C)")])
        engines = {r["run"]: r["engine"] for r in run_detail.paired()["runs"]}
        self.assertEqual(engines, {"mmlupro100-e2b-s1": "llama.cpp",
                                   "mmlupro100-lg-e2b-s1": "little-gemma"})

    def test_the_board_baseline_is_llama_cpp_only(self):
        # /compare's Pi-vs-Orin block is a llama.cpp comparison; a little-gemma
        # run must not appear in it as a second Jetson E2B s1.
        self.run_dir("mmlupro100-e2b-s1", [(70, 1.0, "the answer is (B)")])
        self.run_dir("mmlupro100-lg-e2b-s1", [(70, 0.0, "the answer is (C)")])
        self.assertEqual([r["run"] for r in run_detail.baseline()["runs"]],
                         ["mmlupro100-e2b-s1"])
