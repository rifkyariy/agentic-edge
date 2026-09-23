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
        """Benchmark processes already running."""
        found = [name for name, pattern in (("lm_eval", "[l]m_eval"),
                                            ("run_measured", "[r]un_measured"))
                 if self._pgrep(pattern)]
        deployed = self.deployed_server_pid()
        if [pid for pid in self._pgrep("[l]lama-server") if pid != deployed]:
            found.append("llama-server")
        return found

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


def run_all(paths, resolved, probe=None):
    probe = probe or Probe()
    return [check(paths, resolved, probe) for check in CHECKS]


def passed(results):
    return all(r["ok"] for r in results)
