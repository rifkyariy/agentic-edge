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
        self.started = []

    def make(self, args=GOOD_ARGS, rc=0, done=True, mem=9000):
        class DoneProc:
            """A command that has already finished by the time we look."""
            def __init__(self, rc):
                self.rc, self.pid, self.killed = rc, 4242, False

            def poll(self):
                return self.rc

            def wait(self):
                return self.rc

            def kill(self):
                self.killed = True

        def start_fn(command, env, cwd, log_path):
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
            proc = DoneProc(rc)
            self.started.append(proc)
            return proc

        return runner.Runner(self.p, self.registry, self.baselines,
                             start_fn=start_fn, probe=FakeProbe(mem),
                             sleep=lambda _s: None,
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

    def test_fingerprint_drift_kills_the_run_and_blocks_it(self):
        # The 2026-09-22 Jetson case: no -rea, no --reasoning-budget.
        #
        # The command does start, and must: the run script is what configures
        # the server, so there is nothing truthful to fingerprint until it has
        # begun. What the check buys is killing it during server load instead
        # of finding out three hours later.
        job = self.queue_one()
        r = self.make(args=BAD_ARGS)
        self.drain(r)
        self.assertEqual(store.get(self.p, job["id"])["state"], "blocked")
        self.assertEqual(len(self.executed), 1)
        self.assertTrue(self.started[0].killed, "a drifting run must be killed")

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
        r = runner.Runner(self.p, self.registry, self.baselines, start_fn=boom,
                          probe=FakeProbe(), sleep=lambda _s: None,
                          capture_fn=lambda: fingerprint.capture(
                              runner=lambda cmd, **kw:
                              GOOD_ARGS if cmd[0] == "ps" else "{}"))
        r.tick()
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "failed")
        self.assertIn("no such file", got["note"])


if __name__ == "__main__":
    unittest.main()

# ---------------------------------------------------------------------------
# Fingerprint timing. These are the tests the old suite could not express:
# capture_fn was injected and returned the same value whenever it was called,
# so nothing distinguished "captured before the run started" from "after".
# Capturing before is the bug the whole mechanism exists to prevent — the
# server is not configured yet, so every mmlupro job blocks on flags that the
# run script was about to set.
# ---------------------------------------------------------------------------

class FakeProc:
    def __init__(self, rc=0, exits_after=None):
        self.rc, self.pid, self.killed = rc, 4242, False
        self._polls, self._exits_after = 0, exits_after

    def poll(self):
        self._polls += 1
        if self._exits_after is not None and self._polls >= self._exits_after:
            return self.rc
        return None

    def wait(self):
        return self.rc

    def kill(self):
        self.killed = True


