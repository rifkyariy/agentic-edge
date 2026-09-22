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
