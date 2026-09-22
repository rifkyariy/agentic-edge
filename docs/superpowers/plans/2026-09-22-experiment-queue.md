# Experiment Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give both boards a device-side job queue with prechecks, serving-flag
fingerprinting and structured logging, and a dashboard UI that drives it.

**Architecture:** A stdlib-only Python daemon (`queue_runner.py`) on each board
owns a queue file and runs one job at a time, capturing the resolved
`llama-server` command line after the server is up and refusing to start when it
drifts from a declared baseline. A single device-side CLI (`queue_ctl.py`) is the
only thing the dashboard invokes over ssh; the Next.js app is a client.

**Tech Stack:** Python 3.12+ stdlib only on the devices (no pip — AGENTS §7);
`unittest` for tests; systemd user units for supervision; Next.js 15 / React 19
in `dashboard/`.

**Spec:** [`docs/superpowers/specs/2026-09-22-experiment-queue-design.md`](../specs/2026-09-22-experiment-queue-design.md)

## Global Constraints

- **Stdlib only on the devices.** No pip, no third-party imports in
  `benchmark/`. The Jetson has no passwordless sudo and its venvs are
  bootstrapped by hand (AGENTS §7).
- **Package name is `jobqueue`, never `queue`.** `queue` is a stdlib module;
  a package of that name in `benchmark/` would shadow it for everything run
  from that directory, including `concurrent.futures`.
- **Tests are `unittest`, run from `benchmark/`:**
  `cd benchmark && python3 -m unittest discover -s tests -v`. Neither the Mac's
  system `python3` nor the Pi has pytest.
- **No test may execute a real benchmark.** Every runner test injects a fake
  exec function.
- **Path case differs per board:** `~/Research` on the Pi, `~/research` on the
  Jetson. Detect, never hardcode (AGENTS §2).
- **Completion is the `.done` marker, never exit status.**
  `std_mmlupro_jetson.sh` ends on `echo finished` and always returns 0.
- **Baseline serving flags** (AGENTS §5, verified 2026-09-22):
  `-rea off --reasoning-budget -1 -c 8192 --cache-ram 0`. `-rea` is
  `--reasoning`, the thinking switch. `--reasoning-format` is separate and must
  be pinned to `none` whenever thinking is on.
- **Never `scp` over a script a board is currently running** (AGENTS §4.1).
  Deploy with `git pull` — both boards are clones of `origin/main` on `main`.
- **Python versions:** 3.13.5 (Pi), 3.12.3 (Jetson), 3.14.6 (Mac). Target 3.12.

## File Structure

```
benchmark/
  jobqueue/__init__.py        (empty)
  jobqueue/paths.py           root + board detection, every derived path
  jobqueue/store.py           queue.json: flock, atomic write, state transitions
  jobqueue/events.py          events.jsonl append + offset-based read
  jobqueue/kinds.py           job_kinds.json: validate params, resolve command
  jobqueue/prechecks.py       memory, stale dir, subset ids, board idle
  jobqueue/fingerprint.py     capture resolved argv, diff vs baselines.json
  jobqueue/runner.py          the state machine
  job_kinds.json              the registry (data)
  baselines.json              expected serving flags per condition (data)
  queue_runner.py             daemon entry point (thin)
  queue_ctl.py                CLI the dashboard drives over ssh (thin)
  systemd/agentic-queue.service
  install_queue.sh            installs + enables the user unit
  run_measured.sh             MODIFY: second server_args capture
  tests/__init__.py
  tests/test_paths.py  test_store.py  test_events.py  test_kinds.py
  tests/test_prechecks.py  test_fingerprint.py  test_runner.py  test_queue_ctl.py

dashboard/
  app/api/queue/route.js      GET status / POST add / DELETE cancel
  app/api/logs/route.js       offset-based log reads
  app/queue/page.js           config form, preflight panel, queue list
  app/JobDetail.js            event timeline, fingerprint diff, log tabs
  app/lib/hosts.js            MODIFY: ssh multiplexing (Task 0)
  app/lib/plan.js             MODIFY: authoritative state, `-think` runs
  app/api/status/route.js     MODIFY: SSE stream (Task 0)
  scripts/check-ssh.mjs       MODIFY: daemon liveness check
```

**Phase boundary:** Tasks 1–10 deliver a working queue usable entirely from the
CLI over ssh. That is a shippable milestone; Tasks 11–15 add the UI. If you stop
after Task 10 you have working software.

---

## Task 0: Dashboard efficiency fixes (independent, land first)

From the spec's scope section — a separate, smaller track that the queue page
later benefits from. Measured today: a poll costs 0.67s (Pi) / 0.96s (Jetson),
of which ~0.2s / ~0.5s is pure SSH handshake.

**Files:**
- Modify: `dashboard/app/lib/hosts.js:38` (the `SSH` constant)

**Interfaces:**
- Consumes: nothing
- Produces: `SSH` — the shared ssh flag string, now with multiplexing. Tasks 11
  and 15 reuse it unchanged.

- [ ] **Step 1: Add ControlMaster multiplexing to the shared ssh flags**

Replace the `SSH` constant in `dashboard/app/lib/hosts.js`:

```js
// Shared ssh flags: never prompt (the web app has no tty), give up quickly.
// ControlMaster reuses one connection per board across calls — the dashboard
// polls every 5s, which is ~11,500 handshakes over an 8h run, each forking an
// sshd and a python on a board AGENTS §5 requires to be otherwise quiet.
// ControlPath lives in /tmp so a stale socket dies with the machine.
export const SSH = "-o BatchMode=yes -o ConnectTimeout=6 -o StrictHostKeyChecking=accept-new"
  + " -o ControlMaster=auto -o ControlPersist=300"
  + " -o ControlPath=/tmp/agentic-edge-cm-%r@%h:%p";
```

- [ ] **Step 2: Verify the master socket is created and reused**

```bash
cd dashboard && npm run dev
# in another shell, after the page has polled once:
ls /tmp/agentic-edge-cm-*
```

Expected: two socket files, one per board.

- [ ] **Step 3: Measure the improvement**

```bash
time ssh -o BatchMode=yes -o ConnectTimeout=6 -o ControlMaster=auto \
  -o ControlPersist=300 -o ControlPath=/tmp/agentic-edge-cm-%r@%h:%p \
  MITLAB-JETSON 'python3 ~/research/agentic-edge/benchmark/probe_status.py > /dev/null'
```

Expected: ~0.45s, against ~0.96s without multiplexing.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app/lib/hosts.js
git commit -m "Reuse one ssh connection per board instead of 11,500"
```

---

## Task 1: Path and board detection

**Files:**
- Create: `benchmark/jobqueue/__init__.py` (empty)
- Create: `benchmark/jobqueue/paths.py`
- Create: `benchmark/tests/__init__.py` (empty)
- Test: `benchmark/tests/test_paths.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `class Paths` with `__init__(self, root, board)` and read-only properties
    `root`, `board`, `queue_dir`, `jobs_dir`, `stdbench`, `measured`,
    `lock_file`, `queue_file`, `events_file`, `pid_file`, and method
    `job_dir(job_id) -> str`
  - `detect(home=None, env=None) -> Paths`
  - `bench_dir() -> str` — absolute path of `benchmark/`, where the run scripts live

- [ ] **Step 1: Write the failing test**

Create `benchmark/tests/test_paths.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd benchmark && python3 -m unittest tests.test_paths -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobqueue'`

- [ ] **Step 3: Write minimal implementation**

Create `benchmark/jobqueue/__init__.py` (empty file) and
`benchmark/tests/__init__.py` (empty file), then `benchmark/jobqueue/paths.py`:

```python
"""Where the queue keeps its state, and which board we are on.

The Pi keeps its results tree in ~/Research, the Jetson in ~/research. That
case difference has caused board-specific bugs before (AGENTS §7), so it is
detected once here and nowhere else.

AGENTIC_QUEUE_ROOT and AGENTIC_BOARD override detection. The test suite runs
on a Mac that has neither directory, and `queue_ctl.py --dry-run` uses them
to resolve commands off-board.
"""
import os


class BoardUnknown(Exception):
    """Neither ~/Research nor ~/research exists and no override was given."""


class Paths:
    def __init__(self, root, board):
        self.root = root
        self.board = board

    @property
    def queue_dir(self):
        return os.path.join(self.root, "queue")

    @property
    def queue_file(self):
        return os.path.join(self.queue_dir, "queue.json")

    @property
    def lock_file(self):
        # Separate from queue.json: atomic writes replace the inode, so a lock
        # held on the data file itself would be released by its own update.
        return os.path.join(self.queue_dir, "queue.lock")

    @property
    def events_file(self):
        return os.path.join(self.queue_dir, "events.jsonl")

    @property
    def pid_file(self):
        return os.path.join(self.queue_dir, "runner.pid")

    @property
    def jobs_dir(self):
        return os.path.join(self.queue_dir, "jobs")

    def job_dir(self, job_id):
        return os.path.join(self.jobs_dir, job_id)

    @property
    def stdbench(self):
        return os.path.join(self.root, "stdbench")

    @property
    def measured(self):
        return os.path.join(self.root, "measured")


def detect(home=None, env=None, isdir=None):
    env = os.environ if env is None else env
    home = os.path.expanduser("~") if home is None else home
    isdir = os.path.isdir if isdir is None else isdir

    root = env.get("AGENTIC_QUEUE_ROOT")
    board = env.get("AGENTIC_BOARD")
    if root and board:
        return Paths(root, board)

    for candidate, name in ((os.path.join(home, "Research"), "pi"),
                            (os.path.join(home, "research"), "jetson")):
        if isdir(candidate):
            return Paths(root or candidate, board or name)
    raise BoardUnknown(
        "no ~/Research or ~/research here; set AGENTIC_QUEUE_ROOT and AGENTIC_BOARD")


def bench_dir():
    """The benchmark/ directory — where run_measured.sh and the run scripts live."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd benchmark && python3 -m unittest tests.test_paths -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add benchmark/jobqueue/ benchmark/tests/
git commit -m "Detect the board's results root in one place"
```

---

## Task 2: The queue store

**Files:**
- Create: `benchmark/jobqueue/store.py`
- Test: `benchmark/tests/test_store.py`

**Interfaces:**
- Consumes: `jobqueue.paths.Paths` (Task 1)
- Produces:
  - `STATES` — tuple of the eight valid state names
  - `new_job(kind, params, label, output_dir, command, env, not_before_epoch=None) -> dict`
  - `add(paths, job) -> dict` — assigns `id`, persists, returns the stored job
  - `load(paths) -> dict` — `{"version": 1, "jobs": [...]}`
  - `get(paths, job_id) -> dict | None`
  - `update(paths, job_id, **fields) -> dict`
  - `cancel(paths, job_id) -> dict`
  - `next_eligible(paths, now) -> dict | None`
  - `active(paths) -> dict | None` — the job in a non-terminal running state

- [ ] **Step 1: Write the failing test**

Create `benchmark/tests/test_store.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd benchmark && python3 -m unittest tests.test_store -v`
Expected: FAIL — `ImportError: cannot import name 'store'`

- [ ] **Step 3: Write minimal implementation**

Create `benchmark/jobqueue/store.py`:

```python
"""The job list, and the rules about what may follow what.

queue.json is rewritten whole under an flock, via a temp file and os.replace,
so a power cut leaves either the old file or the new one and never a torn one.
"""
import fcntl
import json
import os
import time
import uuid

STATES = ("queued", "prechecking", "fingerprinting", "running",
          "completed", "failed", "blocked", "cancelled")

# States in which the board is busy. next_eligible() returns nothing while any
# job is in one of these: one job per device (AGENTS §9).
ACTIVE = ("prechecking", "fingerprinting", "running")

_EMPTY = {"version": 1, "jobs": []}


class NotCancellable(Exception):
    """Cancel was asked for a job that has already left the queue."""


class UnknownJob(Exception):
    pass


def new_job(kind, params, label, output_dir, command, env, not_before_epoch=None):
    return {
        "id": None,
        "kind": kind,
        "params": params,
        "label": label,
        "output_dir": output_dir,
        "command": command,
        "env": env,
        "not_before_epoch": not_before_epoch,
        "state": "queued",
        "created": time.time(),
        "started": None,
        "finished": None,
        "exit_code": None,
        "override_fingerprint": False,
        "note": None,
    }


class _Lock:
    """flock on a file beside queue.json, held for the whole read-modify-write."""

    def __init__(self, path):
        self.path = path
        self.fd = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)
        self.fd = None


def _read(paths):
    try:
        with open(paths.queue_file) as f:
            return json.load(f)
    except (OSError, ValueError):
        return dict(_EMPTY, jobs=[])


def _write(paths, data):
    os.makedirs(paths.queue_dir, exist_ok=True)
    tmp = paths.queue_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, paths.queue_file)


def load(paths):
    return _read(paths)


def get(paths, job_id):
    for j in _read(paths)["jobs"]:
        if j["id"] == job_id:
            return j
    return None


def add(paths, job):
    with _Lock(paths.lock_file):
        data = _read(paths)
        job = dict(job)
        job["id"] = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        data["jobs"].append(job)
        _write(paths, data)
    os.makedirs(paths.job_dir(job["id"]), exist_ok=True)
    return job


def update(paths, job_id, **fields):
    if "state" in fields and fields["state"] not in STATES:
        raise ValueError("unknown state: %r" % (fields["state"],))
    with _Lock(paths.lock_file):
        data = _read(paths)
        for j in data["jobs"]:
            if j["id"] == job_id:
                j.update(fields)
                _write(paths, data)
                return j
        raise UnknownJob(job_id)


def cancel(paths, job_id):
    job = get(paths, job_id)
    if job is None:
        raise UnknownJob(job_id)
    if job["state"] != "queued":
        raise NotCancellable(
            "job %s is %s; only queued jobs can be cancelled" % (job_id, job["state"]))
    return update(paths, job_id, state="cancelled", finished=time.time())


def active(paths):
    for j in _read(paths)["jobs"]:
        if j["state"] in ACTIVE:
            return j
    return None


def next_eligible(paths, now):
    data = _read(paths)
    for j in data["jobs"]:
        if j["state"] in ACTIVE:
            return None
    for j in data["jobs"]:
        if j["state"] != "queued":
            continue
        if j["not_before_epoch"] and now < j["not_before_epoch"]:
            continue
        return j
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd benchmark && python3 -m unittest tests.test_store -v`
Expected: PASS, 13 tests

