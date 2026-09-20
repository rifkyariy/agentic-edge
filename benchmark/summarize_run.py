#!/usr/bin/env python3
"""Energy and efficiency summary for one measured run.

    python3 summarize_run.py --dir run/ [--idle-pre 30] [--idle-post 30]

Reads telemetry.csv (1 Hz device samples) and requests.csv (per-request token
timings) and writes summary.json. The headline numbers are the ones an edge
deployment is actually judged on:

    J/token      energy per generated token, idle power subtracted
    tok/s/W      throughput per watt during generation
    idle_w       the board's floor with the model resident but not working

Energy is a trapezoidal integral of power over the sample timestamps, so a
dropped sample stretches its neighbours rather than silently losing energy.
"""
import argparse
import csv
import json
import os
import statistics as st
import sys


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def integrate(rows, key, lo=None, hi=None):
    """Trapezoidal ∫ over ts_epoch, returning (joules, seconds)."""
    pts = [(r["_t"], num(r[key])) for r in rows
           if (lo is None or r["_t"] >= lo) and (hi is None or r["_t"] <= hi)]
    pts = [(t, v) for t, v in pts if v is not None]
    j = span = 0.0
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        dt = t1 - t0
        if 0 < dt < 30:  # skip gaps from a stalled sampler
            j += (v0 + v1) / 2 * dt
            span += dt
    return j, span


def stats(rows, key, lo=None, hi=None):
    v = [num(r[key]) for r in rows
         if (lo is None or r["_t"] >= lo) and (hi is None or r["_t"] <= hi)]
    v = [x for x in v if x is not None]
    if not v:
        return None
    return {"mean": round(st.mean(v), 2), "median": round(st.median(v), 2),
            "min": round(min(v), 2), "max": round(max(v), 2), "n": len(v)}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--idle-pre", type=float, default=30)
    ap.add_argument("--idle-post", type=float, default=30)
    args = ap.parse_args()

    tele = os.path.join(args.dir, "telemetry.csv")
    with open(tele) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["_t"] = num(r["ts_epoch"])
    rows = [r for r in rows if r["_t"]]
    if not rows:
        sys.exit(f"no samples in {tele}")

    meta = {}
    mpath = os.path.join(args.dir, "meta.json")
    if os.path.exists(mpath):
        meta = json.load(open(mpath))

    t0, t1 = rows[0]["_t"], rows[-1]["_t"]
    # The command's own window, excluding the idle baselines around it.
    work_lo = meta.get("work_start_epoch") or (t0 + args.idle_pre)
    work_hi = meta.get("work_end_epoch") or (t1 - args.idle_post)

    reqs = []
    rpath = os.path.join(args.dir, "requests.csv")
    if os.path.exists(rpath):
        with open(rpath) as f:
            reqs = [r for r in csv.DictReader(f)
                    if num(r["end_epoch"]) and work_lo <= num(r["end_epoch"]) <= work_hi + 60]

    idle_w = stats(rows, "power_w", t0, t0 + args.idle_pre) or {}
    idle_mean = idle_w.get("mean")
    work_j, work_s = integrate(rows, "power_w", work_lo, work_hi)
    idle_j = (idle_mean or 0) * work_s

    gen_tokens = sum(int(r["gen_tokens"]) for r in reqs if r["gen_tokens"])
    prompt_tokens = sum(int(r["prompt_tokens"]) for r in reqs if r["prompt_tokens"])
    gen_s = sum(float(r["gen_ms"]) for r in reqs if r["gen_ms"]) / 1000
    prompt_s = sum(float(r["prompt_ms"]) for r in reqs if r["prompt_ms"]) / 1000

    # Decode-only power: samples inside a request's generation phase.
    gen_windows = [(num(r["start_epoch"]) + (float(r["prompt_ms"] or 0) / 1000),
                    num(r["end_epoch"])) for r in reqs if num(r["end_epoch"])]
    gen_rows = [r for r in rows if any(lo <= r["_t"] <= hi for lo, hi in gen_windows)]
    gen_power = None
    if gen_rows:
        v = [num(r["power_w"]) for r in gen_rows if num(r["power_w"])]
        gen_power = round(st.mean(v), 2) if v else None

    out = {
        "label": meta.get("label"),
        "model": meta.get("model_path"),
        "command": meta.get("command"),
        "samples": len(rows),
        "wall_s": round(t1 - t0, 1),
        "work_s": round(work_s, 1),
        "power": {
            "idle_w": idle_mean,
            "idle_post_w": (stats(rows, "power_w", t1 - args.idle_post, t1) or {}).get("mean"),
            "work_mean_w": round(work_j / work_s, 2) if work_s else None,
            "work_peak_w": (stats(rows, "power_w", work_lo, work_hi) or {}).get("max"),
            "generation_mean_w": gen_power,
            "energy_wh": round(work_j / 3600, 3),
            "energy_j": round(work_j, 1),
            "energy_above_idle_j": round(work_j - idle_j, 1),
            "_method": "sum of PMIC per-rail V*I, trapezoidal over 1Hz samples; "
                       "board DC power, excludes PSU conversion loss",
        },
        "tokens": {
            "requests": len(reqs),
            "prompt_tokens": prompt_tokens, "generated_tokens": gen_tokens,
            "prefill_s": round(prompt_s, 1), "decode_s": round(gen_s, 1),
            "prefill_tok_s": round(prompt_tokens / prompt_s, 2) if prompt_s else None,
            "decode_tok_s": round(gen_tokens / gen_s, 2) if gen_s else None,
        },
        "efficiency": {
            "j_per_generated_token": round(work_j / gen_tokens, 2) if gen_tokens else None,
            "j_per_generated_token_above_idle":
                round((work_j - idle_j) / gen_tokens, 2) if gen_tokens else None,
            "j_per_token_all": round(work_j / (gen_tokens + prompt_tokens), 3)
                if (gen_tokens + prompt_tokens) else None,
            "decode_tok_s_per_w": round((gen_tokens / gen_s) / gen_power, 3)
                if gen_s and gen_power else None,
            "tokens_per_wh": round(gen_tokens / (work_j / 3600), 1) if work_j else None,
        },
        "thermal": {
            "temp_c": stats(rows, "temp_c", work_lo, work_hi),
            "throttled_nonzero_samples": sum(
                1 for r in rows if r.get("throttled") not in ("0x0", "", None)),
            "cpu_mhz_mean": (stats(rows, "cpu0_mhz", work_lo, work_hi) or {}).get("mean"),
        },
        "utilisation": {
            "cpu_pct": stats(rows, "cpu_pct", work_lo, work_hi),
            "proc_cpu_pct": stats(rows, "proc_cpu_pct", work_lo, work_hi),
            "proc_rss_mb": stats(rows, "proc_rss_mb", work_lo, work_hi),
            "mem_used_mb": stats(rows, "mem_used_mb", work_lo, work_hi),
            "swap_used_mb": stats(rows, "swap_used_mb", work_lo, work_hi),
        },
    }
    path = os.path.join(args.dir, "summary.json")
    json.dump(out, open(path, "w"), indent=1)
    print(json.dumps(out, indent=1))
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
