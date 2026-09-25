import subprocess
import unittest
from unittest import mock

import telemetry


def fake_pgrep(running):
    """subprocess.run stand-in: pgrep -n -x <name> finds only `running`."""
    def run(argv, **_):
        name = argv[-1]
        if name in running:
            return subprocess.CompletedProcess(argv, 0, stdout="%d\n" % running[name])
        return subprocess.CompletedProcess(argv, 1, stdout="")
    return run


class TestPidOf(unittest.TestCase):
    def test_the_default_follows_either_engine(self):
        # S3: a little-gemma run left proc_rss_mb and proc_cpu_pct empty,
        # because only llama-server was ever looked for.
        with mock.patch.object(telemetry.subprocess, "run",
                               fake_pgrep({"run-cuda-i8": 4242})):
            self.assertEqual(telemetry.pid_of(telemetry.DEFAULT_PROC), 4242)
        with mock.patch.object(telemetry.subprocess, "run",
                               fake_pgrep({"llama-server": 17})):
            self.assertEqual(telemetry.pid_of(telemetry.DEFAULT_PROC), 17)

    def test_nothing_running_is_none(self):
        with mock.patch.object(telemetry.subprocess, "run", fake_pgrep({})):
            self.assertIsNone(telemetry.pid_of(telemetry.DEFAULT_PROC))

    def test_a_single_name_still_works(self):
        with mock.patch.object(telemetry.subprocess, "run",
                               fake_pgrep({"llama-server": 17, "run-cuda-i8": 9})):
            self.assertEqual(telemetry.pid_of("llama-server"), 17)