- [ ] **Step 5: Commit**

```bash
git add benchmark/jobqueue/store.py benchmark/tests/test_store.py
git commit -m "Make one-job-per-device a property of the queue, not a rule"
```

---

## Task 3: The event log

**Files:**
- Create: `benchmark/jobqueue/events.py`
- Test: `benchmark/tests/test_events.py`

**Interfaces:**
- Consumes: `jobqueue.paths.Paths` (Task 1)
- Produces:
  - `emit(paths, job_id, event, **fields) -> dict` — appends one JSON line to
    both `queue/events.jsonl` and `queue/jobs/<id>/events.jsonl`
  - `read(paths, job_id=None, offset=0) -> (list_of_dicts, new_offset)`

- [ ] **Step 1: Write the failing test**

Create `benchmark/tests/test_events.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd benchmark && python3 -m unittest tests.test_events -v`
Expected: FAIL — `ImportError: cannot import name 'events'`

- [ ] **Step 3: Write minimal implementation**

Create `benchmark/jobqueue/events.py`:

```python
"""Append-only job history.

Two copies of every line: one board-wide log the dashboard tails, and one per
job so reading a single job's history does not mean scanning the whole file.
Reads are byte-offset based so tailing a three-hour run does not re-send it.
"""
import json
import os
import time


def _append(path, line):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(line + "\n")


def emit(paths, job_id, event, **fields):
    rec = {"ts": time.time(), "job": job_id, "event": event}
    rec.update(fields)
    line = json.dumps(rec, sort_keys=True)
    _append(paths.events_file, line)
    _append(os.path.join(paths.job_dir(job_id), "events.jsonl"), line)
    return rec


def read(paths, job_id=None, offset=0):
    path = (paths.events_file if job_id is None
            else os.path.join(paths.job_dir(job_id), "events.jsonl"))
    try:
        with open(path) as f:
            f.seek(offset)
            body = f.read()
            new_offset = f.tell()
    except OSError:
        return [], offset

    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            # A torn final line from a concurrent append. Skipping is right:
            # the next read picks it up whole.
            continue
    return out, new_offset
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd benchmark && python3 -m unittest tests.test_events -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add benchmark/jobqueue/events.py benchmark/tests/test_events.py
git commit -m "Record what happened to each job, readable by offset"
```

---

## Task 4: The job-kind registry

**Files:**
- Create: `benchmark/job_kinds.json`
- Create: `benchmark/jobqueue/kinds.py`
- Test: `benchmark/tests/test_kinds.py`

**Interfaces:**
- Consumes: `jobqueue.paths.Paths` (Task 1)
- Produces:
  - `ValidationError` — raised for an unknown kind or bad parameter
  - `load(path=None) -> dict` — the parsed registry
  - `validate(registry, kind, params) -> dict` — normalised params
  - `pick(mapping, params)`, `pick_memory(spec, params)`,
    `pick_baseline(spec, params)` — the small lookups Tasks 5 and 7 reuse
  - `resolve(registry, kind, params, paths) -> dict` with keys
    `label`, `output_dir`, `command`, `env` (dict), `baseline` (str or None),
    `memory_mb` (int or None), `params` (the normalised parameters)

**Why label and output_dir are separate templates:** `run_measured.sh` is given
`mmlupro-e4b-s2` while lm-eval writes `mmlupro100-e4b-s2`. A thinking-on run
appends `-think` to **both** — `std_mmlupro.sh` sets `OUT=$OUT-think` for the
output, and the label needs it too because `run_detail.py:42` matches a run to
its telemetry with a `-(s\d)-\d{8}` regex over the *measured* directory name,
which is built from the label. Without it, a thinking-on and thinking-off run of
the same model and subset both produce `mmlupro-e4b-s2-<stamp>` and the lookup
silently returns whichever ran last.
`SRVLOG` must be built from `output_dir`; built from the label it would point at
a file that never exists, `run_measured.sh` would fall back to parsing the
journal, and the Jetson has no `llama-server` unit — so `requests.csv` would come
out empty and silent.

- [ ] **Step 1: Write the failing test**

Create `benchmark/tests/test_kinds.py`:

```python
import tempfile
import unittest

from jobqueue import kinds, paths


class TestKinds(unittest.TestCase):
    def setUp(self):
        self.reg = kinds.load()
        self.pi = paths.Paths("/home/mitlab/Research", "pi")
        self.jetson = paths.Paths("/home/ari/research", "jetson")

    def test_registry_ships_mmlupro_and_raw(self):
        self.assertIn("mmlupro", self.reg)
        self.assertIn("raw", self.reg)

    def test_validate_accepts_known_params(self):
        got = kinds.validate(self.reg, "mmlupro",
                             {"model": "e4b", "subset": "s2", "thinking": "off"})
        self.assertEqual(got["model"], "e4b")

    def test_validate_fills_defaults(self):
        got = kinds.validate(self.reg, "mmlupro", {"model": "e2b", "subset": "s1"})
        self.assertEqual(got["thinking"], "off")

    def test_validate_rejects_unknown_kind(self):
        with self.assertRaises(kinds.ValidationError):
            kinds.validate(self.reg, "nonsense", {})

    def test_validate_rejects_bad_enum_value(self):
        with self.assertRaises(kinds.ValidationError) as cm:
            kinds.validate(self.reg, "mmlupro",
                           {"model": "e9b", "subset": "s1", "thinking": "off"})
        self.assertIn("e9b", str(cm.exception))

    def test_validate_rejects_unexpected_param(self):
        with self.assertRaises(kinds.ValidationError):
            kinds.validate(self.reg, "mmlupro",
                           {"model": "e2b", "subset": "s1", "colour": "green"})

    def test_pi_command_uses_the_pi_run_script(self):
        got = kinds.resolve(self.reg, "mmlupro",
                            {"model": "e4b", "subset": "s2", "thinking": "off"}, self.pi)
        self.assertEqual(got["label"], "mmlupro-e4b-s2")
        self.assertEqual(got["output_dir"], "mmlupro100-e4b-s2")
        self.assertIn("./std_mmlupro.sh e4b", got["command"])
        self.assertIn("SUBSET=s2", got["command"])
        self.assertNotIn("SRVLOG", got["env"])

    def test_jetson_command_sets_srvlog_from_the_output_dir(self):
        got = kinds.resolve(self.reg, "mmlupro",
                            {"model": "e4b", "subset": "s2", "thinking": "off"},
                            self.jetson)
        self.assertIn("./std_mmlupro_jetson.sh e4b", got["command"])
        self.assertEqual(got["env"]["SRVLOG"],
                         "/home/ari/research/stdbench/mmlupro100-e4b-s2/server.log")

    def test_thinking_on_appends_think_to_output_dir_and_srvlog(self):
        got = kinds.resolve(self.reg, "mmlupro",
                            {"model": "e4b", "subset": "s2", "thinking": "on"},
                            self.jetson)
        # Both gain the suffix. The label becomes the measured directory name,
        # which run_detail.py:42 uses to match a run to its telemetry; if a
        # thinking run were labelled the same as the baseline it would collide.
        self.assertEqual(got["label"], "mmlupro-e4b-s2-think")
        self.assertEqual(got["output_dir"], "mmlupro100-e4b-s2-think")
        self.assertTrue(got["env"]["SRVLOG"].endswith("mmlupro100-e4b-s2-think/server.log"))

    def test_thinking_selects_a_different_baseline(self):
        off = kinds.resolve(self.reg, "mmlupro",
                            {"model": "e2b", "subset": "s1", "thinking": "off"}, self.pi)
        on = kinds.resolve(self.reg, "mmlupro",
                           {"model": "e2b", "subset": "s1", "thinking": "on"}, self.pi)
        self.assertEqual(off["baseline"], "mmlupro-baseline")
        self.assertEqual(on["baseline"], "mmlupro-thinking-on")

    def test_raw_kind_wraps_a_free_command(self):
        got = kinds.resolve(self.reg, "raw",
                            {"label": "smoke", "command": "./std_run.sh queue"}, self.pi)
        self.assertEqual(got["label"], "smoke")
        self.assertIn("./std_run.sh queue", got["command"])
        self.assertIsNone(got["baseline"])

    def test_raw_label_rejects_shell_metacharacters(self):
        with self.assertRaises(kinds.ValidationError):
            kinds.validate(self.reg, "raw", {"label": "a; rm -rf /", "command": "true"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd benchmark && python3 -m unittest tests.test_kinds -v`
Expected: FAIL — `ImportError: cannot import name 'kinds'`

- [ ] **Step 3: Write the registry**

Create `benchmark/job_kinds.json`:

```json
{
  "mmlupro": {
    "description": "MMLU-Pro on one 100-question subset, one model.",
    "params": {
      "model":    {"enum": ["e2b", "e4b"]},
      "subset":   {"enum": ["s1", "s2", "s3"]},
      "thinking": {"enum": ["off", "on"], "default": "off"}
    },
    "label": "mmlupro-{model}-{subset}",
    "output_dir": "mmlupro100-{model}-{subset}",
    "suffix_when": {"thinking": {"on": "-think"}},
    "baseline": {"thinking": {"off": "mmlupro-baseline", "on": "mmlupro-thinking-on"}},
    "memory_mb": {"e2b": 3900, "e4b": 5400},
    "boards": {
      "pi": {
        "command": "env SUBSET={subset} THINKING={thinking} ./std_mmlupro.sh {model}",
        "env": {}
      },
      "jetson": {
        "command": "env SUBSET={subset} THINKING={thinking} ./std_mmlupro_jetson.sh {model}",
        "env": {"SRVLOG": "{stdbench}/{output_dir}/server.log", "SUBSET": "{subset}"}
      }
    }
  },

  "raw": {
    "description": "Any command, wrapped in run_measured.sh. The escape hatch.",
    "params": {
      "label":   {"pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"},
      "command": {"free_text": true}
    },
    "label": "{label}",
    "output_dir": "{label}",
    "baseline": null,
    "boards": {
      "pi":     {"command": "{command}", "env": {}},
      "jetson": {"command": "{command}", "env": {}}
    }
  }
}
```

- [ ] **Step 4: Write minimal implementation**

Create `benchmark/jobqueue/kinds.py`:

