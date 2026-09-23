#!/usr/bin/env python3
"""The queue daemon. One per board, supervised by a systemd user unit.

    queue_runner.py --daemon      run until stopped
    queue_runner.py --once        one tick, then exit (smoke test)

Stdlib only (AGENTS §7). Everything interesting lives in jobqueue/runner.py;
this file is the process wrapper around it.
"""
import argparse
import glob
import hashlib
import json
import os
import signal
import sys
import time

from jobqueue import fingerprint, kinds, paths, runner, store

POLL_SECONDS = 5


def code_stamp(bench=None):
    """A hash of the files this daemon has loaded. deploy.sh replaces them;
    the daemon notices between jobs and reloads itself, so a deploy never has
    to restart it mid-run. Content, not mtime: rsync -a carries the Mac's
    mtimes, which can be older than what was on the board."""
    bench = bench or paths.bench_dir()
    files = sorted([os.path.join(bench, n) for n in
                    ("queue_runner.py", "job_kinds.json", "baselines.json")]
                   + glob.glob(os.path.join(bench, "jobqueue", "*.py")))
    h = hashlib.sha1()
    for f in files:
        try:
            with open(f, "rb") as fh:
                h.update(f.encode() + b"\0" + fh.read())
        except OSError:
            pass
    return h.hexdigest()


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
    loaded = code_stamp()
    # What this process is running, for deploy.sh: the file on disk can be
    # newer than the code a daemon loaded, so only the daemon can say.
    with open(os.path.join(p.queue_dir, "daemon.json"), "w") as f:
        json.dump({"pid": os.getpid(), "code": loaded, "self_reload": True,
                   "started": time.time()}, f)

    # A job the previous daemon left active: follow it to its end, or judge
    # it now if its process is gone. The unit uses KillMode=process, so a
    # restart stops only this daemon, never the run it started.
    try:
        adopted = r.recover()
        if adopted:
            print("queue_runner: recovered job %s" % adopted, flush=True)
    except Exception as exc:                          # noqa: BLE001
        print("queue_runner: recovery failed: %r" % (exc,), file=sys.stderr, flush=True)

    def stop(signum, frame):
        # A running job is left alone: KillMode=process means systemd stops
        # only this process, and the next daemon adopts the run by its pid.
        stopping["now"] = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    print("queue_runner: watching %s on %s" % (p.queue_dir, p.board), flush=True)
    while not stopping["now"]:
        # Only between jobs: tick() blocks for the whole of a run.
        if store.active(p) is None and code_stamp() != loaded:
            print("queue_runner: code changed on disk; reloading", flush=True)
            os.execv(sys.executable, [sys.executable] + sys.argv)
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
