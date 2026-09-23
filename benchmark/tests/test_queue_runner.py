import os
import shutil
import tempfile
import unittest

import queue_runner
from jobqueue import paths


class TestCodeStamp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = os.path.join(self.tmp.name, "benchmark")
        shutil.copytree(paths.bench_dir(), self.bench,
                        ignore=shutil.ignore_patterns("tests", "__pycache__"))

    def test_an_edit_changes_the_stamp_even_with_an_older_mtime(self):
        before = queue_runner.code_stamp(self.bench)
        f = os.path.join(self.bench, "jobqueue", "store.py")
        old = os.path.getmtime(f)
        with open(f, "a") as fh:
            fh.write("\n# deployed\n")
        os.utime(f, (old - 3600, old - 3600))       # rsync -a keeps old mtimes
        self.assertNotEqual(queue_runner.code_stamp(self.bench), before)

    def test_files_a_run_uses_do_not_trigger_a_reload(self):
        before = queue_runner.code_stamp(self.bench)
        with open(os.path.join(self.bench, "std_mmlupro.sh"), "a") as fh:
            fh.write("\n# edit\n")
        self.assertEqual(queue_runner.code_stamp(self.bench), before)


if __name__ == "__main__":
    unittest.main()