```python
"""What can be queued, and what each thing turns into on this board.

The dashboard renders its form from this registry, fetched from the device, so
the UI can never offer a job the daemon would not accept.
"""
import json
import os
import re

from . import paths as _paths


class ValidationError(Exception):
    pass


def load(path=None):
    path = path or os.path.join(_paths.bench_dir(), "job_kinds.json")
    with open(path) as f:
        return json.load(f)


def validate(registry, kind, params):
    spec = registry.get(kind)
    if spec is None:
        raise ValidationError("unknown job kind: %r (have: %s)"
                              % (kind, ", ".join(sorted(registry))))
    declared = spec["params"]
    unexpected = set(params) - set(declared)
    if unexpected:
        raise ValidationError("%s takes no parameter %s"
                              % (kind, ", ".join(sorted(unexpected))))

    out = {}
    for name, rule in declared.items():
        if name in params:
            value = params[name]
        elif "default" in rule:
            value = rule["default"]
        else:
            raise ValidationError("%s needs a %s" % (kind, name))

        if not isinstance(value, str):
            raise ValidationError("%s.%s must be a string" % (kind, name))
        if "enum" in rule and value not in rule["enum"]:
            raise ValidationError("%s.%s: %r is not one of %s"
                                  % (kind, name, value, ", ".join(rule["enum"])))
        if "pattern" in rule and not re.match(rule["pattern"], value):
            raise ValidationError("%s.%s: %r does not match %s"
                                  % (kind, name, value, rule["pattern"]))
        out[name] = value
    return out


def pick(mapping, params):
    """Resolve a {"param": {"value": result}} lookup against the job's params."""
    if mapping is None:
        return None
    if isinstance(mapping, str):
        return mapping
    (param, table), = mapping.items()
    return table.get(params.get(param))


def pick_memory(spec, params):
    """The MB this job kind needs for this model, or None if it declares none."""
    table = spec.get("memory_mb")
    if not table:
        return None
    return table.get(params.get("model"))


def pick_baseline(spec, params):
    """The baselines.json key this job must match, or None for an unchecked kind."""
    return pick(spec.get("baseline"), params)


def resolve(registry, kind, params, paths):
    spec = registry[kind]
    params = validate(registry, kind, params)

    label = spec["label"].format(**params)
    output_dir = spec["output_dir"].format(**params)
    # The suffix goes on BOTH. run_detail.py:42 matches a benchmark run to the
    # measured run that produced it by model plus a -(s\d)-\d{8} regex over the
    # measured directory name, which is built from the label. Leave the label
    # unsuffixed and a thinking-on and thinking-off run of the same model and
    # subset both land at mmlupro-e4b-s2-<stamp>; the lookup then returns
    # whichever is newer and silently attaches the wrong telemetry.
    suffix = pick(spec.get("suffix_when"), params)
    if suffix:
        label += suffix
        output_dir += suffix

    board = spec["boards"].get(paths.board)
    if board is None:
        raise ValidationError("%s cannot run on %s" % (kind, paths.board))

    fields = dict(params, label=label, output_dir=output_dir,
                  stdbench=paths.stdbench, measured=paths.measured)
    env = {k: v.format(**fields) for k, v in board.get("env", {}).items()}
    inner = board["command"].format(**fields)

    return {
        "label": label,
        "output_dir": output_dir,
        "command": "./run_measured.sh %s -- %s" % (label, inner),
        "env": env,
        "baseline": pick_baseline(spec, params),
        "memory_mb": pick_memory(spec, params),
        # The normalised params travel with the result so callers do not have
        # to validate a second time to learn what the defaults filled in.
        "params": params,
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd benchmark && python3 -m unittest tests.test_kinds -v`
Expected: PASS, 12 tests

- [ ] **Step 6: Commit**

```bash
git add benchmark/job_kinds.json benchmark/jobqueue/kinds.py benchmark/tests/test_kinds.py
git commit -m "Declare what can be queued, so adding IFEval is one entry"
```

---

## Task 5: Prechecks

**Files:**
- Create: `benchmark/jobqueue/prechecks.py`
- Test: `benchmark/tests/test_prechecks.py`

**Interfaces:**
- Consumes: `jobqueue.paths.Paths` (Task 1), the `resolve()` dict from
  `jobqueue.kinds` (Task 4)
- Produces:
  - `run_all(paths, resolved, probe=None) -> list[dict]` — each
    `{"name", "ok", "detail", "measured"}`
  - `Probe` — the injectable seam: `mem_available_mb()`, `rss_by_user()`,
    `busy_processes()`
  - `passed(results) -> bool`

- [ ] **Step 1: Write the failing test**

Create `benchmark/tests/test_prechecks.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd benchmark && python3 -m unittest tests.test_prechecks -v`
Expected: FAIL — `ImportError: cannot import name 'prechecks'`

- [ ] **Step 3: Write minimal implementation**

Create `benchmark/jobqueue/prechecks.py`:

```python
"""Checks that run before a job starts.

Refusing to start costs seconds; finding out three hours in costs the run.
mmlupro100-e4b-s2 was OOM-killed at question 94 after 2h39m, which is where
the memory thresholds come from.

Every result carries the measured value, not just a verdict, so a refusal
explains itself.
"""
import os
import subprocess


class Probe:
    """The parts that touch the real machine, isolated so tests can replace them."""

    def mem_available_mb(self):
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) // 1024
        except OSError:
            pass
        return 0

    def rss_by_user(self):
        try:
            out = subprocess.run(["ps", "-eo", "user,rss", "--no-headers"],
                                 capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return {}
        totals = {}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                totals[parts[0]] = totals.get(parts[0], 0) + int(parts[1]) // 1024
        return {u: mb for u, mb in totals.items() if mb > 50}

    def busy_processes(self):
        """Benchmark processes already running. Uses pgrep -f with a bracketed
        first character so the pattern cannot match the pgrep call itself
        (AGENTS §4.2)."""
        found = []
        for name, pattern in (("lm_eval", "[l]m_eval"),
                              ("run_measured", "[r]un_measured"),
                              ("llama-server", "[l]lama-server")):
            try:
                rc = subprocess.run(["pgrep", "-f", pattern],
                                    capture_output=True, timeout=10).returncode
            except (OSError, subprocess.SubprocessError):
                continue
            if rc == 0:
                found.append(name)
        return found


def _memory(paths, resolved, probe):
    need = resolved.get("memory_mb")
    if not need:
        return {"name": "memory", "ok": True, "measured": None,
                "detail": "this job kind declares no memory requirement"}
    have = probe.mem_available_mb()
    if have >= need:
        return {"name": "memory", "ok": True, "measured": have,
                "detail": "%d MB available, need ~%d MB" % (have, need)}
    others = probe.rss_by_user()
    who = "; ".join("%s %d MB" % (u, mb) for u, mb in sorted(others.items()))
    return {"name": "memory", "ok": False, "measured": have,
            "detail": "only %d MB available, need ~%d MB%s"
                      % (have, need, (" — on the board: " + who) if who else "")}


def _output_dir(paths, resolved, probe):
    target = os.path.join(paths.stdbench, resolved["output_dir"])
    if os.path.isdir(target):
        return {"name": "output_dir", "ok": False, "measured": target,
                "detail": "%s already exists — a stale lm-eval cache there is "
                          "replayed instead of regenerated; move it aside" % target}
    return {"name": "output_dir", "ok": True, "measured": target,
            "detail": "no stale directory at %s" % target}


def _subset_ids(paths, resolved, probe):
    subset = (resolved.get("params") or {}).get("subset")
    if not subset:
        return {"name": "subset_ids", "ok": True, "measured": None,
                "detail": "no subset for this job kind"}
    f = os.path.join(paths.stdbench, "mmlupro_subset100_%s_samples.json" % subset)
    if not os.path.isfile(f):
        return {"name": "subset_ids", "ok": False, "measured": f,
                "detail": "%s is missing — both boards must run the identical "
                          "question subset (AGENTS §5)" % f}
    return {"name": "subset_ids", "ok": True, "measured": f,
            "detail": "subset %s ids present" % subset}


def _board_idle(paths, resolved, probe):
    busy = probe.busy_processes()
    if busy:
        return {"name": "board_idle", "ok": False, "measured": busy,
                "detail": "already running: %s — a second concurrent run "
                          "invalidates the telemetry of both (AGENTS §9)"
                          % ", ".join(busy)}
    return {"name": "board_idle", "ok": True, "measured": [],
            "detail": "no benchmark processes running"}


CHECKS = (_memory, _output_dir, _subset_ids, _board_idle)


def run_all(paths, resolved, probe=None):
    probe = probe or Probe()
    return [check(paths, resolved, probe) for check in CHECKS]


def passed(results):
    return all(r["ok"] for r in results)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd benchmark && python3 -m unittest tests.test_prechecks -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add benchmark/jobqueue/prechecks.py benchmark/tests/test_prechecks.py
git commit -m "Refuse in seconds what would otherwise fail in three hours"
```

---

## Task 6: The fingerprint

**Files:**
- Create: `benchmark/baselines.json`
- Create: `benchmark/jobqueue/fingerprint.py`
- Test: `benchmark/tests/test_fingerprint.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - `parse_flags(argv_line) -> dict` — keys `ctx`, `cache_ram`, `reasoning`,
    `reasoning_budget`, `reasoning_format`, `ngl`, `model`
  - `capture(runner=None) -> dict` — keys `server_args`, `model_path`,
    `governor`, `kernel`, `flags`
  - `load_baselines(path=None) -> dict`
  - `diff(flags, expected) -> list[dict]` — each `{"key", "expected", "actual", "ok"}`
  - `agrees(rows) -> bool`

**Capture timing is the entire point.** `run_measured.sh` writes `meta.json`
*before* starting the wrapped command, so its `server_args` is always the
previous server: four of six archived Pi runs name the wrong model and all six
say `-c 4096` where the run sets `8192`; the Jetson's is empty for all nine.
This function must be called *after* the run's server is serving. A fingerprint
captured the way `meta.json` captures reproduces the original bug exactly.

- [ ] **Step 1: Write the failing test**

Create `benchmark/tests/test_fingerprint.py`:

```python
import unittest

from jobqueue import fingerprint

# The Jetson's resolved command line before 2026-09-22. Neither -rea nor
# --reasoning-budget is present, so -rea fell back to 'auto', Gemma's template
# turned thinking on, and the default --reasoning-format auto filed the thoughts
# under reasoning_content where lm-eval never reads them. Every Jetson MMLU-Pro
# run before that date lost its answer this way: median response 993 characters
# against the Pi's 1,880, and 11 of 100 completely empty.
JETSON_BROKEN = (
    "/home/ari/build/llama.cpp/build/bin/llama-server "
    "-m /home/ari/research/models/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf "
    "-c 8192 --host 127.0.0.1 --port 8080 -ngl 99 --cache-ram 0")

JETSON_FIXED = (
    "/home/ari/build/llama.cpp/build/bin/llama-server "
    "-m /home/ari/research/models/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf "
    "-c 8192 --host 127.0.0.1 --port 8080 -ngl 99 "
    "-rea off --reasoning-budget -1 --cache-ram 0")

PI_BASELINE = (
    "/home/mitlab/llama.cpp/build/bin/llama-server "
    "-m /home/mitlab/models/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf "
    "-t 3 -c 8192 --host 127.0.0.1 --port 8080 -rea off --reasoning-budget -1 "
    "--cache-ram 0")


class TestParseFlags(unittest.TestCase):
    def test_reads_the_flags_the_baseline_asserts_on(self):
        f = fingerprint.parse_flags(PI_BASELINE)
        self.assertEqual(f["ctx"], "8192")
        self.assertEqual(f["reasoning"], "off")
        self.assertEqual(f["reasoning_budget"], "-1")
        self.assertEqual(f["cache_ram"], "0")

    def test_absent_flags_read_as_none(self):
        f = fingerprint.parse_flags(JETSON_BROKEN)
        self.assertIsNone(f["reasoning"])
        self.assertIsNone(f["reasoning_budget"])

    def test_long_form_reasoning_is_the_same_flag_as_rea(self):
        # -rea is the short form of --reasoning, the thinking switch. It is NOT
        # --reasoning-format, which is a separate flag. AGENTS §5 had these
        # confused until 2026-09-22.
        f = fingerprint.parse_flags("llama-server --reasoning off")
        self.assertEqual(f["reasoning"], "off")

    def test_reasoning_format_is_not_confused_with_reasoning(self):
        f = fingerprint.parse_flags("llama-server -rea on --reasoning-format none")
        self.assertEqual(f["reasoning"], "on")
        self.assertEqual(f["reasoning_format"], "none")

    def test_reads_model_and_ngl(self):
        f = fingerprint.parse_flags(JETSON_FIXED)
        self.assertTrue(f["model"].endswith("gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf"))
        self.assertEqual(f["ngl"], "99")

    def test_empty_command_line_yields_all_none(self):
        f = fingerprint.parse_flags("")
        self.assertIsNone(f["ctx"])


class TestDiff(unittest.TestCase):
    def setUp(self):
        self.baselines = fingerprint.load_baselines()

    def test_the_2026_09_22_jetson_regression_is_caught(self):
        rows = fingerprint.diff(fingerprint.parse_flags(JETSON_BROKEN),
                                self.baselines["mmlupro-baseline"]["flags"])
        self.assertFalse(fingerprint.agrees(rows))
        bad = [r["key"] for r in rows if not r["ok"]]
        self.assertIn("reasoning", bad)

    def test_the_corrected_jetson_command_agrees(self):
        rows = fingerprint.diff(fingerprint.parse_flags(JETSON_FIXED),
                                self.baselines["mmlupro-baseline"]["flags"])
        self.assertTrue(fingerprint.agrees(rows), rows)

    def test_the_pi_baseline_agrees_with_the_same_declaration(self):
        # Both boards must satisfy one declaration or the comparison is void.
        rows = fingerprint.diff(fingerprint.parse_flags(PI_BASELINE),
                                self.baselines["mmlupro-baseline"]["flags"])
        self.assertTrue(fingerprint.agrees(rows), rows)

    def test_a_4096_context_is_caught(self):
        # The deployed default truncates: the longest subset prompt is 2,427
        # tokens and the answer budget is 2,048 (AGENTS §4.4).
        line = PI_BASELINE.replace("-c 8192", "-c 4096")
        rows = fingerprint.diff(fingerprint.parse_flags(line),
                                self.baselines["mmlupro-baseline"]["flags"])
        self.assertIn("ctx", [r["key"] for r in rows if not r["ok"]])

    def test_thinking_on_baseline_requires_reasoning_format_none(self):
        flags = fingerprint.parse_flags(
            "llama-server -c 8192 --cache-ram 0 -rea on --reasoning-budget 320")
        rows = fingerprint.diff(flags, self.baselines["mmlupro-thinking-on"]["flags"])
        self.assertIn("reasoning_format", [r["key"] for r in rows if not r["ok"]])

    def test_diff_rows_carry_both_values_for_display(self):
        rows = fingerprint.diff(fingerprint.parse_flags(JETSON_BROKEN),
                                self.baselines["mmlupro-baseline"]["flags"])
        row = next(r for r in rows if r["key"] == "reasoning")
        self.assertEqual(row["expected"], "off")
        self.assertIsNone(row["actual"])


