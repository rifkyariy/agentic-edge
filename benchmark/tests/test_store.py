import json
import os
import tempfile
import unittest

from jobqueue import paths, store


def mkjob(label="mmlupro-e4b-s2", **kw):
    base = dict(kind="mmlupro",
                params={"model": "e4b", "subset": "s2", "thinking": "off"},
                label=label, output_dir="mmlupro100-e4b-s2",
                command="./run_measured.sh " + label, env={})
    base.update(kw)
    return store.new_job(**base)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = paths.Paths(self.tmp.name, "jetson")

    def test_add_assigns_id_and_persists(self):
        job = store.add(self.p, mkjob())
        self.assertTrue(job["id"])
        self.assertEqual(job["state"], "queued")
        again = store.get(self.p, job["id"])
        self.assertEqual(again["label"], "mmlupro-e4b-s2")

    def test_ids_are_unique_across_rapid_adds(self):
        ids = {store.add(self.p, mkjob())["id"] for _ in range(50)}
        self.assertEqual(len(ids), 50)

    def test_queue_file_is_valid_json_after_many_writes(self):
        for _ in range(10):
            store.add(self.p, mkjob())
        with open(self.p.queue_file) as f:
            data = json.load(f)
        self.assertEqual(len(data["jobs"]), 10)
        self.assertEqual(data["version"], 1)

    def test_update_changes_only_named_fields(self):
        job = store.add(self.p, mkjob())
        store.update(self.p, job["id"], state="running", started=123.0)
        got = store.get(self.p, job["id"])
        self.assertEqual(got["state"], "running")
        self.assertEqual(got["started"], 123.0)
        self.assertEqual(got["label"], "mmlupro-e4b-s2")

    def test_update_rejects_unknown_state(self):
        job = store.add(self.p, mkjob())
        with self.assertRaises(ValueError):
            store.update(self.p, job["id"], state="wandering")

    def test_cancel_only_affects_queued_jobs(self):
        job = store.add(self.p, mkjob())
        store.cancel(self.p, job["id"])
        self.assertEqual(store.get(self.p, job["id"])["state"], "cancelled")

    def test_cancel_of_running_job_raises(self):
        job = store.add(self.p, mkjob())
        store.update(self.p, job["id"], state="running")
        with self.assertRaises(store.NotCancellable):
            store.cancel(self.p, job["id"])

    def test_next_eligible_is_fifo(self):
        first = store.add(self.p, mkjob(label="first"))
        store.add(self.p, mkjob(label="second"))
        self.assertEqual(store.next_eligible(self.p, now=0)["id"], first["id"])

    def test_next_eligible_skips_jobs_not_yet_due(self):
        store.add(self.p, mkjob(label="later", not_before_epoch=5000))
        due = store.add(self.p, mkjob(label="now"))
        self.assertEqual(store.next_eligible(self.p, now=100)["id"], due["id"])
        self.assertEqual(store.next_eligible(self.p, now=6000)["label"], "later")

    def test_next_eligible_returns_none_while_a_job_is_active(self):
        running = store.add(self.p, mkjob(label="running"))
        store.update(self.p, running["id"], state="running")
        store.add(self.p, mkjob(label="waiting"))
        # One job per device (AGENTS §9) is a property of the store, not a rule
        # the caller has to remember.
        self.assertIsNone(store.next_eligible(self.p, now=0))

    def test_active_reports_the_running_job(self):
        job = store.add(self.p, mkjob())
        self.assertIsNone(store.active(self.p))
        store.update(self.p, job["id"], state="fingerprinting")
        self.assertEqual(store.active(self.p)["id"], job["id"])

    def test_load_on_missing_file_returns_empty_queue(self):
        self.assertEqual(store.load(self.p), {"version": 1, "jobs": []})

    def test_write_is_atomic_leaving_no_partial_file(self):
        store.add(self.p, mkjob())
        leftovers = [f for f in os.listdir(self.p.queue_dir) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
