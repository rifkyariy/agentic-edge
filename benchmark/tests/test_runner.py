import json
import os
import tempfile
import unittest

from jobqueue import events, fingerprint, kinds, paths, runner, store

GOOD_ARGS = ("llama-server -m /m/gemma-4-E4B.gguf -c 8192 --cache-ram 0 "
             "-rea off --reasoning-budget -1")
BAD_ARGS = "llama-server -m /m/gemma-4-E4B.gguf -c 8192 --cache-ram 0 -ngl 99"


class FakeProbe:
    def __init__(self, mem=9000):
        self.mem = mem

    def mem_available_mb(self):
        return self.mem

    def busy_processes(self):
        return []

    def rss_by_user(self):
        return {}


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = paths.Paths(self.tmp.name, "jetson")
        os.makedirs(self.p.stdbench)
        with open(os.path.join(self.p.stdbench,
                               "mmlupro_subset100_s2_samples.json"), "w") as f:
            json.dump([1], f)
        with open(os.path.join(self.p.stdbench,
                               "mmlupro_subset100_s3_samples.json"), "w") as f:
            json.dump([1], f)
        self.registry = kinds.load()
        self.baselines = fingerprint.load_baselines()
        self.executed = []

    def make(self, args=GOOD_ARGS, rc=0, done=True, mem=9000):
        def exec_fn(command, env, cwd, log_path):
            self.executed.append(command)
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a") as f:
                f.write("fake run of %s\n" % command)
            if done:
                # The .done marker lands in the job's own output directory.
                label = command.split()[1]
                out = os.path.join(self.p.stdbench,
                                   label.replace("mmlupro-", "mmlupro100-"))
                os.makedirs(out, exist_ok=True)
                open(os.path.join(out, ".done"), "w").close()
            return rc

        return runner.Runner(self.p, self.registry, self.baselines,
                             exec_fn=exec_fn, probe=FakeProbe(mem),
                             capture_fn=lambda: fingerprint.capture(
                                 runner=lambda cmd, **kw:
                                 args if cmd[0] == "ps" else "{}"))

    def queue_one(self, **params):
        p = dict({"model": "e4b", "subset": "s2", "thinking": "off"}, **params)
        resolved = kinds.resolve(self.registry, "mmlupro", p, self.p)
        job = store.new_job(kind="mmlupro", params=resolved["params"],
                            label=resolved["label"],
                            output_dir=resolved["output_dir"],
                            command=resolved["command"], env=resolved["env"])
        return store.add(self.p, job)

    def drain(self, r, limit=10):
        for _ in range(limit):
            if not r.tick():
                break

    def test_a_clean_job_runs_to_completed(self):
        job = self.queue_one()
        r = self.make()
        self.drain(r)
        self.assertEqual(store.get(self.p, job["id"])["state"], "completed")
        self.assertEqual(len(self.executed), 1)

    def test_the_command_that_runs_is_the_resolved_one(self):
        self.queue_one()
        self.drain(self.make())
        self.assertIn("./run_measured.sh mmlupro-e4b-s2", self.executed[0])
        self.assertIn("./std_mmlupro_jetson.sh e4b", self.executed[0])

    def test_failing_precheck_blocks_without_executing(self):
        job = self.queue_one()
        r = self.make(mem=100)
        self.drain(r)
        self.assertEqual(store.get(self.p, job["id"])["state"], "blocked")
        self.assertEqual(self.executed, [])

    def test_precheck_results_are_written_for_the_ui(self):
        job = self.queue_one()
        self.drain(self.make(mem=100))
        with open(os.path.join(self.p.job_dir(job["id"]), "precheck.json")) as f:
            results = json.load(f)
        self.assertFalse(next(r for r in results if r["name"] == "memory")["ok"])

    def test_fingerprint_drift_blocks_without_running_lm_eval(self):
        # The 2026-09-22 Jetson case: no -rea, no --reasoning-budget.
        job = self.queue_one()
        r = self.make(args=BAD_ARGS)
        self.drain(r)
        self.assertEqual(store.get(self.p, job["id"])["state"], "blocked")
        self.assertEqual(self.executed, [])

    def test_fingerprint_is_written_even_when_it_blocks(self):
        job = self.queue_one()
        self.drain(self.make(args=BAD_ARGS))
        with open(os.path.join(self.p.job_dir(job["id"]), "fingerprint.json")) as f:
            fp = json.load(f)
        self.assertFalse(fp["agrees"])
        self.assertIn("reasoning", [r["key"] for r in fp["diff"] if not r["ok"]])

    def test_override_lets_a_drifting_job_run_and_records_that_it_did(self):
        job = self.queue_one()
        store.update(self.p, job["id"], override_fingerprint=True)
        self.drain(self.make(args=BAD_ARGS))
        self.assertEqual(store.get(self.p, job["id"])["state"], "completed")
        names = [e["event"] for e in events.read(self.p, job["id"])[0]]
        self.assertIn("fingerprint_overridden", names)

    def test_missing_done_marker_is_a_failure_even_on_exit_zero(self):
        # std_mmlupro_jetson.sh ends on `echo finished` and always returns 0,
        # so exit status is not evidence. The .done marker is.
        job = self.queue_one()
        self.drain(self.make(rc=0, done=False))
        self.assertEqual(store.get(self.p, job["id"])["state"], "failed")

    def test_nonzero_exit_with_done_marker_still_completes(self):
        job = self.queue_one()
        self.drain(self.make(rc=3, done=True))
        self.assertEqual(store.get(self.p, job["id"])["state"], "completed")
        self.assertEqual(store.get(self.p, job["id"])["exit_code"], 3)

    def test_only_one_job_runs_even_with_several_queued(self):
        self.queue_one()
        self.queue_one(subset="s3")
        r = self.make()
        r.tick()
        self.assertLessEqual(len(self.executed), 1)

    def test_tick_returns_false_on_an_empty_queue(self):
        self.assertFalse(self.make().tick())

    def test_events_record_the_whole_lifecycle(self):
        job = self.queue_one()
        self.drain(self.make())
        names = [e["event"] for e in events.read(self.p, job["id"])[0]]
        for expected in ("precheck_passed", "fingerprint_ok", "started", "completed"):
            self.assertIn(expected, names)

    def test_a_blocked_job_does_not_block_the_queue_forever(self):
        first = self.queue_one()
        r = self.make(mem=100)
        self.drain(r)
        self.assertEqual(store.get(self.p, first["id"])["state"], "blocked")
        self.assertIsNone(store.active(self.p))

    def test_a_failing_exec_is_reported_not_raised(self):
        job = self.queue_one()
        def boom(command, env, cwd, log_path):
            raise OSError("no such file")
        r = runner.Runner(self.p, self.registry, self.baselines, exec_fn=boom,
                          probe=FakeProbe(),
                          capture_fn=lambda: fingerprint.capture(
                              runner=lambda cmd, **kw:
                              GOOD_ARGS if cmd[0] == "ps" else "{}"))
        r.tick()
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "failed")
        self.assertIn("no such file", got["note"])


if __name__ == "__main__":
    unittest.main()
