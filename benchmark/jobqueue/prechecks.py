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
