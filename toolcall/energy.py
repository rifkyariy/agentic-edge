#!/usr/bin/env python3
"""Energy summary for one Jetson run, after main's benchmark/summarize_run.py.

    python3 energy.py runs/<name> [--idle 30]

    python3 energy.py runs/<name> --tasks tasks/t1.jsonl   # also per category / T1 group

Reads tegrastats.log (1 Hz; VDD_IN is the whole board's input power from the
INA3221, so it excludes PSU loss) and results.jsonl, and writes energy.json:
run totals, idle power with the model resident, energy above idle, J per task
and per token, decode-only power, prefill and decode speed, and each task's own
energy, the same set main's summarize_run.py reports. With --tasks it also
splits energy, time and pass rate by category and T1 group, so accuracy per Wh
can be read per tier.

Power is integrated by the trapezoid rule with linear interpolation at the
window edges, so a 3 s task between two samples still gets its share.
Runs from before results.jsonl carried start/end epochs have no idle baseline
and no per-task split; their window is the whole log.
"""
import argparse, bisect, json, re, statistics as st, time
from collections import defaultdict
from pathlib import Path

from score import group, score_task

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


def model_calls(r):
    """(request start epoch, llama-server timings) per model call; a JSON chain makes one per turn."""
    if r.get("turns"):
        return [(t.get("start_epoch"), t.get("timings")) for t in r["turns"] if t.get("timings")]
    return [(r.get("start_epoch"), r["timings"])] if r.get("timings") else []


def by_group(recs, tasks, per_task, idle_w):
    """Energy, time and pass rate per category and T1 group (chain length band, fan-out size)."""
    out = defaultdict(lambda: {"tasks": 0, "pass": 0, "energy_j": 0.0, "above_idle_j": 0.0, "wall_s": 0.0})
    for r in recs:
        t = tasks[r["id"]]
        ok = r["outcome"] == "ok" and score_task(t, r.get("calls") or [])["pass"]
        for k in {t["category"], group(t)} - {None}:
            g = out[k]
            g["tasks"] += 1
            g["pass"] += ok
            g["energy_j"] += per_task[r["id"]]["j"]
            g["above_idle_j"] += per_task[r["id"]]["j_above_idle"] or 0
            g["wall_s"] += r["end_epoch"] - r["start_epoch"]
    return {k: {"tasks": g["tasks"], "acc": round(g["pass"] / g["tasks"], 4),
                "j_per_task": round(g["energy_j"] / g["tasks"], 2),
                "j_per_task_above_idle": round(g["above_idle_j"] / g["tasks"], 2) if idle_w else None,
                "s_per_task": round(g["wall_s"] / g["tasks"], 2),
                "passes_per_wh": round(g["pass"] / (g["energy_j"] / 3600), 2)}
            for k, g in sorted(out.items())}


def summarize(samples, recs, idle=30.0, tasks=None):
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
    calls = [c for r in recs for c in model_calls(r)]
    prefill_s = sum(t["prompt_ms"] for _, t in calls) / 1000
    decode_s = sum(t["predicted_ms"] for _, t in calls) / 1000
    prefill_n = sum(t["prompt_n"] for _, t in calls)  # tokens actually processed: cache hits excluded
    decode_n = sum(t["predicted_n"] for _, t in calls)
    # decode-only power: samples inside a call's generation phase, as main's summarize_run.py
    windows = sorted((s + t["prompt_ms"] / 1000, s + (t["prompt_ms"] + t["predicted_ms"]) / 1000) for s, t in calls if s)
    gen_w = [x for t, x in zip(ts, w) if any(a <= t <= b for a, b in windows)]
    gen_mean_w = round(st.mean(gen_w), 2) if gen_w else None
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
        "j_per_token_all": rnd(work_j / (gen + prompt), 3) if gen + prompt else None,
        "work_peak_w": max(s[1] for s in work), "generation_mean_w": gen_mean_w,
        "model_calls": len(calls), "prefill_s": round(prefill_s, 1), "decode_s": round(decode_s, 1),
        "prefill_tok_s": rnd(prefill_n / prefill_s) if prefill_s else None,
        "decode_tok_s": rnd(decode_n / decode_s) if decode_s else None,
        "decode_tok_s_per_w": rnd(decode_n / decode_s / gen_mean_w, 3) if decode_s and gen_mean_w else None,
        "peak_ram_mb": max(s[2] for s in work), "mean_gpu_load_pct": round(st.mean(s[3] for s in work), 1),
        "peak_tj_c": max(s[4] for s in work),
        "by_group": by_group(recs, tasks, per_task, idle_w) if tasks and per_task else None,
        "per_task": per_task,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--idle", type=float, default=30)
    ap.add_argument("--tasks", type=Path)
    a = ap.parse_args()
    recs = [json.loads(l) for l in (a.run / "results.jsonl").open()]
    tasks = {t["id"]: t for t in map(json.loads, a.tasks.open())} if a.tasks else None
    s = summarize(parse(a.run / "tegrastats.log"), recs, a.idle, tasks)
    (a.run / "energy.json").write_text(json.dumps(s, indent=2))
    print(" ".join(f"{k}={v}" for k, v in s.items() if k not in ("per_task", "by_group", "power_source", "window")))
    for k, g in (s["by_group"] or {}).items():
        print(f"  {k:20} " + " ".join(f"{m}={v}" for m, v in g.items()))


if __name__ == "__main__":
    main()