class TestFingerprintTiming(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = paths.Paths(self.tmp.name, "jetson")
        os.makedirs(self.p.stdbench)
        with open(os.path.join(self.p.stdbench,
                               "mmlupro_subset100_s2_samples.json"), "w") as f:
            json.dump([1], f)
        self.registry = kinds.load()
        self.baselines = fingerprint.load_baselines()
        self.order = []
        self.procs = []
        self.now = [1000.0]           # a clock the fake sleep advances

    def make(self, captures, rc=0, done=True, exits_after=None):
        """captures: the server argv seen on each successive poll."""
        seq = list(captures)

        def start_fn(command, env, cwd, log_path):
            self.order.append("started")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            open(log_path, "a").close()
            if done:
                out = os.path.join(self.p.stdbench, "mmlupro100-e4b-s2")
                os.makedirs(out, exist_ok=True)
                open(os.path.join(out, ".done"), "w").close()
            proc = FakeProc(rc=rc, exits_after=exits_after)
            self.procs.append(proc)
            return proc

        def capture_fn():
            self.order.append("captured")
            args = seq.pop(0) if seq else (seq[-1] if seq else "")
            return fingerprint.capture(
                runner=lambda cmd, **kw: args if cmd[0] == "ps" else "{}")

        def sleep(seconds):
            self.now[0] += seconds

        return runner.Runner(self.p, self.registry, self.baselines,
                             start_fn=start_fn, probe=FakeProbe(),
                             capture_fn=capture_fn, sleep=sleep,
                             clock=lambda: self.now[0],
                             pids_fn=lambda: [])

    def queue_one(self, **params):
        p = dict({"model": "e4b", "subset": "s2", "thinking": "off"}, **params)
        r = kinds.resolve(self.registry, "mmlupro", p, self.p)
        return store.add(self.p, store.new_job(
            kind="mmlupro", params=r["params"], label=r["label"],
            output_dir=r["output_dir"], command=r["command"], env=r["env"]))

    def test_the_fingerprint_is_captured_after_the_run_starts(self):
        # The regression. Before the fix the order was captured-then-started,
        # so the flags read belonged to whatever the board had running before.
        self.queue_one()
        self.make([GOOD_ARGS]).tick()
        self.assertEqual(self.order[0], "started")
        self.assertIn("captured", self.order)

    def test_an_empty_server_is_polled_until_it_appears(self):
        # The Jetson has no server until the run script launches one, so the
        # first captures come back empty. That must not be read as drift.
        job = self.queue_one()
        self.make(["", "", GOOD_ARGS]).tick()
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "completed", got["note"])

    def test_a_job_completes_once_the_server_matches(self):
        job = self.queue_one()
        self.drain_ok = self.make(["", GOOD_ARGS]).tick()
        names = [e["event"] for e in events.read(self.p, job["id"])[0]]
        self.assertIn("fingerprint_ok", names)
        self.assertEqual(store.get(self.p, job["id"])["state"], "completed")

    def test_drift_after_the_server_appears_kills_the_run(self):
        job = self.queue_one()
        self.make(["", BAD_ARGS]).tick()
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "blocked")
        self.assertTrue(self.procs[0].killed, "the run must be killed on drift")
        self.assertIn("reasoning", got["note"])

    def test_a_server_that_never_appears_is_a_failure_not_a_silent_pass(self):
        job = self.queue_one()
        self.make([""] * 200).tick()
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "blocked")
        self.assertIn("no llama-server", got["note"])
        self.assertTrue(self.procs[0].killed)

    def test_a_command_that_dies_before_serving_is_judged_on_the_done_marker(self):
        job = self.queue_one()
        self.make([""] * 5, done=False, exits_after=2).tick()
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "failed")
        self.assertIn("no .done marker", got["note"])

    def test_override_lets_a_drifting_run_continue_rather_than_killing_it(self):
        job = self.queue_one()
        store.update(self.p, job["id"], override_fingerprint=True)
        self.make(["", BAD_ARGS]).tick()
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "completed")
        self.assertFalse(self.procs[0].killed)

    def test_a_kind_without_a_baseline_does_not_wait_for_a_server(self):
        # raw declares no baseline; it must not sit polling for 420s.
        r = kinds.resolve(self.registry, "raw",
                          {"label": "smoke", "command": "true"}, self.p)
        store.add(self.p, store.new_job(
            kind="raw", params=r["params"], label=r["label"],
            output_dir=r["output_dir"], command=r["command"], env=r["env"]))
        os.makedirs(os.path.join(self.p.stdbench, "smoke"), exist_ok=True)
        open(os.path.join(self.p.stdbench, "smoke", ".done"), "w").close()
        self.make([""] * 5, done=False).tick()
        self.assertNotIn("captured", self.order)


PI_IDLE = ("llama-server -m /m/gemma-4-E4B.gguf -t 3 -c 4096 --host 127.0.0.1 "
           "--port 8080 -rea off --reasoning-budget -1")


class TestPiDeployedServer(TestFingerprintTiming):
    """The Pi's va-llm serves all the time, so a server is up before the run
    touches anything. Only a server the run itself started is evidence."""

    def make_pi(self, seen, before=(812,)):
        """seen: (pid, argv) on each successive poll."""
        seq = list(seen)
        r = self.make([""])

        def capture_fn():
            self.order.append("captured")
            pid, args = seq.pop(0) if len(seq) > 1 else seq[0]
            return {"server_args": args, "pids": [pid], "model_path": "",
                    "flags": fingerprint.parse_flags(args)}
        r.capture_fn = capture_fn
        r.pids_fn = lambda: list(before)
        return r

    def test_the_idle_deployed_server_is_not_mistaken_for_the_runs(self):
        # The regression: the first poll saw the idle -c 4096 server, read
        # it as the run's, and blocked every Pi job for drift.
        job = self.queue_one()
        self.make_pi([(812, PI_IDLE), (812, PI_IDLE), (905, GOOD_ARGS)]).tick()
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "completed", got["note"])

    def test_the_restarted_server_is_still_diffed(self):
        job = self.queue_one()
        self.make_pi([(812, PI_IDLE), (905, BAD_ARGS)]).tick()
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "blocked")
        self.assertTrue(self.procs[0].killed)

    def test_a_run_that_never_restarts_the_server_is_blocked_not_passed(self):
        job = self.queue_one()
        self.make_pi([(812, PI_IDLE)]).tick()
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "blocked")
        self.assertIn("never replaced", got["note"])


