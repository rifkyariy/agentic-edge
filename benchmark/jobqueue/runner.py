"""One job at a time, and the checks that gate it.

Every effect the board has on the outcome — running a command, reading memory,
reading the server's command line — arrives through an injected function, so
the whole state machine is testable on a Mac with no board attached and no
benchmark ever executed.
"""
import json
import os
import signal
import subprocess
import time

from . import events, fingerprint as fp, kinds, paths as _paths, prechecks, store


def default_start(command, env, cwd, log_path):
    """Start the wrapped command and return the process, still running.

    It is started, not run to completion, because the fingerprint has to be
    taken while it is in flight: the run script is what configures the server,
    so there is nothing truthful to read until after it has begun. See
    Runner._await_fingerprint.

    start_new_session puts it in its own process group, so killing it on drift
    takes the run script and the server it launched, not just the shell.

    shell=True is deliberate and required: the commands this runs are shell
    constructs by design -- `./run_measured.sh <label> -- env SUBSET=s2
    ./std_mmlupro_jetson.sh e4b` -- and the `raw` job kind exists precisely so a
    human can queue an arbitrary command. It is not an injection hole to close
    but the feature itself.

    What bounds it: every non-raw kind builds its command from enum-validated
    parameters (jobqueue/kinds.py), and the `label` that reaches the
    run_measured.sh wrapper is pattern-validated
    `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` for `raw` too, so no metacharacter can
    escape the wrapper into the surrounding line. Queueing at all requires
    either an ssh session on the board or the dashboard, which runs on
    localhost and authenticates with the operator's own key -- both of which
    already grant a shell. This is a single-user lab tool, and `raw` grants
    nothing its caller did not already have.
    """
    full = dict(os.environ)
    full.update(env or {})
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log = open(log_path, "a")                      # closed when the process ends
    return subprocess.Popen(command, shell=True, cwd=cwd, env=full,
                            stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)


# How long to wait for the run's own server before giving up. run_measured.sh
# records a 30s idle baseline first, and both run scripts then wait up to 300s
# (150 x 2s) for the server to answer, so the budget has to clear 330s.
FINGERPRINT_POLL_SECONDS = 5
FINGERPRINT_TIMEOUT_SECONDS = 420


