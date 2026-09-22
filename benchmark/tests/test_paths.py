import os
import unittest

from jobqueue import paths


class TestPaths(unittest.TestCase):
    def test_derived_paths_hang_off_root(self):
        p = paths.Paths("/home/ari/research", "jetson")
        self.assertEqual(p.queue_dir, "/home/ari/research/queue")
        self.assertEqual(p.queue_file, "/home/ari/research/queue/queue.json")
        self.assertEqual(p.lock_file, "/home/ari/research/queue/queue.lock")
        self.assertEqual(p.events_file, "/home/ari/research/queue/events.jsonl")
        self.assertEqual(p.pid_file, "/home/ari/research/queue/runner.pid")
        self.assertEqual(p.jobs_dir, "/home/ari/research/queue/jobs")
        self.assertEqual(p.job_dir("j1"), "/home/ari/research/queue/jobs/j1")
        self.assertEqual(p.stdbench, "/home/ari/research/stdbench")
        self.assertEqual(p.measured, "/home/ari/research/measured")

    def test_detect_prefers_capital_research_as_pi(self):
        # The Pi keeps its tree in ~/Research, the Jetson in ~/research.
        home = "/home/mitlab"
        exists = {"/home/mitlab/Research"}
        p = paths.detect(home=home, env={}, isdir=exists.__contains__)
        self.assertEqual(p.board, "pi")
        self.assertEqual(p.root, "/home/mitlab/Research")

    def test_detect_lowercase_research_is_jetson(self):
        home = "/home/ari"
        exists = {"/home/ari/research"}
        p = paths.detect(home=home, env={}, isdir=exists.__contains__)
        self.assertEqual(p.board, "jetson")
        self.assertEqual(p.root, "/home/ari/research")

    def test_env_overrides_detection(self):
        # Tests run on a Mac with neither directory; the override is how the
        # suite and `--dry-run` work off-board.
        env = {"AGENTIC_QUEUE_ROOT": "/tmp/fake", "AGENTIC_BOARD": "jetson"}
        p = paths.detect(home="/home/nobody", env=env, isdir=lambda _: False)
        self.assertEqual(p.root, "/tmp/fake")
        self.assertEqual(p.board, "jetson")

    def test_detect_raises_when_no_root_found(self):
        with self.assertRaises(paths.BoardUnknown):
            paths.detect(home="/home/nobody", env={}, isdir=lambda _: False)

    def test_bench_dir_contains_the_run_scripts(self):
        self.assertTrue(os.path.isfile(os.path.join(paths.bench_dir(), "run_measured.sh")))


if __name__ == "__main__":
    unittest.main()