class TestCapture(unittest.TestCase):
    def test_capture_uses_the_injected_runner(self):
        calls = []

        def fake(cmd, **kw):
            calls.append(cmd)
            if cmd[0] == "ps":
                return PI_BASELINE
            if cmd[0] == "curl":
                return '{"model_path": "/home/mitlab/models/x.gguf"}'
            return "somevalue"

        got = fingerprint.capture(runner=fake)
        self.assertEqual(got["flags"]["reasoning"], "off")
        self.assertEqual(got["model_path"], "/home/mitlab/models/x.gguf")
        self.assertIn(["ps", "-o", "args=", "-C", "llama-server"], calls)

    def test_capture_survives_an_unparseable_props_response(self):
        got = fingerprint.capture(runner=lambda cmd, **kw:
                                  PI_BASELINE if cmd[0] == "ps" else "not json")
        self.assertEqual(got["model_path"], "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd benchmark && python3 -m unittest tests.test_fingerprint -v`
Expected: FAIL — `ImportError: cannot import name 'fingerprint'`

- [ ] **Step 3: Write the baselines**

Create `benchmark/baselines.json`:

```json
{
  "mmlupro-baseline": {
    "description": "Thinking off. Verified 2026-09-22 against llama-server --help on both boards: -rea is --reasoning, the thinking switch, NOT --reasoning-format. --reasoning-budget -1 is already llama.cpp's default; it is passed explicitly so the resolved command line records it.",
    "flags": {
      "ctx": "8192",
      "cache_ram": "0",
      "reasoning": "off",
      "reasoning_budget": "-1"
    }
  },
  "mmlupro-thinking-on": {
    "description": "The reasoning row. --reasoning-format MUST be pinned to none: left at its 'auto' default the thoughts go to message.reasoning_content, which lm-eval never reads, and answers arrive truncated or empty.",
    "flags": {
      "ctx": "8192",
      "cache_ram": "0",
      "reasoning": "on",
      "reasoning_budget": "320",
      "reasoning_format": "none"
    }
  }
}
```

- [ ] **Step 4: Write minimal implementation**

Create `benchmark/jobqueue/fingerprint.py`:

```python
"""What the server is actually serving, against what it was supposed to.

The Pi reaches llama-server through va-llm and runtime.env; the Jetson launches
it directly. Comparing the *inputs* on each board compares two incomparable
things. The resolved command line is the only common ground — which is what
AGENTS §10 says to diff, and what nothing was doing automatically.
"""
import json
import os
import subprocess

from . import paths as _paths

# Flag name -> the keys that introduce it. -rea is the short form of
# --reasoning. --reasoning-format is a DIFFERENT flag; keeping them apart is
# the whole reason this module exists.
_FLAGS = {
    "ctx": ("-c", "--ctx-size"),
    "cache_ram": ("--cache-ram",),
    "reasoning": ("-rea", "--reasoning"),
    "reasoning_budget": ("--reasoning-budget",),
    "reasoning_format": ("--reasoning-format",),
    "ngl": ("-ngl", "--n-gpu-layers"),
    "model": ("-m", "--model"),
}
_LOOKUP = {flag: key for key, flags in _FLAGS.items() for flag in flags}


def parse_flags(argv_line):
    out = {key: None for key in _FLAGS}
    tokens = (argv_line or "").split()
    for i, token in enumerate(tokens):
        key = _LOOKUP.get(token)
        if key is None:
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        # -rea takes an optional value; a following flag means it was omitted.
        if nxt is not None and not nxt.startswith("-"):
            out[key] = nxt
        elif nxt is not None and key in ("reasoning_budget",) and _is_number(nxt):
            out[key] = nxt
    return out


def _is_number(tok):
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def capture(runner=None):
    run = runner or _run
    args = run(["ps", "-o", "args=", "-C", "llama-server"])
    props = run(["curl", "-s", "-m", "3", "http://127.0.0.1:8080/props"])
    model = ""
    try:
        model = json.loads(props).get("model_path", "")
    except (ValueError, AttributeError):
        model = ""
    return {
        "server_args": args,
        "model_path": model,
        "governor": run(["cat", "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"]),
        "kernel": run(["uname", "-sr"]),
        "flags": parse_flags(args),
    }


def load_baselines(path=None):
    path = path or os.path.join(_paths.bench_dir(), "baselines.json")
    with open(path) as f:
        return json.load(f)


def diff(flags, expected):
    rows = []
    for key in sorted(expected):
        want = expected[key]
        got = flags.get(key)
        rows.append({"key": key, "expected": want, "actual": got,
                     "ok": got is not None and str(got) == str(want)})
    return rows


def agrees(rows):
    return all(r["ok"] for r in rows)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd benchmark && python3 -m unittest tests.test_fingerprint -v`
Expected: PASS, 15 tests

- [ ] **Step 6: Commit**

```bash
git add benchmark/baselines.json benchmark/jobqueue/fingerprint.py benchmark/tests/test_fingerprint.py
git commit -m "Make the AGENTS §10 check automatic, with the regression as a fixture"
```

---

## Task 7: The runner state machine

> **Corrected during implementation (2026-09-22).** The code below captures the
> fingerprint *before* `_execute`, which is the exact bug the spec warned
> against: the run script is what configures the server, so at that moment the
> flags belong to whatever the board was already running — the idle deployed
> server on the Pi, nothing at all on the Jetson. Every `mmlupro` job would
> block. The shipped `jobqueue/runner.py` instead starts the command, polls for
> the run's own server, diffs then, and kills the run on drift. The `exec_fn`
> seam became `start_fn`, returning a still-running process. See the tests in
> `TestFingerprintTiming`, which assert the ordering the old fakes could not
> express.

**Files:**
- Create: `benchmark/jobqueue/runner.py`
- Test: `benchmark/tests/test_runner.py`

**Interfaces:**
- Consumes: `paths` (1), `store` (2), `events` (3), `kinds` (4),
  `prechecks` (5), `fingerprint` (6)
- Produces:
  - `class Runner(paths, registry, baselines, exec_fn, probe=None, capture_fn=None, clock=time.time)`
  - `Runner.tick() -> bool` — performs at most one transition; True if it did work
  - `exec_fn(command, env, cwd, log_path) -> int` — the injected seam that runs
    the wrapped command and returns its exit status

- [ ] **Step 1: Write the failing test**

Create `benchmark/tests/test_runner.py`:

```python
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
        self.registry = kinds.load()
        self.baselines = fingerprint.load_baselines()
        self.executed = []

    def make(self, args=GOOD_ARGS, rc=0, done=True, mem=9000):
        def exec_fn(command, env, cwd, log_path):
            self.executed.append(command)
            if done:
                out = os.path.join(self.p.stdbench, "mmlupro100-e4b-s2")
                os.makedirs(out, exist_ok=True)
                open(os.path.join(out, ".done"), "w").close()
            return rc

        return runner.Runner(self.p, self.registry, self.baselines,
                             exec_fn=exec_fn, probe=FakeProbe(mem),
                             capture_fn=lambda: fingerprint.capture(
                                 runner=lambda cmd, **kw:
                                 args if cmd[0] == "ps" else "{}"))

    def queue_one(self, **params):
        p = dict(model="e4b", subset="s2", thinking="off", **params)
        resolved = kinds.resolve(self.registry, "mmlupro", p, self.p)
        job = store.new_job(kind="mmlupro", params=p, label=resolved["label"],
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
        self.queue_one(subset="s2")
        r = self.make()
        r.tick()
        r.tick()
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd benchmark && python3 -m unittest tests.test_runner -v`
Expected: FAIL — `ImportError: cannot import name 'runner'`

- [ ] **Step 3: Write minimal implementation**

Create `benchmark/jobqueue/runner.py`:

```python
"""One job at a time, and the checks that gate it.

Every effect the board has on the outcome — running a command, reading memory,
reading the server's command line — arrives through an injected function, so
the whole state machine is testable on a Mac with no board attached and no
benchmark ever executed.
"""
import json
import os
import subprocess
import time

from . import events, fingerprint as fp, kinds, paths as _paths, prechecks, store


def default_exec(command, env, cwd, log_path):
    """Run the wrapped command, streaming to log_path. Returns its exit status.

    shell=True is deliberate and required: the commands this runs are shell
    constructs by design — `./run_measured.sh <label> -- env SUBSET=s2
    ./std_mmlupro_jetson.sh e4b` — and the `raw` job kind exists precisely so a
    human can queue an arbitrary command. It is not an injection hole to close
    but the feature itself.

    What bounds it: every non-raw kind builds its command from enum-validated
    parameters (jobqueue/kinds.py), and the `label` that reaches the
    run_measured.sh wrapper is pattern-validated
    `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` for `raw` too, so no metacharacter can
    escape the wrapper into the surrounding line. Queueing at all requires
    either an ssh session on the board or the dashboard, which runs on
    localhost and authenticates with the operator's own key — both of which
    already grant a shell. This is a single-user lab tool, and `raw` grants
    nothing its caller did not already have.
    """
    full = dict(os.environ)
    full.update(env or {})
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as log:
        proc = subprocess.Popen(command, shell=True, cwd=cwd, env=full,
                                stdout=log, stderr=subprocess.STDOUT)
        return proc.wait()


class Runner:
    def __init__(self, paths, registry, baselines, exec_fn=None, probe=None,
                 capture_fn=None, clock=time.time):
        self.paths = paths
        self.registry = registry
        self.baselines = baselines
        self.exec_fn = exec_fn or default_exec
        self.probe = probe
        self.capture_fn = capture_fn or fp.capture
        self.clock = clock

    # -- helpers ---------------------------------------------------------

    def _write(self, job_id, name, payload):
        d = self.paths.job_dir(job_id)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w") as f:
            json.dump(payload, f, indent=1)

    def _resolved(self, job):
        """The parts prechecks needs, rebuilt from the stored job."""
        spec = self.registry.get(job["kind"], {})
        return {"label": job["label"], "output_dir": job["output_dir"],
                "params": job["params"],
                "memory_mb": kinds.pick_memory(spec, job["params"])}

    def _baseline_for(self, job):
        spec = self.registry.get(job["kind"], {})
        name = kinds.pick_baseline(spec, job["params"])
        return name, (self.baselines.get(name) if name else None)

    # -- the machine -----------------------------------------------------

    def tick(self):
        if store.active(self.paths) is not None:
            return False
        job = store.next_eligible(self.paths, now=self.clock())
        if job is None:
            return False
        self._run_one(job)
        return True

    def _run_one(self, job):
        jid = job["id"]

        store.update(self.paths, jid, state="prechecking")
        results = prechecks.run_all(self.paths, self._resolved(job), self.probe)
        self._write(jid, "precheck.json", results)
        if not prechecks.passed(results):
            failed = [r["detail"] for r in results if not r["ok"]]
            events.emit(self.paths, jid, "precheck_failed", detail="; ".join(failed))
            store.update(self.paths, jid, state="blocked",
                         finished=self.clock(), note="; ".join(failed))
            return
        events.emit(self.paths, jid, "precheck_passed")

        store.update(self.paths, jid, state="fingerprinting")
        name, baseline = self._baseline_for(job)
        captured = self.capture_fn()
        rows = fp.diff(captured["flags"], baseline["flags"]) if baseline else []
        agrees = fp.agrees(rows) if baseline else True
        self._write(jid, "fingerprint.json",
                    {"baseline": name, "captured": captured,
                     "diff": rows, "agrees": agrees})

        if not agrees:
            bad = ", ".join("%s: expected %s, got %s"
                            % (r["key"], r["expected"], r["actual"])
                            for r in rows if not r["ok"])
            if not job.get("override_fingerprint"):
                events.emit(self.paths, jid, "fingerprint_drift", detail=bad)
                store.update(self.paths, jid, state="blocked",
                             finished=self.clock(), note=bad)
                return
            # Recorded, and the job carries the mark from here on: AGENTS §5
            # reports every run, including the ones someone waved through.
            events.emit(self.paths, jid, "fingerprint_overridden", detail=bad)
        else:
            events.emit(self.paths, jid, "fingerprint_ok", baseline=name)

        self._execute(job)

    def _execute(self, job):
        jid = job["id"]
        cwd = _paths.bench_dir()
        log_path = os.path.join(self.paths.job_dir(jid), "command.log")

        store.update(self.paths, jid, state="running", started=self.clock())
        events.emit(self.paths, jid, "started", command=job["command"])
        try:
            rc = self.exec_fn(job["command"], job["env"], cwd, log_path)
        except Exception as exc:                      # noqa: BLE001 - reported, not raised
            events.emit(self.paths, jid, "failed", detail=repr(exc))
            store.update(self.paths, jid, state="failed",
                         finished=self.clock(), note=repr(exc))
            return

        # Exit status is not evidence: std_mmlupro_jetson.sh ends on
        # `echo finished` and always returns 0. The .done marker is the signal.
        marker = os.path.join(self.paths.stdbench, job["output_dir"], ".done")
        if os.path.isfile(marker):
            events.emit(self.paths, jid, "completed", exit_code=rc)
            store.update(self.paths, jid, state="completed",
                         finished=self.clock(), exit_code=rc)
        else:
            tail = self._tail(log_path)
            events.emit(self.paths, jid, "failed", exit_code=rc,
                        detail="no .done marker", tail=tail)
            store.update(self.paths, jid, state="failed", finished=self.clock(),
                         exit_code=rc, note="no .done marker at %s" % marker)

    @staticmethod
    def _tail(path, lines=20):
        try:
            with open(path) as f:
                return f.read().splitlines()[-lines:]
        except OSError:
            return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd benchmark && python3 -m unittest tests.test_runner -v`
Expected: PASS, 13 tests

- [ ] **Step 5: Run the whole suite**

Run: `cd benchmark && python3 -m unittest discover -s tests -v`
Expected: PASS, all tests from Tasks 1–7

- [ ] **Step 6: Commit**

```bash
git add benchmark/jobqueue/runner.py benchmark/tests/test_runner.py
git commit -m "Run one job at a time, and judge it by the .done marker"
```

---

## Task 8: The CLI

**Files:**
- Create: `benchmark/queue_ctl.py`
- Test: `benchmark/tests/test_queue_ctl.py`

**Interfaces:**
- Consumes: every `jobqueue` module (Tasks 1–7)
- Produces: a CLI whose every subcommand prints one JSON object to stdout and
  exits 0 on success, 1 on a handled error (`{"error": "..."}`), so the
  dashboard never has to parse prose:
  - `--describe` → `{"board", "kinds", "baselines", "timezone"}`
  - `--preflight JSON` → `{"resolved", "prechecks", "ok"}`
  - `--add JSON` → `{"job": {...}}`
  - `--cancel ID` → `{"job": {...}}`
  - `--status` → `{"board", "jobs", "active", "daemon_alive", "events", "offset"}`
  - `--log ID --stream NAME [--from N]` → `{"text", "offset", "eof"}`

- [ ] **Step 1: Write the failing test**

Create `benchmark/tests/test_queue_ctl.py`:

```python
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
                              capture_output=True, text=True, env=env)
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

    def test_log_rejects_an_unknown_stream_name(self):
        rc, out = self.ctl("--log", "whatever", "--stream", "../../etc/passwd")
        self.assertEqual(rc, 1)
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd benchmark && python3 -m unittest tests.test_queue_ctl -v`
Expected: FAIL — the script does not exist

- [ ] **Step 3: Write minimal implementation**

Create `benchmark/queue_ctl.py` (and `chmod +x` it):

```python
#!/usr/bin/env python3
"""The one thing the dashboard runs over ssh.

Every subcommand prints a single JSON object and exits 0, or prints
{"error": "..."} and exits 1. AGENTS §7: work the dashboard needs from a device
goes through a device-side script, not an ad-hoc ssh command in the web app.

    queue_ctl.py --describe
    queue_ctl.py --preflight '{"kind":"mmlupro","params":{...}}'
    queue_ctl.py --add       '{"kind":"mmlupro","params":{...},"not_before":"02:00"}'
    queue_ctl.py --cancel <job_id>
    queue_ctl.py --status [--from <offset>]
    queue_ctl.py --log <job_id> --stream lm_eval|server|command [--from <offset>]
"""
import argparse
import json
import os
import sys
import time

from jobqueue import events, fingerprint, kinds, paths, prechecks, store

# Which log each stream name means, and where it lives. Whitelisted so a stream
# name can never become a path.
STREAMS = {
    "command": ("job", "command.log"),
    "lm_eval": ("output", "lm_eval.log"),
    "server": ("output", "server.log"),
}


def fail(message):
    json.dump({"error": str(message)}, sys.stdout)
    sys.stdout.write("\n")
    sys.exit(1)


def ok(payload):
    json.dump(payload, sys.stdout, default=str)
    sys.stdout.write("\n")
    sys.exit(0)


def parse_not_before(text, now=None):
    """'02:00' in the board's local time -> the next epoch at or after now."""
    now = time.time() if now is None else now
    try:
        hh, mm = text.split(":")
        hh, mm = int(hh), int(mm)
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ValueError
    except (ValueError, AttributeError):
        raise ValueError("not_before must be HH:MM in the board's local time, got %r"
                         % (text,))
    local = time.localtime(now)
    target = time.mktime((local.tm_year, local.tm_mon, local.tm_mday,
                          hh, mm, 0, 0, 0, -1))
    if target < now:
        target += 86400
    return target


def daemon_alive(p):
    try:
        with open(p.pid_file) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def resolve_request(registry, p, body):
    kind = body.get("kind")
    params = body.get("params") or {}
    if kind not in registry:
        raise kinds.ValidationError("unknown job kind: %r" % (kind,))
    return kinds.resolve(registry, kind, params, p)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--describe", action="store_true")
    ap.add_argument("--preflight", metavar="JSON")
    ap.add_argument("--add", metavar="JSON")
    ap.add_argument("--cancel", metavar="JOB_ID")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--log", metavar="JOB_ID")
    # Deliberately not argparse `choices`: that exits 2 with prose on stderr,
    # and the contract with the dashboard is that every outcome is one JSON
    # object. Validated against STREAMS below instead.
    ap.add_argument("--stream", metavar="NAME")
    ap.add_argument("--from", dest="offset", type=int, default=0)
    args = ap.parse_args(argv)

    try:
        p = paths.detect()
    except paths.BoardUnknown as exc:
        fail(exc)

    registry = kinds.load()

    if args.describe:
        ok({"board": p.board, "kinds": registry,
            "baselines": fingerprint.load_baselines(),
            "timezone": time.tzname[0], "root": p.root})

    if args.preflight or args.add:
        raw = args.preflight or args.add
        try:
            body = json.loads(raw)
        except ValueError as exc:
            fail("could not parse request JSON: %s" % exc)
        try:
            resolved = resolve_request(registry, p, body)
        except kinds.ValidationError as exc:
            fail(exc)

        # resolve() already carries the normalised params, so nothing needs
        # validating a second time here.
        checks = prechecks.run_all(p, resolved)
        if args.preflight:
            ok({"resolved": resolved, "prechecks": checks,
                "ok": prechecks.passed(checks)})

        not_before = None
        if body.get("not_before"):
            try:
                not_before = parse_not_before(body["not_before"])
            except ValueError as exc:
                fail(exc)

        job = store.add(p, store.new_job(
            kind=body["kind"], params=resolved["params"],
            label=resolved["label"], output_dir=resolved["output_dir"],
            command=resolved["command"], env=resolved["env"],
            not_before_epoch=not_before))
        events.emit(p, job["id"], "queued", by=body.get("by", "queue_ctl"),
                    label=job["label"])
        ok({"job": job})

    if args.cancel:
        try:
            ok({"job": store.cancel(p, args.cancel)})
        except (store.UnknownJob, store.NotCancellable) as exc:
            fail(exc)

    if args.status:
        recent, offset = events.read(p, offset=args.offset)
        ok({"board": p.board, "jobs": store.load(p)["jobs"],
            "active": store.active(p), "daemon_alive": daemon_alive(p),
            "events": recent, "offset": offset, "ts": time.time()})

    if args.log:
        if not args.stream:
            fail("--log needs --stream")
        if args.stream not in STREAMS:
            # The whitelist is what stops a stream name becoming a path.
            fail("unknown stream %r; choose one of %s"
                 % (args.stream, ", ".join(sorted(STREAMS))))
        where, filename = STREAMS[args.stream]
        job = store.get(p, args.log)
        if where == "job":
            path = os.path.join(p.job_dir(args.log), filename)
        else:
            if job is None:
                fail("unknown job: %s" % args.log)
            path = os.path.join(p.stdbench, job["output_dir"], filename)
        try:
            with open(path) as f:
                f.seek(args.offset)
                text = f.read()
                ok({"text": text, "offset": f.tell(), "eof": True, "path": path})
        except OSError as exc:
            fail("cannot read %s: %s" % (path, exc))

    ap.print_help(sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd benchmark && chmod +x queue_ctl.py && python3 -m unittest tests.test_queue_ctl -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Commit**

```bash
git add benchmark/queue_ctl.py benchmark/tests/test_queue_ctl.py
git commit -m "Give the dashboard one typed entry point instead of ad-hoc ssh"
```

---

## Task 9: The daemon and its unit

**Files:**
- Create: `benchmark/queue_runner.py`
- Create: `benchmark/systemd/agentic-queue.service`
- Create: `benchmark/install_queue.sh`

**Interfaces:**
- Consumes: `jobqueue.runner.Runner` (Task 7), `jobqueue.paths` (Task 1)
- Produces: `queue_runner.py --daemon` (loop) and `--once` (single tick, for
  smoke-testing on a board without leaving anything running)

**Supervision is identical on both boards.** Checked 2026-09-22: `systemctl
--user` reports `running` on each, and `loginctl enable-linger` succeeds without
sudo on the Jetson as well as the Pi. No cron, no `@reboot`, no pidfile
watchdog — systemd owns liveness; `runner.pid` exists only so `--status` and
`check-ssh.mjs` can report staleness without talking to systemd.

- [ ] **Step 1: Write the daemon entry point**

Create `benchmark/queue_runner.py` (and `chmod +x` it):

```python
#!/usr/bin/env python3
"""The queue daemon. One per board, supervised by a systemd user unit.

    queue_runner.py --daemon      run until stopped
    queue_runner.py --once        one tick, then exit (smoke test)

Stdlib only (AGENTS §7). Everything interesting lives in jobqueue/runner.py;
this file is the process wrapper around it.
"""
import argparse
import os
import signal
import sys
import time

from jobqueue import fingerprint, kinds, paths, runner

POLL_SECONDS = 5


def write_pid(p):
    os.makedirs(p.queue_dir, exist_ok=True)
    with open(p.pid_file, "w") as f:
        f.write(str(os.getpid()))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args(argv)

    p = paths.detect()
    r = runner.Runner(p, kinds.load(), fingerprint.load_baselines())

    if args.once:
        did = r.tick()
        print("did work" if did else "nothing to do")
        return 0

    if not args.daemon:
        ap.print_help(sys.stderr)
        return 2

    write_pid(p)
    stopping = {"now": False}

    def stop(signum, frame):
        # A running job is deliberately left alone: it is a detached
        # run_measured.sh with its own telemetry, and killing it mid-run
        # would cost hours. systemd restarts us and we pick the job back up.
        stopping["now"] = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    print("queue_runner: watching %s on %s" % (p.queue_dir, p.board), flush=True)
    while not stopping["now"]:
        try:
            if not r.tick():
                time.sleep(POLL_SECONDS)
        except Exception as exc:                      # noqa: BLE001
            # A crash here must not take the queue down: log and keep going.
            print("queue_runner: tick failed: %r" % (exc,), file=sys.stderr, flush=True)
            time.sleep(POLL_SECONDS)

    try:
        os.remove(p.pid_file)
    except OSError:
        pass
    print("queue_runner: stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the systemd user unit**

Create `benchmark/systemd/agentic-queue.service`:

```ini
[Unit]
Description=Agentic Edge benchmark queue
After=network.target

[Service]
Type=simple
# %h is the user's home: ~/Research/agentic-edge on the Pi,
# ~/research/agentic-edge on the Jetson. install_queue.sh substitutes the
# right one, since the case differs per board (AGENTS §2).
WorkingDirectory=__BENCH_DIR__
ExecStart=/usr/bin/env python3 __BENCH_DIR__/queue_runner.py --daemon
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

- [ ] **Step 3: Write the installer**

Create `benchmark/install_queue.sh` (and `chmod +x` it):

```sh
#!/bin/sh
# Install and start the queue daemon on this board. Run it on the board.
#
#   ./install_queue.sh
#
# Uses a systemd *user* unit, which works identically on both boards: the
# Jetson has no passwordless sudo, but lingering is a per-user setting and
# `loginctl enable-linger` succeeds there without it.
set -eu

BENCH=$(cd "$(dirname "$0")" && pwd)
UNIT_DIR=$HOME/.config/systemd/user
UNIT=$UNIT_DIR/agentic-queue.service

mkdir -p "$UNIT_DIR"
sed "s|__BENCH_DIR__|$BENCH|g" "$BENCH/systemd/agentic-queue.service" > "$UNIT"
echo "wrote $UNIT"

# Without lingering the unit dies at logout, which is exactly when a
# three-hour run needs it most.
loginctl enable-linger "$USER" 2>/dev/null || true
echo -n "linger: "; loginctl show-user "$USER" -p Linger

systemctl --user daemon-reload
systemctl --user enable --now agentic-queue.service
systemctl --user --no-pager status agentic-queue.service | head -5
```

- [ ] **Step 4: Smoke-test the daemon off-board**

```bash
cd benchmark
AGENTIC_QUEUE_ROOT=/tmp/qtest AGENTIC_BOARD=jetson \
  python3 queue_runner.py --once
```

Expected: `nothing to do` (an empty queue), exit 0.

- [ ] **Step 5: Deploy and install on both boards**

`git pull`, never `scp` — AGENTS §4.1 is explicit that overwriting a script a
board is running kills it mid-execution.

```bash
git push
ssh MITLAB-EDGE   'cd ~/Research/agentic-edge && git pull && ./benchmark/install_queue.sh'
ssh MITLAB-JETSON 'cd ~/research/agentic-edge && git pull && ./benchmark/install_queue.sh'
```

Expected on each: `Linger=yes`, and `Active: active (running)`.

- [ ] **Step 6: Verify the suite passes on both boards**

Board-specific bugs have been the norm here — `~/Research` vs `~/research`,
PMIC vs INA3221, journal vs file logs (AGENTS §7).

```bash
ssh MITLAB-EDGE   'cd ~/Research/agentic-edge/benchmark && python3 -m unittest discover -s tests'
ssh MITLAB-JETSON 'cd ~/research/agentic-edge/benchmark && python3 -m unittest discover -s tests'
```

Expected: OK on both.

- [ ] **Step 7: Commit**

```bash
git add benchmark/queue_runner.py benchmark/systemd/ benchmark/install_queue.sh
git commit -m "Supervise the queue with one user unit on both boards"
```

---

## Task 10: Fix the `meta.json` capture in `run_measured.sh`

**Files:**
- Modify: `benchmark/run_measured.sh`

**Interfaces:**
- Consumes: nothing
- Produces: `meta.json` gains `server_args_after` and `flags_after`, captured
  once the wrapped command's server is serving.

**Why:** `run_measured.sh` writes `meta.json` before starting the wrapped
command, but the run script restarts va-llm (Pi) or launches llama-server
(Jetson) afterwards. So `server_args` is the *previous* state — four of six
archived Pi runs name the wrong model, all six say `-c 4096` where the run sets
`8192`, and the Jetson's is empty for all nine. Runs launched outside the queue
need an honest record too.

- [ ] **Step 1: Add the post-start capture**

In `benchmark/run_measured.sh`, find this block:

```sh
WORK_START=$(date +%s)
echo "[$(date +%H:%M:%S)] running: $*"
"$@" > "$OUT/command.log" 2>&1
RC=$?
```

Replace it with:

```sh
WORK_START=$(date +%s)
echo "[$(date +%H:%M:%S)] running: $*"
"$@" > "$OUT/command.log" 2>&1 &
WORK_PID=$!

# meta.json's server_args is captured before the command starts, so it records
# whatever was already running — the idle deployed server on the Pi, nothing at
# all on the Jetson. That is how a missing -rea survived days of review. Take a
# second sample once the run's own server is up, and keep it separately so the
# original field's meaning does not change under anything already reading it.
( for _ in $(seq 60); do
    sleep 5
    ARGS=$(ps -o args= -C llama-server 2>/dev/null | head -1)
    [ -n "$ARGS" ] || continue
    python3 - "$OUT" "$ARGS" <<'PY'
import json, sys
out, args = sys.argv[1], sys.argv[2]
p = out + "/meta.json"
m = json.load(open(p))
if m.get("server_args_after"):
    raise SystemExit(0)
m["server_args_after"] = args
json.dump(m, open(p, "w"), indent=1)
PY
    break
  done ) &

wait "$WORK_PID"
RC=$?
```

- [ ] **Step 2: Verify the script still parses**

Run: `bash -n benchmark/run_measured.sh`
Expected: no output, exit 0

- [ ] **Step 3: Verify on a board with a short real command**

```bash
ssh MITLAB-JETSON 'cd ~/research/agentic-edge/benchmark && \
  IDLE=2 ./run_measured.sh capture-check -- sleep 20'
ssh MITLAB-JETSON 'python3 -c "import json,glob;
p=sorted(glob.glob(\"$HOME/research/measured/capture-check-*/meta.json\"))[-1];
m=json.load(open(p)); print(\"before:\", repr(m.get(\"server_args\"))[:80]);
print(\"after: \", repr(m.get(\"server_args_after\"))[:80])"'
```

Expected: both empty (no server runs for `sleep`), and no crash — the capture
must not break a run that has no llama-server at all.

- [ ] **Step 4: Commit**

```bash
git add benchmark/run_measured.sh
git commit -m "Record the server the run actually used, not the one before it"
```

---

## Task 11: Dashboard API routes

**Files:**
- Create: `dashboard/app/api/queue/route.js`
- Create: `dashboard/app/api/logs/route.js`

**Interfaces:**
- Consumes: `queue_ctl.py` (Task 8); `HOSTS`, `byId`, `SSH`, `hint` from
  `dashboard/app/lib/hosts.js`
- Produces:
  - `GET /api/queue` → `{ts, boxes: [{...host, ok, board, jobs, active, daemon_alive, events, offset}]}`
  - `POST /api/queue` body `{box, kind, params, not_before?}` → `{job}`
  - `POST /api/queue?preflight=1` → `{resolved, prechecks, ok}`
  - `DELETE /api/queue?box=&job=` → `{job}`
  - `GET /api/logs?box=&job=&stream=&from=` → `{text, offset}`

- [ ] **Step 1: Write the queue route**

Create `dashboard/app/api/queue/route.js`:

```js
import { exec } from "node:child_process";
import { promisify } from "node:util";
import { HOSTS, byId, SSH, hint } from "../../lib/hosts";

const run = promisify(exec);

export const dynamic = "force-dynamic";

// Everything goes through queue_ctl.py, which prints one JSON object and exits
// 0, or prints {"error": ...} and exits 1 (AGENTS §7 — no ad-hoc ssh here).
// The payload is single-quoted for the remote shell, so any single quote inside
// it has to be broken out first.
const shq = (s) => `'${String(s).replaceAll("'", `'\\''`)}'`;

async function ctl(box, args, timeout = 30000) {
  const cmd = `ssh ${SSH} ${box.host} '${box.py} ${box.repo}/benchmark/queue_ctl.py ${args}'`;
  try {
    const { stdout } = await run(cmd, { timeout, maxBuffer: 8 * 1024 * 1024 });
    return { ok: true, data: JSON.parse(stdout) };
  } catch (e) {
    // A handled error still prints JSON on stdout and exits 1, so prefer it
    // over the raw stderr: "e9b is not one of e2b, e4b" beats "exit code 1".
    let parsed = null;
    try { parsed = JSON.parse(e.stdout || ""); } catch { /* not ours */ }
    const error = parsed?.error
      || (e.stderr || e.message || "failed").toString().trim().slice(0, 400);
    return { ok: false, error, hint: hint(error, box) };
  }
}

export async function GET() {
  const boxes = await Promise.all(HOSTS.map(async (h) => {
    const r = await ctl(h, "--status");
    return r.ok ? { ...h, ok: true, ...r.data }
                : { ...h, ok: false, error: r.error, hint: r.hint, jobs: [] };
  }));
  return Response.json({ ts: Date.now(), boxes });
}

export async function POST(request) {
  const { searchParams } = new URL(request.url);
  const preflight = searchParams.get("preflight") === "1";
  const body = await request.json().catch(() => null);
  const box = byId(body?.box);
  if (!box || !body?.kind) {
    return Response.json({ error: "bad box or kind" }, { status: 400 });
  }
  const payload = JSON.stringify({
    kind: body.kind, params: body.params || {},
    not_before: body.not_before || null, by: "dashboard",
  });
  const r = await ctl(box, `${preflight ? "--preflight" : "--add"} ${shq(payload)}`);
  return r.ok ? Response.json(r.data)
              : Response.json({ error: r.error, hint: r.hint }, { status: 400 });
}

export async function DELETE(request) {
  const { searchParams } = new URL(request.url);
  const box = byId(searchParams.get("box"));
  const job = searchParams.get("job");
  if (!box || !job || !/^[\w.-]+$/.test(job)) {
    return Response.json({ error: "bad box or job" }, { status: 400 });
  }
  const r = await ctl(box, `--cancel ${job}`);
  return r.ok ? Response.json(r.data)
              : Response.json({ error: r.error }, { status: 400 });
}
```

- [ ] **Step 2: Write the logs route**

Create `dashboard/app/api/logs/route.js`:

```js
import { exec } from "node:child_process";
import { promisify } from "node:util";
import { byId, SSH, hint } from "../../lib/hosts";

const run = promisify(exec);

export const dynamic = "force-dynamic";

const STREAMS = new Set(["command", "lm_eval", "server"]);

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const box = byId(searchParams.get("box"));
  const job = searchParams.get("job");
  const stream = searchParams.get("stream");
  const from = Number.parseInt(searchParams.get("from") || "0", 10) || 0;

  if (!box || !job || !/^[\w.-]+$/.test(job) || !STREAMS.has(stream)) {
    return Response.json({ error: "bad box, job or stream" }, { status: 400 });
  }

  // Offset-based: a three-hour lm_eval.log is not re-sent on every poll.
  const cmd = `ssh ${SSH} ${box.host} '${box.py} ${box.repo}/benchmark/queue_ctl.py `
            + `--log ${job} --stream ${stream} --from ${from}'`;
  try {
    const { stdout } = await run(cmd, { timeout: 30000, maxBuffer: 16 * 1024 * 1024 });
    return Response.json(JSON.parse(stdout));
  } catch (e) {
    let parsed = null;
    try { parsed = JSON.parse(e.stdout || ""); } catch { /* not ours */ }
    const error = parsed?.error
      || (e.stderr || e.message || "failed").toString().trim().slice(0, 300);
    return Response.json({ error, hint: hint(error, box) }, { status: 502 });
  }
}
```

- [ ] **Step 3: Verify both routes against the real boards**

```bash
cd dashboard && npm run dev
curl -s localhost:3939/api/queue | head -c 400
curl -s -X POST localhost:3939/api/queue?preflight=1 \
  -H 'content-type: application/json' \
  -d '{"box":"jetson","kind":"mmlupro","params":{"model":"e4b","subset":"s2"}}' | head -c 400
```

Expected: `/api/queue` lists both boards with `daemon_alive: true`; the
preflight returns `resolved` and a `prechecks` array.

- [ ] **Step 4: Verify a bad parameter surfaces the device's own message**

```bash
curl -s -X POST localhost:3939/api/queue -H 'content-type: application/json' \
  -d '{"box":"jetson","kind":"mmlupro","params":{"model":"e9b","subset":"s2"}}'
```

Expected: HTTP 400 with `"e9b is not one of e2b, e4b"` — not "exit code 1".

- [ ] **Step 5: Commit**

```bash
git add dashboard/app/api/queue dashboard/app/api/logs
git commit -m "Expose the queue to the browser through queue_ctl alone"
```

---

## Task 12: Teach `plan.js` the queue and thinking runs

**Files:**
- Modify: `dashboard/app/lib/plan.js`

**Interfaces:**
- Consumes: the `jobs` array from `GET /api/queue` (Task 11)
- Produces:
  - `PLAN` gains `thinking: ["off", "on"]`
  - `RUN_RE` matches an optional `-think` suffix
  - `cell(box, model, subset, thinking = "off", queue = null)` — prefers the
    queue's authoritative state, falling back to the process heuristic

**Two bugs this fixes.** `RUN_RE` is anchored
`/^mmlupro100-(e2b|e4b)(?:-(s\d))?$/i` with no `-think` branch, so the first
thinking-on run will complete and not appear in the matrix. And `cell()` infers
"running" from process names, which its own comment admits is fragile; with a
queue there is a real answer.

- [ ] **Step 1: Write the failing test**

Create `dashboard/app/lib/plan.test.mjs`:

```js
// Run with: node --test dashboard/app/lib/plan.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { cell, PLAN } from "./plan.js";

const doneBox = (run, at = "2026-09-21 10:00") => ({
  data: { procs: {}, completed: [{ task: "mmlu_pro", run, score: 66, stderr: 4.7, at }] },
});

test("plan covers both thinking conditions", () => {
  assert.deepEqual(PLAN.thinking, ["off", "on"]);
});

test("a thinking-on run is matched to its cell", () => {
  const box = doneBox("mmlupro100-e4b-s2-think");
  assert.equal(cell(box, "e4b", "s2", "on").status, "done");
});

test("a thinking-on run does not fill the thinking-off cell", () => {
  const box = doneBox("mmlupro100-e4b-s2-think");
  assert.equal(cell(box, "e4b", "s2", "off").status, "pending");
});

test("a baseline run does not fill the thinking-on cell", () => {
  const box = doneBox("mmlupro100-e4b-s2");
  assert.equal(cell(box, "e4b", "s2", "on").status, "pending");
});

test("the queue is authoritative about what is running", () => {
  const box = { data: { procs: {}, completed: [] } };
  const queue = { jobs: [{ state: "running", output_dir: "mmlupro100-e4b-s2", id: "j1" }] };
  const c = cell(box, "e4b", "s2", "off", queue);
  assert.equal(c.status, "running");
  assert.equal(c.job, "j1");
});

test("a blocked job is shown as blocked, not pending", () => {
  const box = { data: { procs: {}, completed: [] } };
  const queue = { jobs: [{ state: "blocked", output_dir: "mmlupro100-e4b-s2",
                           id: "j1", note: "reasoning: expected off, got None" }] };
  const c = cell(box, "e4b", "s2", "off", queue);
  assert.equal(c.status, "blocked");
  assert.match(c.note, /reasoning/);
});

test("without a queue the process heuristic still works", () => {
  const box = {
    data: { procs: { lm_eval: 1 },
            progress: { run: "mmlupro100-e4b-s2", pct: 41, eta: "1h 2m" },
            completed: [] },
  };
  assert.equal(cell(box, "e4b", "s2", "off").status, "running");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test dashboard/app/lib/plan.test.mjs`
Expected: FAIL — `PLAN.thinking` is undefined

- [ ] **Step 3: Write minimal implementation**

In `dashboard/app/lib/plan.js`, replace `PLAN`, `RUN_RE`, `matches` and `cell`:

```js
// The experiment queue, so the matrix can show what is done, running and pending.
// Subsets are disjoint 100-question MMLU-Pro samples (seeds 20260918/19/20).
export const PLAN = { models: ["e2b", "e4b"], subsets: ["s1", "s2", "s3"],
                      thinking: ["off", "on"] };

// Run directories are mmlupro100-<model> (an early run, implicitly s1) or
// mmlupro100-<model>-<subset>, with -think appended for the reasoning row
// (std_mmlupro.sh sets OUT=$OUT-think). Anything else — a smoke test, a .bak —
// must not be matched into a cell, so the pattern stays anchored.
const RUN_RE = /^mmlupro100-(e2b|e4b)(?:-(s\d))?(-think)?$/i;
const matches = (name, model, subset, thinking = "off") => {
  const m = RUN_RE.exec((name || "").trim());
  if (!m) return false;
  return m[1].toLowerCase() === model
      && (m[2] || "s1").toLowerCase() === subset
      && (m[3] ? "on" : "off") === thinking;
};

export function cell(box, model, subset, thinking = "off", queue = null) {
  const d = box?.data;

  // The queue knows what it started; ask it before guessing. Without a daemon
  // (an older board, or one where the unit is down) fall through to the
  // process heuristic below so the matrix still renders.
  const job = (queue?.jobs || []).find(
    (j) => matches(j.output_dir, model, subset, thinking)
        && ["queued", "prechecking", "fingerprinting", "running", "blocked"].includes(j.state));
  if (job) {
    if (job.state === "blocked") {
      return { status: "blocked", job: job.id, note: job.note, run: job.output_dir };
    }
    if (job.state === "queued") {
      return { status: "queued", job: job.id, run: job.output_dir,
               notBefore: job.not_before_epoch };
    }
    return { status: "running", job: job.id, run: job.output_dir,
             pct: d?.progress && matches(d.progress.run, model, subset, thinking)
                  ? d.progress.pct : null,
             eta: d?.progress?.eta };
  }

  if (!d) return { status: "unknown" };

  // progress comes from parsing the newest lm_eval.log, which keeps reading
  // 100/100 long after the run ended — so it only means "running" while the
  // box actually has the processes to match.
  const procs = d.procs || {};
  const live = procs.lm_eval || procs.run_measured || procs.telemetry;
  if (live && d.progress && matches(d.progress.run, model, subset, thinking)) {
    return { status: "running", pct: d.progress.pct, eta: d.progress.eta,
             run: d.progress.run };
  }
  const done = (d.completed || []).find(
    (c) => c.task === "mmlu_pro" && matches(c.run, model, subset, thinking));
  if (!done) return { status: "pending" };
  return { status: done.at >= BATCH_START ? "done" : "prior", run: done.run,
           score: done.score, stderr: done.stderr, minutes: done.minutes, at: done.at };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test dashboard/app/lib/plan.test.mjs`
Expected: PASS, 7 tests

- [ ] **Step 5: Check the existing matrix still renders**

`app/page.js` calls `cell(box, m, s)` with three arguments. The new parameters
default, so baseline cells are unchanged. Open http://localhost:3939 and confirm
the matrix shows the same six scores as before.

- [ ] **Step 6: Commit**

```bash
git add dashboard/app/lib/plan.js dashboard/app/lib/plan.test.mjs
git commit -m "Let the matrix see thinking runs, and ask the queue what is live"
```

---

## Task 13: The queue page

**Files:**
- Create: `dashboard/app/queue/page.js`
- Modify: `dashboard/app/globals.css` (append the queue styles)

**Interfaces:**
- Consumes: `GET/POST/DELETE /api/queue` (Task 11)
- Produces: a page at `/queue`; no exports other than the default component

- [ ] **Step 1: Write the page**

Create `dashboard/app/queue/page.js`:

```jsx
"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

const POLL_MS = 5000;

const fmtTime = (epoch) =>
  epoch ? new Date(epoch * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : null;

function JobForm({ box, onQueued }) {
  const kinds = box.kinds || {};
  const [kind, setKind] = useState("mmlupro");
  const [params, setParams] = useState({});
  const [notBefore, setNotBefore] = useState("");
  const [pre, setPre] = useState(null);
  const [busy, setBusy] = useState(false);

  const spec = kinds[kind];

  // Reset parameters to each kind's defaults when the kind changes, so the
  // form can never post a leftover parameter the new kind does not declare.
  useEffect(() => {
    if (!spec) return;
    const next = {};
    for (const [name, rule] of Object.entries(spec.params)) {
      next[name] = rule.default ?? rule.enum?.[0] ?? "";
    }
    setParams(next);
    setPre(null);
  }, [kind, box.id]);                       // eslint-disable-line react-hooks/exhaustive-deps

  const send = useCallback(async (preflight) => {
    setBusy(true);
    try {
      const res = await fetch(`/api/queue${preflight ? "?preflight=1" : ""}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ box: box.id, kind, params,
                               not_before: notBefore || null }),
      });
      const data = await res.json();
      if (!res.ok) { setPre({ error: data.error, hint: data.hint }); return; }
      if (preflight) setPre(data);
      else { setPre(null); onQueued(); }
    } finally { setBusy(false); }
  }, [box.id, kind, params, notBefore, onQueued]);

  // Preflight on every change: the answer is cheap and the point is to see the
  // memory and stale-directory checks before committing three hours.
  useEffect(() => {
    if (!spec || !Object.keys(params).length) return;
    const t = setTimeout(() => send(true), 250);
    return () => clearTimeout(t);
  }, [params, notBefore]);                  // eslint-disable-line react-hooks/exhaustive-deps

  if (!spec) return <p className="sub">This board reported no job kinds.</p>;

  return (
    <div className="jobform">
      <label>kind
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {Object.keys(kinds).map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </label>

      {Object.entries(spec.params).map(([name, rule]) => (
        <label key={name}>{name}
          {rule.enum ? (
            <select value={params[name] ?? ""}
                    onChange={(e) => setParams({ ...params, [name]: e.target.value })}>
              {rule.enum.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          ) : (
            <input value={params[name] ?? ""} placeholder={rule.pattern ? "letters, digits, . _ -" : ""}
                   onChange={(e) => setParams({ ...params, [name]: e.target.value })} />
          )}
        </label>
      ))}

      <label>not before
        <input value={notBefore} placeholder="HH:MM" size={6}
               onChange={(e) => setNotBefore(e.target.value)} />
        <i className="sub"> {box.timezone} (board time)</i>
      </label>

      {pre?.error && (
        <p className="pre-error"><b>{pre.error}</b>{pre.hint ? <><br />{pre.hint}</> : null}</p>
      )}

      {pre?.prechecks && (
        <ul className="prechecks">
          {pre.prechecks.map((c) => (
            <li key={c.name} className={c.ok ? "ok" : "bad"}>
              <b>{c.ok ? "✓" : "✗"} {c.name}</b> {c.detail}
            </li>
          ))}
        </ul>
      )}

      {pre?.resolved && (
        <pre className="resolved">{pre.resolved.command}</pre>
      )}

      <button type="button" disabled={busy || (pre && pre.ok === false)}
              onClick={() => send(false)}>
        {pre && pre.ok === false ? "prechecks failed" : "queue this run"}
      </button>
    </div>
  );
}

function QueueList({ box, onChange }) {
  const cancel = async (id) => {
    await fetch(`/api/queue?box=${box.id}&job=${id}`, { method: "DELETE" });
    onChange();
  };
  const jobs = (box.jobs || []).filter((j) => j.state !== "cancelled");
  if (!jobs.length) return <p className="sub">Nothing queued.</p>;
  return (
    <table className="queue-table">
      <thead><tr><th>job</th><th>state</th><th>when</th><th /></tr></thead>
      <tbody>
        {jobs.slice().reverse().map((j) => (
          <tr key={j.id} className={`state-${j.state}`}>
            <td>
              <Link href={`/queue/${box.id}/${j.id}`}>{j.label}</Link>
              {j.note ? <i className="note"> {j.note}</i> : null}
            </td>
            <td>{j.state}</td>
            <td>{fmtTime(j.started || j.not_before_epoch || j.created) || "—"}</td>
            <td>{j.state === "queued"
              ? <button type="button" onClick={() => cancel(j.id)}>cancel</button>
              : null}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function QueuePage() {
  const [boxes, setBoxes] = useState([]);
  const load = useCallback(async () => {
    const res = await fetch("/api/queue");
    const data = await res.json();
    setBoxes(data.boxes || []);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  return (
    <main>
      <header className="card-head">
        <h2>Queue</h2>
        <p className="sub">
          One job per board at a time. Each run is prechecked for memory and a
          stale output directory, and its serving flags are diffed against the
          declared baseline before lm-eval starts.{" "}
          <Link href="/">← live monitor</Link>
        </p>
      </header>

      {boxes.map((box) => (
        <section key={box.id} className="card">
          <div className="card-head">
            <h3>{box.label}</h3>
            {box.ok
              ? <p className="sub">{box.daemon_alive
                  ? "queue daemon running" : "⚠ queue daemon is not running"}</p>
              : <p className="pre-error"><b>{box.error}</b>{box.hint ? <><br />{box.hint}</> : null}</p>}
          </div>
          {box.ok && <JobForm box={box} onQueued={load} />}
          {box.ok && <QueueList box={box} onChange={load} />}
        </section>
      ))}
    </main>
  );
}
```

- [ ] **Step 2: Append the styles**

Add to the end of `dashboard/app/globals.css`:

```css
/* ---- queue page ---- */
.jobform { display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-end;
           padding: 0 1rem 1rem; }
.jobform label { display: flex; flex-direction: column; gap: .25rem;
                 font-size: .8rem; text-transform: lowercase; opacity: .85; }
.jobform select, .jobform input { padding: .35rem .5rem; font: inherit; }
.jobform button { padding: .45rem 1rem; font: inherit; cursor: pointer; }
.jobform button:disabled { opacity: .5; cursor: not-allowed; }

.prechecks { flex-basis: 100%; list-style: none; margin: 0; padding: 0;
             font-size: .8rem; }
.prechecks li { padding: .15rem 0; }
.prechecks li.ok b { color: #3fa45b; }
.prechecks li.bad b { color: #d14; }

.resolved { flex-basis: 100%; margin: 0; padding: .5rem .75rem; font-size: .75rem;
            background: rgba(127,127,127,.12); border-radius: 4px;
            white-space: pre-wrap; word-break: break-all; }
.pre-error { flex-basis: 100%; color: #d14; font-size: .85rem; margin: 0; }

.queue-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
.queue-table th, .queue-table td { padding: .4rem .75rem; text-align: left;
                                   border-top: 1px solid rgba(127,127,127,.2); }
.queue-table .note { opacity: .7; font-size: .78rem; }
.state-running td { background: rgba(60,120,220,.12); }
.state-blocked td { background: rgba(221,17,68,.12); }
.state-failed td  { background: rgba(221,17,68,.08); }
.state-completed td { background: rgba(63,164,91,.10); }
```

- [ ] **Step 3: Verify in the browser**

Open http://localhost:3939/queue. Expected: both boards, each showing "queue
daemon running", a form defaulting to `mmlupro`/`e2b`/`s1`/`off`, and a live
preflight panel listing four checks. Change subset to one whose output
directory already exists — the stale-directory check must go red and the queue
button must disable.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app/queue dashboard/app/globals.css
git commit -m "Compose a run in the browser, and see the checks before committing hours"
```

---

## Task 14: Job detail — timeline, fingerprint diff, logs

**Files:**
- Create: `dashboard/app/queue/[box]/[job]/page.js`
- Modify: `dashboard/app/globals.css` (append)

**Interfaces:**
- Consumes: `GET /api/queue` (Task 11), `GET /api/logs` (Task 11)
- Produces: a page at `/queue/<box>/<job>`

- [ ] **Step 1: Write the page**

Create `dashboard/app/queue/[box]/[job]/page.js`:

```jsx
"use client";
import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

const POLL_MS = 5000;
const STREAMS = ["lm_eval", "server", "command"];

const ts = (t) => new Date(t * 1000).toLocaleTimeString([], {
  hour: "2-digit", minute: "2-digit", second: "2-digit" });

function Fingerprint({ fp }) {
  if (!fp) return null;
  return (
    <div className={`fingerprint ${fp.agrees ? "ok" : "drift"}`}>
      <h4>Fingerprint {fp.agrees ? "✓ matches baseline" : "⚠ drift"}
        <i> {fp.baseline}</i></h4>
      <table>
        <tbody>
          {fp.diff.map((r) => (
            <tr key={r.key} className={r.ok ? "ok" : "bad"}>
              <td>{r.key}</td>
              <td>{r.ok ? "✓" : "✗"}</td>
              <td>{String(r.actual ?? "MISSING")}</td>
              <td className="sub">expected {String(r.expected)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <pre className="resolved">{fp.captured?.server_args || "(no server was running)"}</pre>
    </div>
  );
}

function LogTab({ box, job, stream, active }) {
  const [text, setText] = useState("");
  const offset = useRef(0);
  const pre = useRef(null);

  useEffect(() => { offset.current = 0; setText(""); }, [stream, job]);

  useEffect(() => {
    if (!active) return undefined;
    let stop = false;
    const tick = async () => {
      const res = await fetch(
        `/api/logs?box=${box}&job=${job}&stream=${stream}&from=${offset.current}`);
      const data = await res.json();
      if (stop) return;
      if (data.error) { setText((t) => t || `— ${data.error}`); return; }
      if (data.text) {
        offset.current = data.offset;
        setText((t) => (t + data.text).slice(-200000));
        if (pre.current) pre.current.scrollTop = pre.current.scrollHeight;
      }
    };
    tick();
    const t = setInterval(tick, POLL_MS);
    return () => { stop = true; clearInterval(t); };
  }, [box, job, stream, active]);

  if (!active) return null;
  return <pre className="logview" ref={pre}>{text || "— empty —"}</pre>;
}

export default function JobDetail({ params }) {
  const { box: boxId, job: jobId } = use(params);
  const [box, setBox] = useState(null);
  const [stream, setStream] = useState("lm_eval");

  const load = useCallback(async () => {
    const res = await fetch("/api/queue");
    const data = await res.json();
    setBox((data.boxes || []).find((b) => b.id === boxId) || null);
  }, [boxId]);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  const job = (box?.jobs || []).find((j) => j.id === jobId);
  const evts = (box?.events || []).filter((e) => e.job === jobId);
  const fp = job?.fingerprint;

  if (!box) return <main><p className="sub">Loading…</p></main>;
  if (!job) return <main><p className="sub">No job {jobId} on {box.label}. <Link href="/queue">← queue</Link></p></main>;

  return (
    <main>
      <header className="card-head">
        <h2>{job.label} <i className={`state-pill state-${job.state}`}>{job.state}</i></h2>
        <p className="sub">{box.label} · {job.kind} ·{" "}
          {Object.entries(job.params).map(([k, v]) => `${k}=${v}`).join(" ")}{" "}
          <Link href="/queue">← queue</Link></p>
        {job.override_fingerprint && (
          <p className="pre-error">
            This run was started with a fingerprint override. It is not
            comparable to runs that matched the baseline.
          </p>
        )}
      </header>

      <section className="card">
        <div className="card-head"><h3>Timeline</h3></div>
        <ul className="timeline">
          {evts.map((e, i) => (
            <li key={i}><b>{ts(e.ts)}</b> {e.event}
              {e.detail ? <i> — {e.detail}</i> : null}</li>
          ))}
          {!evts.length && <li className="sub">No events recorded yet.</li>}
        </ul>
      </section>

      {fp && <section className="card"><Fingerprint fp={fp} /></section>}

      <section className="card">
        <div className="card-head">
          <h3>Logs</h3>
          <div className="tabs">
            {STREAMS.map((s) => (
              <button key={s} type="button"
                      className={s === stream ? "on" : ""}
                      onClick={() => setStream(s)}>{s}</button>
            ))}
          </div>
        </div>
        {STREAMS.map((s) => (
          <LogTab key={s} box={boxId} job={jobId} stream={s} active={s === stream} />
        ))}
      </section>
    </main>
  );
}
```

- [ ] **Step 2: Have `--status` include each job's fingerprint**

The page reads `job.fingerprint`, which `queue_ctl.py --status` does not yet
send. In `benchmark/queue_ctl.py`, replace the `--status` branch:

```python
    if args.status:
        recent, offset = events.read(p, offset=args.offset)
        jobs = store.load(p)["jobs"]
        # The detail page renders the fingerprint diff, so ship it with the job
        # rather than making the browser fetch one file per job.
        for j in jobs:
            for name, key in (("fingerprint.json", "fingerprint"),
                              ("precheck.json", "prechecks")):
                try:
                    with open(os.path.join(p.job_dir(j["id"]), name)) as f:
                        j[key] = json.load(f)
                except (OSError, ValueError):
                    j[key] = None
        ok({"board": p.board, "jobs": jobs,
            "active": store.active(p), "daemon_alive": daemon_alive(p),
            "events": recent, "offset": offset, "ts": time.time()})
```

- [ ] **Step 3: Add a test for the enriched status**

Append to `benchmark/tests/test_queue_ctl.py`:

```python
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
```

Run: `cd benchmark && python3 -m unittest tests.test_queue_ctl -v`
Expected: PASS, 14 tests

- [ ] **Step 4: Append the styles**

Add to the end of `dashboard/app/globals.css`:

```css
/* ---- job detail ---- */
.timeline { list-style: none; margin: 0; padding: 0 1rem 1rem; font-size: .85rem; }
.timeline li { padding: .2rem 0; }
.timeline b { font-variant-numeric: tabular-nums; opacity: .7; margin-right: .5rem; }
.timeline i { opacity: .75; }

.fingerprint { padding: 0 1rem 1rem; }
.fingerprint h4 { margin: .75rem 0 .5rem; }
.fingerprint h4 i { font-weight: normal; opacity: .6; font-size: .8rem; }
.fingerprint table { border-collapse: collapse; font-size: .82rem; width: 100%; }
.fingerprint td { padding: .2rem .5rem; border-top: 1px solid rgba(127,127,127,.15); }
.fingerprint tr.bad { color: #d14; }
.fingerprint tr.ok td:nth-child(2) { color: #3fa45b; }
.fingerprint.drift { border-left: 3px solid #d14; }

.tabs button { font: inherit; padding: .25rem .7rem; cursor: pointer;
               background: none; border: 1px solid rgba(127,127,127,.3);
               border-radius: 4px; margin-left: .25rem; }
.tabs button.on { background: rgba(127,127,127,.2); }

.logview { margin: 0 1rem 1rem; padding: .75rem; max-height: 60vh; overflow: auto;
           font-size: .75rem; line-height: 1.45; white-space: pre-wrap;
           background: rgba(127,127,127,.10); border-radius: 4px; }

.state-pill { font-style: normal; font-size: .7rem; padding: .1rem .5rem;
              border-radius: 999px; vertical-align: middle;
              background: rgba(127,127,127,.2); }
```

- [ ] **Step 5: Verify in the browser**

Queue a `raw` job that fails fast (`{"label":"smoke","command":"false"}`), let
the daemon pick it up, then open its detail page. Expected: the timeline shows
`queued → precheck_passed → started → failed`, the failure says
`no .done marker`, and the `command` log tab renders.

- [ ] **Step 6: Commit**

```bash
git add dashboard/app/queue benchmark/queue_ctl.py benchmark/tests/test_queue_ctl.py dashboard/app/globals.css
git commit -m "Show each job's timeline, flag diff and logs in one place"
```

---

## Task 15: Daemon liveness in the preflight script

**Files:**
- Modify: `dashboard/scripts/check-ssh.mjs`

**Interfaces:**
- Consumes: `queue_ctl.py --describe` (Task 8)
- Produces: one more per-board check in `npm run check`

- [ ] **Step 1: Read the existing checks**

Run: `sed -n '1,76p' dashboard/scripts/check-ssh.mjs`

Match the existing style exactly — every failure there prints the command that
fixes it, and the new check must do the same.

- [ ] **Step 2: Add the check**

Add a per-board check that runs `queue_ctl.py --describe` and parses it, and
reports the daemon's state. Follow the file's existing per-check shape; the
failure hint must be the installer command:

```js
// The queue daemon is what makes a run survive this Mac going to sleep, so a
// dead one is worth catching here rather than when a job silently never starts.
{
  name: "queue daemon",
  cmd: (h) => `${h.py} ${h.repo}/benchmark/queue_ctl.py --status`,
  check: (stdout) => {
    const { daemon_alive: alive } = JSON.parse(stdout);
    return alive ? null : "the queue daemon is not running";
  },
  fix: (h) => `ssh ${h.host} 'cd ${h.repo} && ./benchmark/install_queue.sh'`,
}
```

- [ ] **Step 3: Verify**

Run: `cd dashboard && npm run check`
Expected: every board green, including "queue daemon".

Then stop one and confirm the failure is actionable:

```bash
ssh MITLAB-JETSON 'systemctl --user stop agentic-queue'
cd dashboard && npm run check
ssh MITLAB-JETSON 'systemctl --user start agentic-queue'
```

Expected: the Jetson's "queue daemon" check fails and prints the
`install_queue.sh` command.

- [ ] **Step 4: Commit**

```bash
git add dashboard/scripts/check-ssh.mjs
git commit -m "Catch a dead queue daemon in the preflight, not at 2am"
```

---

## Task 16: End-to-end on both boards

**Files:** none — this is the acceptance run.

- [ ] **Step 1: Full suite on both boards**

```bash
ssh MITLAB-EDGE   'cd ~/Research/agentic-edge/benchmark && python3 -m unittest discover -s tests'
ssh MITLAB-JETSON 'cd ~/research/agentic-edge/benchmark && python3 -m unittest discover -s tests'
```

Expected: OK on both. Board-specific bugs have been the norm (AGENTS §7).

- [ ] **Step 2: Confirm the fingerprint blocks a genuinely wrong config**

Queue a `raw` job whose command starts a server without `-rea`, and confirm the
daemon refuses it. This is the 2026-09-22 regression, live:

```bash
curl -s -X POST localhost:3939/api/queue -H 'content-type: application/json' \
  -d '{"box":"jetson","kind":"raw","params":{"label":"drift-check","command":"true"}}'
```

Expected: `raw` declares no baseline, so it runs. Then queue a real `mmlupro`
job while a deliberately mis-flagged server is up and confirm the job goes to
`blocked` with `reasoning: expected off, got None` — and that nothing executed.

- [ ] **Step 3: One real short run end to end**

Queue `mmlupro` for a subset with no existing output directory on the Jetson,
watch it move `queued → prechecking → fingerprinting → running → completed`,
and confirm afterwards:

```bash
ssh MITLAB-JETSON 'python3 -c "
import json; p=\"$HOME/research/queue/jobs\"
import os
j=sorted(os.listdir(p))[-1]
print(json.load(open(os.path.join(p,j,\"fingerprint.json\")))[\"agrees\"])"'
```

Expected: `True`, and `meta.json` for that run now has a non-empty
`server_args_after` — the field that was blank for all nine previous Jetson runs.

- [ ] **Step 4: Update the docs**

- `AGENTS.md` §3: add the queue to "Running things".
- `AGENTS.md` §1: add `jobqueue/`, `queue_ctl.py`, `queue_runner.py`,
  `job_kinds.json`, `baselines.json` to the layout.
- `AGENTS.md` §10: the `meta.json` caveat can now say `server_args_after` is
  the honest field.
- `dashboard/README.md`: document `/queue`.

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md dashboard/README.md
git commit -m "Document the queue in the places people actually read"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §2 architecture, ssh boundary | 8, 11 |
| §3 on-device layout, job lifecycle | 1, 2, 3 |
| §4 job kinds, label vs output_dir, SRVLOG | 4 |
| §5 prechecks | 5 |
| §5 fingerprint, baselines, override policy | 6, 7 |
| §5 `run_measured.sh` second capture | 10 |
| §6 API routes | 11 |
| §6 `plan.js` authoritative state + `-think` | 12 |
| §6 queue page, job detail | 13, 14 |
| §6 `check-ssh.mjs` | 15 |
| §7 supervision | 9 |
| §8 failure behaviour | 2 (atomic/flock), 7 (`.done`, exec failure), 9 (crash tolerance) |
| §9 testing, both boards | every task; 9 and 16 run on hardware |
| §10 scheduling FIFO + not-before | 2 (`next_eligible`), 8 (`parse_not_before`) |
| §10 Task 0 efficiency track | 0 |

**Not covered, deliberately:** the SSE stream from the spec's Task 0 note. The
queue page and job detail both poll at 5s like the existing dashboard; SSE is a
change to `/api/status` that belongs with the efficiency track, not here.
Multiplexing (Task 0 step 1) is what makes that polling cheap.

**Type consistency:** `resolve()` returns `label`, `output_dir`, `command`,
`env`, `baseline`, `memory_mb` — consumed with those names in `prechecks`
(Task 5), `runner` (Task 7) and `queue_ctl` (Task 8). `Paths` properties are
used identically in Tasks 2, 3, 5, 7, 8. `cell()`'s new signature
`(box, model, subset, thinking, queue)` defaults its new parameters, so
`app/page.js`'s existing three-argument calls keep working (Task 12 step 5).
