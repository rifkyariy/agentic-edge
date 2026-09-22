import json
import os
import subprocess
import sys
import tempfile
import unittest

from jobqueue import paths

CTL = os.path.join(paths.bench_dir(), "queue_ctl.py")


class TestQueueCtl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "stdbench"))
        with open(os.path.join(self.root, "stdbench",
                               "mmlupro_subset100_s2_samples.json"), "w") as f:
            json.dump([1], f)

    def ctl(self, *args):
        env = dict(os.environ,
                   AGENTIC_QUEUE_ROOT=self.root, AGENTIC_BOARD="jetson")
        proc = subprocess.run([sys.executable, CTL] + list(args),
                              capture_output=True, text=True, env=env,
                              cwd=paths.bench_dir())
        return proc.returncode, json.loads(proc.stdout or "{}")

    def test_describe_lists_the_kinds_and_the_board(self):
        rc, out = self.ctl("--describe")
        self.assertEqual(rc, 0)
        self.assertEqual(out["board"], "jetson")
        self.assertIn("mmlupro", out["kinds"])
        self.assertIn("mmlupro-baseline", out["baselines"])
        self.assertTrue(out["timezone"])

    def test_preflight_reports_checks_without_queueing_anything(self):
        rc, out = self.ctl("--preflight",
                           '{"kind":"mmlupro","params":{"model":"e4b","subset":"s2"}}')
        self.assertEqual(rc, 0)
        self.assertEqual(out["resolved"]["label"], "mmlupro-e4b-s2")
        self.assertIn("memory", [c["name"] for c in out["prechecks"]])
        _, status = self.ctl("--status")
        self.assertEqual(status["jobs"], [])

    def test_add_queues_a_job(self):
        rc, out = self.ctl("--add",
                           '{"kind":"mmlupro","params":{"model":"e4b","subset":"s2"}}')
        self.assertEqual(rc, 0)
        self.assertEqual(out["job"]["state"], "queued")
        _, status = self.ctl("--status")
        self.assertEqual(len(status["jobs"]), 1)

    def test_add_rejects_a_bad_parameter_with_a_readable_error(self):
        rc, out = self.ctl("--add",
                           '{"kind":"mmlupro","params":{"model":"e9b","subset":"s2"}}')
        self.assertEqual(rc, 1)
        self.assertIn("e9b", out["error"])

    def test_add_rejects_malformed_json(self):
        rc, out = self.ctl("--add", "{not json")
        self.assertEqual(rc, 1)
        self.assertIn("error", out)

    def test_not_before_is_converted_to_an_absolute_epoch(self):
        rc, out = self.ctl("--add",
                           '{"kind":"mmlupro","params":{"model":"e4b","subset":"s2"},'
                           '"not_before":"02:00"}')
        self.assertEqual(rc, 0)
        self.assertIsNotNone(out["job"]["not_before_epoch"])

    def test_not_before_rejects_a_bad_time(self):
        rc, out = self.ctl("--add",
                           '{"kind":"mmlupro","params":{"model":"e4b","subset":"s2"},'
                           '"not_before":"half past nine"}')
        self.assertEqual(rc, 1)

    def test_cancel_marks_a_queued_job_cancelled(self):
        _, added = self.ctl("--add",
                            '{"kind":"mmlupro","params":{"model":"e4b","subset":"s2"}}')
        rc, out = self.ctl("--cancel", added["job"]["id"])
        self.assertEqual(rc, 0)
        self.assertEqual(out["job"]["state"], "cancelled")

    def test_cancel_of_unknown_job_errors(self):
        rc, out = self.ctl("--cancel", "nope")
        self.assertEqual(rc, 1)
        self.assertIn("error", out)

    def test_status_reports_the_daemon_as_not_running(self):
        rc, out = self.ctl("--status")
        self.assertEqual(rc, 0)
        self.assertFalse(out["daemon_alive"])

    def test_log_read_is_offset_based(self):
        _, added = self.ctl("--add",
                            '{"kind":"mmlupro","params":{"model":"e4b","subset":"s2"}}')
        jid = added["job"]["id"]
        log = os.path.join(self.root, "queue", "jobs", jid, "command.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "w") as f:
            f.write("first\n")
        rc, out = self.ctl("--log", jid, "--stream", "command")
        self.assertEqual(out["text"], "first\n")
        with open(log, "a") as f:
            f.write("second\n")
        rc, out2 = self.ctl("--log", jid, "--stream", "command",
                            "--from", str(out["offset"]))
        self.assertEqual(out2["text"], "second\n")

    def test_status_includes_fingerprint_and_prechecks_when_present(self):
        _, added = self.ctl("--add",
                            '{"kind":"mmlupro","params":{"model":"e4b","subset":"s2"}}')
        jid = added["job"]["id"]
        d = os.path.join(self.root, "queue", "jobs", jid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "fingerprint.json"), "w") as f:
            json.dump({"agrees": False, "baseline": "mmlupro-baseline",
                       "diff": [{"key": "reasoning", "ok": False,
                                 "expected": "off", "actual": None}]}, f)
        _, status = self.ctl("--status")
        job = status["jobs"][0]
        self.assertFalse(job["fingerprint"]["agrees"])

    def test_status_reports_null_fingerprint_before_a_job_runs(self):
        self.ctl("--add", '{"kind":"mmlupro","params":{"model":"e4b","subset":"s2"}}')
        _, status = self.ctl("--status")
        self.assertIsNone(status["jobs"][0]["fingerprint"])

    def test_log_rejects_an_unknown_stream_name(self):
        rc, out = self.ctl("--log", "whatever", "--stream", "../../etc/passwd")
        self.assertEqual(rc, 1)
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
