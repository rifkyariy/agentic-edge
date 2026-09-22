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
