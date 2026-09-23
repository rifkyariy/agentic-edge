#!/usr/bin/env python3
"""The one thing the dashboard runs over ssh.

Every subcommand prints a single JSON object and exits 0, or prints
{"error": "..."} and exits 1. AGENTS §7: work the dashboard needs from a device
goes through a device-side script, not an ad-hoc ssh command in the web app.

    queue_ctl.py --describe
    queue_ctl.py --preflight '{"kind":"mmlupro","params":{...}}'
    queue_ctl.py --add       '{"kind":"mmlupro","params":{...},"not_before":"02:00"}'
    queue_ctl.py --add       '{"jobs":[{...},{...}]}'   a batch, queued in order
                  a job may carry "override": {"checks":["memory"],"reason":"..."}
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


def deployed():
    """What deploy.sh last put here: commit, time, and whether it was clean."""
    try:
        with open(os.path.join(paths.bench_dir(), "DEPLOYED.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


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
        batch = body.get("jobs") if isinstance(body.get("jobs"), list) else [body]
        if not batch:
            fail("no jobs in the request")

        # Everything already waiting or running on this board. Each job in the
        # batch is checked against it and against the batch jobs before it, so
        # a batch cannot queue the same run twice either.
        pending = [j for j in store.load(p)["jobs"]
                   if j["state"] == "queued" or j["state"] in store.ACTIVE]
        ahead = next((j["label"] for j in pending if j["state"] in store.ACTIVE),
                     pending[-1]["label"] if pending else None)

        plans = []
        for item in batch:
            try:
                resolved = resolve_request(registry, p, item)
                override = prechecks.validate_override(item.get("override"))
            except (kinds.ValidationError, ValueError) as exc:
                fail(exc)
            checks = prechecks.run_all(p, resolved, pending=list(pending), ahead=ahead)
            left = prechecks.blocking(checks, override)
            plans.append({"item": item, "resolved": resolved, "prechecks": checks,
                          "override": override, "ok": not left,
                          "blocking": [c["name"] for c in left]})
            pending.append({"id": "(this batch)", "state": "queued",
                            "output_dir": resolved["output_dir"],
                            "label": resolved["label"]})
            ahead = resolved["label"]

        if args.preflight:
            if "jobs" in body:
                ok({"results": plans, "ok": all(x["ok"] for x in plans)})
            x = plans[0]
            ok({"resolved": x["resolved"], "prechecks": x["prechecks"],
                "ok": x["ok"], "blocking": x["blocking"]})

        # --add enforces what the form shows. Before, it queued anything and
        # left the refusal to the runner, hours later.
        refused = [x for x in plans if not x["ok"]]
        if refused:
            fail("; ".join("%s: %s" % (x["resolved"]["label"], ", ".join(
                c["detail"] for c in x["prechecks"] if c["name"] in x["blocking"]))
                for x in refused))

        added = []
        for x in plans:
            item, resolved = x["item"], x["resolved"]
            not_before = None
            if item.get("not_before"):
                try:
                    not_before = parse_not_before(item["not_before"])
                except ValueError as exc:
                    fail(exc)
            job = store.new_job(
                kind=item["kind"], params=resolved["params"],
                label=resolved["label"], output_dir=resolved["output_dir"],
                command=resolved["command"], env=resolved["env"],
                not_before_epoch=not_before)
            if x["override"]:
                job["override_prechecks"] = dict(x["override"],
                                                 by=item.get("by", "queue_ctl"))
            job = store.add(p, job)
            events.emit(p, job["id"], "queued", by=item.get("by", "queue_ctl"),
                        label=job["label"])
            if x["override"]:
                # Recorded at queue time as well as when it takes effect: the
                # decision was made here, by whoever queued it.
                events.emit(p, job["id"], "precheck_override_requested",
                            checks=x["override"]["checks"],
                            reason=x["override"]["reason"])
            added.append(job)
        if "jobs" in body:
            ok({"jobs": added})
        ok({"job": added[0]})

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
            "deployed": deployed(),
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
