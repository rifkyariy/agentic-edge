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

    def _pgrep(self, pattern):
        """Pids whose command line matches. The bracketed first character
        stops the pattern matching the pgrep call itself (AGENTS §4.2)."""
        try:
            out = subprocess.run(["pgrep", "-f", pattern], capture_output=True,
                                 text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        return [int(t) for t in out.split() if t.isdigit()]

    def deployed_server_pid(self):
        """The Pi's voice agent keeps a llama-server up as va-llm, always.

        It is not a benchmark: the run script restarts it with the run's own
        flags and restores it afterwards. Counting it as busy made the Pi
        refuse every job. No such unit on the Jetson, so this is 0 there."""
        try:
            out = subprocess.run(
                ["systemctl", "show", "-p", "MainPID", "--value", "va-llm"],
                capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return 0
        return int(out) if out.isdigit() else 0

    def reclaimable_mb(self):
        """Memory the run frees by restarting the deployed server.

        Only RssAnon: the model's file-backed pages are page cache, which
        MemAvailable already counts. Without this the idle Pi, holding E4B
        in va-llm, showed ~4.8 GB and refused every E4B run."""
        pid = self.deployed_server_pid()
        if not pid:
            return 0
        try:
            with open("/proc/%d/status" % pid) as f:
                for line in f:
                    if line.startswith("RssAnon:"):
                        return int(line.split()[1]) // 1024
        except (OSError, ValueError, IndexError):
            pass
        return 0

    def busy_processes(self):
        """Benchmark processes already running, the deployed server aside."""
        found = [name for name, pattern in (("lm_eval", "[l]m_eval"),
                                            ("run_measured", "[r]un_measured"))
                 if self._pgrep(pattern)]
        deployed = self.deployed_server_pid()
        if [pid for pid in self._pgrep("[l]lama-server") if pid != deployed]:
            found.append("llama-server")
        return found

class FixedProbe:
    """A probe with fixed answers, for queue_ctl's tests (AGENTIC_TEST_PROBE).

    queue_ctl runs as a subprocess in its tests, so the probe cannot be
    injected; without this its answers came from whatever the test machine
    happened to be running."""

    def __init__(self, mem=9000, busy=(), reclaim=0):
        self._mem, self._busy, self._reclaim = mem, list(busy), reclaim

    def mem_available_mb(self):
        return self._mem

    def busy_processes(self):
        return list(self._busy)

    def rss_by_user(self):
        return {}

    def reclaimable_mb(self):
        return self._reclaim


def probe_from_env(env=None):
    raw = (env if env is not None else os.environ).get("AGENTIC_TEST_PROBE")
    if not raw:
        return None
    import json
    return FixedProbe(**json.loads(raw))


def _memory(paths, resolved, probe):
    need = resolved.get("memory_mb")
    if not need:
        return {"name": "memory", "ok": True, "measured": None,
                "detail": "this job kind declares no memory requirement"}
    free = probe.mem_available_mb()
    back = getattr(probe, "reclaimable_mb", lambda: 0)()
    have = free + back
    note = (" (%d free + %d the deployed va-llm releases on restart)"
            % (free, back)) if back else ""
    if have >= need:
        return {"name": "memory", "ok": True, "measured": have,
                "detail": "%d MB available%s, need ~%d MB" % (have, note, need)}
    others = probe.rss_by_user()
    who = "; ".join("%s %d MB" % (u, mb) for u, mb in sorted(others.items()))
    return {"name": "memory", "ok": False, "measured": have,
            "detail": "only %d MB available%s, need ~%d MB%s"
                      % (have, note, need, (" — on the board: " + who) if who else "")}


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

# Checks about the board's state right now, as opposed to the job's own
# inputs. While another job is running or queued ahead, "now" says nothing
# about the moment this job will start, so these are postponed to the runner,
# which repeats every check at start. Checking them at queue time is what made
# the web form refuse to queue anything behind a running job.
BOARD_STATE = ("memory", "board_idle")

# The only check a person may override, and only with a recorded reason. A
# stale output_dir replays an old lm-eval cache instead of running; a missing
# subset cannot run at all; a second concurrent run invalidates both runs'
# telemetry (AGENTS §9). Memory is a judgement call on a threshold.
OVERRIDABLE = ("memory",)


def _defer(result, why):
    return dict(result, ok=True, deferred=True,
                detail="checked when this job starts — %s (now: %s)"
                       % (why, result["detail"]))


def _duplicate(resolved, pending):
    """A job for the same output directory already waiting or running."""
    for j in pending:
        if j.get("output_dir") == resolved["output_dir"]:
            return {"name": "not_queued", "ok": False, "measured": j.get("id"),
                    "detail": "%s is already %s as job %s"
                              % (resolved["output_dir"], j.get("state", "queued"),
                                 j.get("id"))}
    return {"name": "not_queued", "ok": True, "measured": None,
            "detail": "no other job writes %s" % resolved["output_dir"]}


def run_all(paths, resolved, probe=None, pending=None, ahead=None):
    """Every check, each result marked overridable or not.

    pending is given only at queue time (queue_ctl): the jobs already queued
    or running, for the duplicate check. At queue time the board-state checks
    are postponed when something runs first (ahead names it) or the board is
    busy. The runner passes neither, so at start every check is real."""
    probe = probe or probe_from_env() or Probe()
    results = [check(paths, resolved, probe) for check in CHECKS]
    if pending is not None:
        results.append(_duplicate(resolved, pending))
    busy = next((r for r in results if r["name"] == "board_idle" and not r["ok"]), None)
    if pending is not None and (ahead or busy):
        why = ("%s runs first" % ahead) if ahead else "the board is busy now; the queue waits for it"
        results = [_defer(r, why) if r["name"] in BOARD_STATE and not r["ok"] else r
                   for r in results]
    for r in results:
        r["overridable"] = r["name"] in OVERRIDABLE
    return results


def passed(results):
    return all(r["ok"] for r in results)


def blocking(results, override=None):
    """Failed checks that an override does not cover. Empty means go."""
    allowed = set((override or {}).get("checks") or ()) & set(OVERRIDABLE)
    return [r for r in results if not r["ok"] and r["name"] not in allowed]


def validate_override(override):
    """{"checks": [...], "reason": "..."} or ValueError saying why not."""
    if not override:
        return None
    if not isinstance(override, dict):
        raise ValueError("override must be an object with checks and reason")
    checks = override.get("checks") or []
    bad = [c for c in checks if c not in OVERRIDABLE]
    if not checks or bad:
        raise ValueError("only %s can be overridden (got %s)"
                         % (", ".join(OVERRIDABLE), ", ".join(checks) or "nothing"))
    reason = (override.get("reason") or "").strip()
    if len(reason) < 8:
        raise ValueError("an override needs a reason of at least 8 characters; "
                         "it is recorded with the run (AGENTS §5)")
    return {"checks": sorted(set(checks)), "reason": reason,
            "by": override.get("by", "unknown")}
