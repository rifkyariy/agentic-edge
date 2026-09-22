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
