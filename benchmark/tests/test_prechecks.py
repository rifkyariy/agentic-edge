import json
import os
import tempfile
import unittest

from jobqueue import paths, prechecks


class FakeProbe:
    def __init__(self, mem=9000, busy=(), rss=None):
        self._mem, self._busy, self._rss = mem, list(busy), rss or {}

    def mem_available_mb(self):
        return self._mem

    def busy_processes(self):
        return self._busy

    def rss_by_user(self):
        return self._rss


class TestPrechecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = paths.Paths(self.tmp.name, "jetson")
        os.makedirs(self.p.stdbench)
        self.resolved = {"label": "mmlupro-e4b-s2",
                         "output_dir": "mmlupro100-e4b-s2",
                         "memory_mb": 5400,
                         "params": {"subset": "s2"}}
        # The committed subset ids the run will draw from.
        with open(os.path.join(self.p.stdbench,
                               "mmlupro_subset100_s2_samples.json"), "w") as f:
            json.dump([1, 2, 3], f)

    def by_name(self, results, name):
        return next(r for r in results if r["name"] == name)

    def test_all_checks_pass_on_a_clean_board(self):
        out = prechecks.run_all(self.p, self.resolved, FakeProbe())
        self.assertTrue(prechecks.passed(out), out)

    def test_insufficient_memory_fails_and_reports_the_numbers(self):
        out = prechecks.run_all(self.p, self.resolved, FakeProbe(mem=4102))
        mem = self.by_name(out, "memory")
        self.assertFalse(mem["ok"])
        self.assertIn("4102", mem["detail"])
        self.assertIn("5400", mem["detail"])
        self.assertEqual(mem["measured"], 4102)

    def test_memory_failure_names_who_is_using_the_board(self):
        probe = FakeProbe(mem=4102, rss={"someoneelse": 2048})
        out = prechecks.run_all(self.p, self.resolved, probe)
        self.assertIn("someoneelse", self.by_name(out, "memory")["detail"])

    def test_existing_output_dir_fails(self):
        os.makedirs(os.path.join(self.p.stdbench, "mmlupro100-e4b-s2"))
        out = prechecks.run_all(self.p, self.resolved, FakeProbe())
        stale = self.by_name(out, "output_dir")
        self.assertFalse(stale["ok"])
        # A stale lm-eval cache there is replayed, not regenerated.
        self.assertIn("already exists", stale["detail"])

    def test_missing_subset_ids_fails(self):
        os.remove(os.path.join(self.p.stdbench, "mmlupro_subset100_s2_samples.json"))
        out = prechecks.run_all(self.p, self.resolved, FakeProbe())
        self.assertFalse(self.by_name(out, "subset_ids")["ok"])

    def test_subset_check_is_skipped_for_jobs_without_a_subset(self):
        resolved = dict(self.resolved, params={})
        out = prechecks.run_all(self.p, resolved, FakeProbe())
        self.assertTrue(self.by_name(out, "subset_ids")["ok"])
        self.assertIn("no subset", self.by_name(out, "subset_ids")["detail"])

    def test_busy_board_fails(self):
        out = prechecks.run_all(self.p, self.resolved, FakeProbe(busy=["lm_eval"]))
        busy = self.by_name(out, "board_idle")
        self.assertFalse(busy["ok"])
        self.assertIn("lm_eval", busy["detail"])

    def test_memory_check_is_skipped_when_the_kind_declares_no_requirement(self):
        resolved = dict(self.resolved, memory_mb=None)
        out = prechecks.run_all(self.p, resolved, FakeProbe(mem=10))
        self.assertTrue(self.by_name(out, "memory")["ok"])


if __name__ == "__main__":
    unittest.main()
