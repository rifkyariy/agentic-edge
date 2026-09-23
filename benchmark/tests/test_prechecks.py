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


class TestBusyProcesses(unittest.TestCase):
    """The probe itself, with only the process table faked."""

    def probe(self, table, deployed=0):
        class P(prechecks.Probe):
            def _pgrep(self, pattern):
                return table.get(pattern, [])

            def deployed_server_pid(self):
                return deployed
        return P()

    def test_the_pis_deployed_va_llm_server_does_not_count_as_busy(self):
        # The regression: va-llm is always up on the Pi, so board_idle
        # refused every job there before a single run could start.
        probe = self.probe({"[l]lama-server": [812]}, deployed=812)
        self.assertEqual(probe.busy_processes(), [])

    def test_a_second_llama_server_still_counts(self):
        probe = self.probe({"[l]lama-server": [812, 990]}, deployed=812)
        self.assertEqual(probe.busy_processes(), ["llama-server"])

    def test_a_jetson_server_counts_when_no_unit_owns_it(self):
        probe = self.probe({"[l]lama-server": [4100]}, deployed=0)
        self.assertEqual(probe.busy_processes(), ["llama-server"])

    def test_lm_eval_counts_even_with_only_the_deployed_server(self):
        probe = self.probe({"[l]m_eval": [77], "[l]lama-server": [812]},
                           deployed=812)
        self.assertEqual(probe.busy_processes(), ["lm_eval"])


if __name__ == "__main__":
    unittest.main()


class TestReclaimableMemory(unittest.TestCase):
    def test_the_deployed_servers_memory_counts_as_available(self):
        # The Pi idles with E4B resident in va-llm; the run restarts it, so
        # that memory is the run's. 4816 free alone refused every Pi E4B run.
        class P(FakeProbe):
            def reclaimable_mb(self):
                return 2778
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = paths.Paths(tmp.name, "pi")
        got = prechecks._memory(p, {"memory_mb": 5400}, P(mem=4816))
        self.assertTrue(got["ok"], got["detail"])
        self.assertEqual(got["measured"], 7594)

    def test_without_a_deployed_server_nothing_is_added(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = paths.Paths(tmp.name, "jetson")
        got = prechecks._memory(p, {"memory_mb": 5400}, FakeProbe(mem=4816))
        self.assertFalse(got["ok"])


class TestQueueTime(unittest.TestCase):
    """What queue_ctl sees when a job is added, as opposed to the runner."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = paths.Paths(self.tmp.name, "jetson")
        os.makedirs(self.p.stdbench)
        with open(os.path.join(self.p.stdbench,
                               "mmlupro_subset100_s1_samples.json"), "w") as f:
            json.dump([1], f)
        self.resolved = {"label": "mmlupro-e4b-s1-think",
                         "output_dir": "mmlupro100-e4b-s1-think",
                         "memory_mb": 5400, "params": {"subset": "s1"}}

    def by(self, results, name):
        return next(r for r in results if r["name"] == name)

    def test_a_job_behind_a_running_one_can_be_queued(self):
        # The regression: board_idle failed at queue time whenever a job was
        # running, so the web form could never queue the next one.
        busy = FakeProbe(mem=600, busy=["lm_eval", "run_measured"])
        got = prechecks.run_all(self.p, self.resolved, busy, pending=[
            {"id": "j1", "state": "running", "output_dir": "mmlupro100-e2b-s3-think"}],
            ahead="mmlupro-e2b-s3-think")
        self.assertTrue(prechecks.passed(got), got)
        self.assertTrue(self.by(got, "board_idle")["deferred"])
        self.assertTrue(self.by(got, "memory")["deferred"])

    def test_a_run_outside_the_queue_postpones_rather_than_refuses(self):
        got = prechecks.run_all(self.p, self.resolved,
                                FakeProbe(mem=600, busy=["lm_eval"]), pending=[])
        self.assertTrue(prechecks.passed(got))

    def test_the_runner_still_sees_a_busy_board(self):
        got = prechecks.run_all(self.p, self.resolved, FakeProbe(busy=["lm_eval"]))
        self.assertFalse(self.by(got, "board_idle")["ok"])

    def test_an_idle_board_short_of_memory_still_fails_at_queue_time(self):
        got = prechecks.run_all(self.p, self.resolved, FakeProbe(mem=4000), pending=[])
        mem = self.by(got, "memory")
        self.assertFalse(mem["ok"])
        self.assertTrue(mem["overridable"])

    def test_the_same_run_cannot_be_queued_twice(self):
        got = prechecks.run_all(self.p, self.resolved, FakeProbe(), pending=[
            {"id": "j9", "state": "queued", "output_dir": "mmlupro100-e4b-s1-think"}])
        dup = self.by(got, "not_queued")
        self.assertFalse(dup["ok"])
        self.assertFalse(dup["overridable"])
        self.assertIn("j9", dup["detail"])


class TestOverride(unittest.TestCase):
    def test_memory_can_be_overridden_with_a_reason(self):
        o = prechecks.validate_override({"checks": ["memory"],
                                         "reason": "measured peak is 5,008 MB"})
        self.assertEqual(o["checks"], ["memory"])

    def test_nothing_else_can_be_overridden(self):
        for check in ("output_dir", "board_idle", "subset_ids", "not_queued"):
            with self.assertRaises(ValueError):
                prechecks.validate_override({"checks": [check], "reason": "because I said so"})

    def test_a_reason_is_required(self):
        with self.assertRaises(ValueError):
            prechecks.validate_override({"checks": ["memory"], "reason": "ok"})

    def test_blocking_ignores_only_the_overridden_checks(self):
        results = [{"name": "memory", "ok": False}, {"name": "output_dir", "ok": False}]
        left = prechecks.blocking(results, {"checks": ["memory"]})
        self.assertEqual([r["name"] for r in left], ["output_dir"])
