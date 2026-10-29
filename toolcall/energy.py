#!/usr/bin/env python3
"""Energy summary for one Jetson run, after main's benchmark/summarize_run.py.

    python3 energy.py runs/<name> [--idle 30]

Reads tegrastats.log (1 Hz; VDD_IN is the whole board's input power from the
INA3221, so it excludes PSU loss) and results.jsonl, and writes energy.json:
run totals, idle power with the model resident, energy above idle, J per task
and per generated token, and each task's own energy.

Power is integrated by the trapezoid rule with linear interpolation at the
window edges, so a 3 s task between two samples still gets its share.
Runs from before results.jsonl carried start/end epochs have no idle baseline
and no per-task split; their window is the whole log.
"""
import argparse, bisect, json, re, statistics as st, time
from pathlib import Path

LINE = re.compile(r"^(\S+ \S+) RAM (\d+)/.*?GR3D_FREQ (\d+)%.*?tj@([\d.]+)C.*?VDD_IN (\d+)mW")


def parse(path):
    """[(epoch, watts, ram_mb, gpu_pct, tj_c)].
    shortcut: tegrastats logs local time to the second, so run this on the board that
    wrote the log (or under its TZ); timing is good to about 1 s, fine for 2-10 s tasks."""
    out = []
    for line in open(path):
        if m := LINE.match(line):
            t = time.mktime(time.strptime(m[1], "%m-%d-%Y %H:%M:%S"))
            out.append((t, int(m[5]) / 1000, int(m[2]), int(m[3]), float(m[4])))
    return out


def integrate(ts, w, lo, hi):
    """∫ power dt over [lo, hi], in joules."""
    def at(t):
        i = min(max(bisect.bisect_left(ts, t), 1), len(ts) - 1)
        t0, t1 = ts[i - 1], ts[i]
        return w[i - 1] + (w[i] - w[i - 1]) * (min(max(t, t0), t1) - t0) / (t1 - t0)
    pts = [(lo, at(lo))] + [(t, v) for t, v in zip(ts, w) if lo < t < hi] + [(hi, at(hi))]
    return sum((b[0] - a[0]) * (a[1] + b[1]) / 2 for a, b in zip(pts, pts[1:]))


def summarize(samples, recs, idle=30.0):
    ts, w = [s[0] for s in samples], [s[1] for s in samples]
    timed = all("start_epoch" in r for r in recs)
    lo = min(r["start_epoch"] for r in recs) if timed else ts[0]
    hi = max(r["end_epoch"] for r in recs) if timed else ts[-1]
    mean = lambda a, b: round(st.mean(v), 2) if (v := [x for t, x in zip(ts, w) if a <= t <= b]) else None
    idle_w = mean(lo - idle, lo - 1) if timed else None
    work_j, work_s = integrate(ts, w, lo, hi), hi - lo
    above = work_j - idle_w * work_s if idle_w else None
    gen = sum(r["usage"]["completion_tokens"] for r in recs if r.get("usage"))
    prompt = sum(r["usage"]["prompt_tokens"] for r in recs if r.get("usage"))
    rnd = lambda x, n=2: round(x, n) if x is not None else None
    work = [s for s in samples if lo <= s[0] <= hi]
    per_task = None
    if timed:
        per_task = {}
        for r in recs:
            j = integrate(ts, w, r["start_epoch"], r["end_epoch"])
            per_task[r["id"]] = {"j": round(j, 2),
                                 "j_above_idle": rnd(j - idle_w * (r["end_epoch"] - r["start_epoch"])) if idle_w else None}
    return {
        "power_source": "tegrastats VDD_IN (board input, INA3221; excludes PSU loss)",
        "window": "first task start to last task end" if timed else "whole tegrastats log (no per-task epochs)",
        "idle_w": idle_w, "idle_post_w": mean(hi + 1, hi + idle) if timed else None,
        "work_s": round(work_s, 1), "work_mean_w": rnd(work_j / work_s),
        "energy_wh": round(work_j / 3600, 3), "energy_j": round(work_j, 1),
        "energy_above_idle_j": rnd(above, 1),
        "tasks": len(recs), "j_per_task": rnd(work_j / len(recs)),
        "j_per_task_above_idle": rnd(above / len(recs)) if above is not None else None,
        "generated_tokens": gen, "prompt_tokens": prompt,
        "j_per_generated_token": rnd(work_j / gen, 3) if gen else None,
        "j_per_generated_token_above_idle": rnd(above / gen, 3) if gen and above is not None else None,
        "tokens_per_wh": round(gen / (work_j / 3600), 1) if gen else None,
        "peak_ram_mb": max(s[2] for s in work), "mean_gpu_load_pct": round(st.mean(s[3] for s in work), 1),
        "peak_tj_c": max(s[4] for s in work),
        "per_task": per_task,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--idle", type=float, default=30)
    a = ap.parse_args()
    recs = [json.loads(l) for l in (a.run / "results.jsonl").open()]
    s = summarize(parse(a.run / "tegrastats.log"), recs, a.idle)
    (a.run / "energy.json").write_text(json.dumps(s, indent=2))
    print(" ".join(f"{k}={v}" for k, v in s.items() if k not in ("per_task", "power_source", "window")))


if __name__ == "__main__":
    main()
