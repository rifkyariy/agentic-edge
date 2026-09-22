import tempfile
import unittest

from jobqueue import events, paths


class TestEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = paths.Paths(self.tmp.name, "jetson")

    def test_emit_records_event_name_job_and_time(self):
        rec = events.emit(self.p, "j1", "queued", by="dashboard")
        self.assertEqual(rec["event"], "queued")
        self.assertEqual(rec["job"], "j1")
        self.assertEqual(rec["by"], "dashboard")
        self.assertIsInstance(rec["ts"], float)

    def test_read_returns_events_in_order(self):
        events.emit(self.p, "j1", "queued")
        events.emit(self.p, "j1", "started")
        got, _ = events.read(self.p)
        self.assertEqual([e["event"] for e in got], ["queued", "started"])

    def test_read_from_offset_returns_only_new_events(self):
        events.emit(self.p, "j1", "queued")
        first, offset = events.read(self.p)
        events.emit(self.p, "j1", "started")
        rest, new_offset = events.read(self.p, offset=offset)
        self.assertEqual([e["event"] for e in rest], ["started"])
        self.assertGreater(new_offset, offset)

    def test_per_job_log_holds_only_that_job(self):
        events.emit(self.p, "j1", "queued")
        events.emit(self.p, "j2", "queued")
        got, _ = events.read(self.p, job_id="j1")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["job"], "j1")

    def test_read_of_missing_log_is_empty_not_an_error(self):
        got, offset = events.read(self.p, job_id="never-existed")
        self.assertEqual(got, [])
        self.assertEqual(offset, 0)

    def test_a_corrupt_line_is_skipped_not_fatal(self):
        events.emit(self.p, "j1", "queued")
        with open(self.p.events_file, "a") as f:
            f.write("{ this is not json\n")
        events.emit(self.p, "j1", "started")
        got, _ = events.read(self.p)
        self.assertEqual([e["event"] for e in got], ["queued", "started"])


if __name__ == "__main__":
    unittest.main()