class Runner:
    def __init__(self, paths, registry, baselines, start_fn=None, probe=None,
                 capture_fn=None, clock=time.time, sleep=time.sleep,
                 pids_fn=None):
        self.paths = paths
        self.registry = registry
        self.baselines = baselines
        self.start_fn = start_fn or default_start
        self.probe = probe
        self.capture_fn = capture_fn or fp.capture
        self.pids_fn = pids_fn or fp.server_pids
        self.clock = clock
        self.sleep = sleep

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

        # The run script is what configures the server, so the only truthful
        # moment to read the serving flags is after the command has started and
        # before lm-eval gets anywhere. Reading them here, up front, would
        # describe whatever the board happened to be running beforehand -- the
        # idle deployed server on the Pi, nothing at all on the Jetson -- which
        # is exactly the mistake meta.json makes and this check exists to catch.
        log_path = os.path.join(self.paths.job_dir(jid), "command.log")
        # Which servers were already up. The Pi's va-llm is always serving, so
        # without this the very first poll finds the idle deployed server
        # (-c 4096, no --cache-ram) and blocks the job for drift it never had.
        preexisting = self.pids_fn()
        store.update(self.paths, jid, state="fingerprinting", started=self.clock())
        events.emit(self.paths, jid, "started", command=job["command"])
        try:
            proc = self.start_fn(job["command"], job["env"], _paths.bench_dir(),
                                 log_path)
        except Exception as exc:                      # noqa: BLE001
            events.emit(self.paths, jid, "failed", detail=repr(exc))
            store.update(self.paths, jid, state="failed",
                         finished=self.clock(), note=repr(exc))
            return

        name, baseline = self._baseline_for(job)
        if baseline and not self._await_fingerprint(job, proc, name, baseline,
                                                    preexisting):
            return                                    # killed and marked already

        store.update(self.paths, jid, state="running")
        self._finish(job, proc, log_path)

    def _await_fingerprint(self, job, proc, name, baseline, preexisting=()):
        """Wait for the run's own server, then diff it against the baseline.

        "Own" means a llama-server that was not running before the job
        started: on the Pi the run script restarts va-llm, which gives it a
        new pid; on the Jetson there was none to begin with.

        Returns True to let the run continue, False if it was stopped. Polls
        rather than sleeping a fixed time because server load varies with the
        model and the board.
        """
        jid = job["id"]
        deadline = self.clock() + FINGERPRINT_TIMEOUT_SECONDS
        captured = None
        stale = False

        while self.clock() < deadline:
            captured = self.capture_fn()
            pids = set(captured.get("pids") or ())
            stale = bool(pids) and pids <= set(preexisting)
            if captured["server_args"] and not stale:
                break
            if proc.poll() is not None:
                # It died before serving anything. There is nothing to compare;
                # _finish judges it on the .done marker like any other failure.
                events.emit(self.paths, jid, "fingerprint_skipped",
                            detail="the command exited before a server appeared")
                return True
            self.sleep(FINGERPRINT_POLL_SECONDS)

        if not (captured and captured["server_args"]) or stale:
            note = ("no llama-server appeared within %ds, so the serving flags "
                    "could not be verified" % FINGERPRINT_TIMEOUT_SECONDS)
            if stale:
                note = ("the run never replaced the server that was already "
                        "up within %ds, so its serving flags could not be "
                        "verified" % FINGERPRINT_TIMEOUT_SECONDS)
            self._kill(proc)
            events.emit(self.paths, jid, "fingerprint_timeout", detail=note)
            store.update(self.paths, jid, state="blocked",
                         finished=self.clock(), note=note)
            return False

        rows = fp.diff(captured["flags"], baseline["flags"])
        agrees = fp.agrees(rows)
        self._write(jid, "fingerprint.json",
                    {"baseline": name, "captured": captured,
                     "diff": rows, "agrees": agrees})
        if agrees:
            events.emit(self.paths, jid, "fingerprint_ok", baseline=name)
            return True

        bad = ", ".join("%s: expected %s, got %s"
                        % (r["key"], r["expected"], r["actual"])
                        for r in rows if not r["ok"])
        if job.get("override_fingerprint"):
            # Recorded, and the job carries the mark from here on: AGENTS §5
            # reports every run, including the ones someone waved through.
            events.emit(self.paths, jid, "fingerprint_overridden", detail=bad)
            return True

        # Killed now rather than three hours from now. lm-eval has barely
        # started: the server only just finished loading.
        self._kill(proc)
        events.emit(self.paths, jid, "fingerprint_drift", detail=bad)
        store.update(self.paths, jid, state="blocked",
                     finished=self.clock(), note=bad)
        return False

    def _kill(self, proc):
        """Stop the run and the server it started. default_start gives the
        command its own process group so the whole tree goes, not just the
        shell; a stray llama-server would otherwise fail the next job's
        board_idle precheck, which is at least a visible failure."""
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (OSError, AttributeError):
            try:
                proc.kill()
            except Exception:                         # noqa: BLE001
                pass

    def _finish(self, job, proc, log_path):
        jid = job["id"]
        try:
            rc = proc.wait()
        except Exception as exc:                      # noqa: BLE001
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
            events.emit(self.paths, jid, "failed", exit_code=rc,
                        detail="no .done marker", tail=self._tail(log_path))
            store.update(self.paths, jid, state="failed", finished=self.clock(),
                         exit_code=rc, note="no .done marker at %s" % marker)

    @staticmethod
    def _tail(path, lines=20):
        try:
            with open(path) as f:
                return f.read().splitlines()[-lines:]
        except OSError:
            return []