class ScriptedProbe(FakeProbe):
    """Answers change per call: mem and busy are consumed as lists."""

    def __init__(self, mems=(9000,), busy=((),)):
        self.mems, self.busys = list(mems), [list(b) for b in busy]

    def mem_available_mb(self):
        return self.mems.pop(0) if len(self.mems) > 1 else self.mems[0]

    def busy_processes(self):
        return self.busys.pop(0) if len(self.busys) > 1 else self.busys[0]


class TestQueueBehaviour(TestFingerprintTiming):
    def runner(self, probe, captures=(GOOD_ARGS,), done=True):
        r = self.make(list(captures), done=done)
        r.probe = probe
        return r

    def test_a_run_outside_the_queue_makes_the_job_wait_not_block(self):
        job = self.queue_one()
        r = self.runner(ScriptedProbe(busy=[["lm_eval"]]))
        self.assertFalse(r.tick())
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "queued")
        self.assertIn("outside the queue", got["note"])
        self.assertNotIn("started", self.order)

    def test_the_job_starts_once_the_board_frees_up(self):
        job = self.queue_one()
        r = self.runner(ScriptedProbe(busy=[["lm_eval"], [], []]))
        r.tick()
        r.tick()
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "completed", got["note"])
        self.assertIsNone(got["note"])

    def test_memory_that_recovers_within_the_retry_window_is_not_a_refusal(self):
        job = self.queue_one(model="e4b")
        r = self.runner(ScriptedProbe(mems=[4000, 4200, 6000]))
        r.tick()
        self.assertEqual(store.get(self.p, job["id"])["state"], "completed")

    def test_memory_that_stays_short_blocks(self):
        job = self.queue_one(model="e4b")
        r = self.runner(ScriptedProbe(mems=[4000]))
        r.tick()
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "blocked")
        self.assertIn("4000 MB", got["note"])

    def test_a_recorded_memory_override_runs_and_says_so(self):
        job = self.queue_one(model="e4b")
        store.update(self.p, job["id"], override_prechecks={
            "checks": ["memory"], "reason": "peak measured at 5,008 MB", "by": "t"})
        r = self.runner(ScriptedProbe(mems=[4000]))
        r.tick()
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "completed")
        self.assertIn("precheck overridden", got["note"])
        names = [e["event"] for e in events.read(self.p, job["id"])[0]]
        self.assertIn("precheck_overridden", names)

    def test_an_override_does_not_cover_other_checks(self):
        job = self.queue_one(model="e4b")
        os.makedirs(os.path.join(self.p.stdbench, "mmlupro100-e4b-s2"))
        store.update(self.p, job["id"], override_prechecks={
            "checks": ["memory"], "reason": "peak measured at 5,008 MB"})
        r = self.runner(ScriptedProbe(mems=[4000]))
        r.tick()
        self.assertEqual(store.get(self.p, job["id"])["state"], "blocked")

    def test_the_pid_is_recorded_so_a_restart_can_find_the_run(self):
        job = self.queue_one()
        self.runner(ScriptedProbe()).tick()
        self.assertEqual(store.get(self.p, job["id"])["pid"], 4242)


class TestRecovery(TestFingerprintTiming):
    def active_job(self, done):
        job = self.queue_one()
        store.update(self.p, job["id"], state="running", pid=777)
        if done:
            out = os.path.join(self.p.stdbench, "mmlupro100-e4b-s2")
            os.makedirs(out, exist_ok=True)
            open(os.path.join(out, ".done"), "w").close()
        return job

    def test_a_run_still_going_is_adopted_and_judged_when_it_ends(self):
        job = self.active_job(done=True)
        polls = iter([True, True, False])
        r = self.make([""])
        r.recover(alive=lambda pid: next(polls, False), find=lambda j: None)
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "completed")
        names = [e["event"] for e in events.read(self.p, job["id"])[0]]
        self.assertIn("adopted", names)

    def test_a_run_that_vanished_is_failed_not_left_stuck(self):
        # The regression: the queue stayed "running" forever after a restart.
        job = self.active_job(done=False)
        r = self.make([""])
        r.recover(alive=lambda pid: False, find=lambda j: None)
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "failed")
        self.assertIn("daemon restarted", got["note"])

    def test_a_run_that_finished_while_the_daemon_was_down_is_completed(self):
        job = self.active_job(done=True)
        self.make([""]).recover(alive=lambda pid: False, find=lambda j: None)
        self.assertEqual(store.get(self.p, job["id"])["state"], "completed")

    def test_nothing_active_is_a_no_op(self):
        self.assertIsNone(self.make([""]).recover())


if __name__ == "__main__":
    unittest.main()
