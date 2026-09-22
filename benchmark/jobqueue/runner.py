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
