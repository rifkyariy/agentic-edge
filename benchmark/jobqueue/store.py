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
