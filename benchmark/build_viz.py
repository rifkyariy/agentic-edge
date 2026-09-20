#!/usr/bin/env python3
"""Build the MMLU-Pro run page from graded results + device telemetry.

    python3 build_viz.py [--out findings/viz/mmlupro_run.html]

Reads, relative to the repo root:
  findings/stdbench/mmlupro100-{e2b,e4b}/   lm-eval results + per-question samples
  findings/measured/<label>-<stamp>/        telemetry.csv, requests.csv, meta.json
  findings/viz/template.html                the page, with a /*__DATA__*/{} slot

Telemetry series are emitted as arrays-of-arrays (not objects) because a 1Hz
sample over a multi-hour run is tens of thousands of rows and the key names
would triple the page size.
"""
import argparse
import collections
import csv
import glob
import json
import os
import re
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFICIAL = {"E2B": 60.0, "E4B": 69.4}
# (column in telemetry.csv, key in the page)
SERIES = [("power_w", "w"), ("cpu_pct", "cpu"), ("temp_c", "t"),
          ("mem_used_mb", "mem"), ("proc_rss_mb", "rss"), ("cpu0_mhz", "mhz"),
          ("swap_used_mb", "swap"), ("proc_cpu_pct", "pcpu")]


def num(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def graded(tag, d):
    res = json.load(open(glob.glob(d + "/results_*.json")[0]))
    tl = graded_timeline(os.path.join(d, "requests.csv"))
    qs = []
    for f in sorted(glob.glob(d + "/samples_mmlu_pro_*.jsonl")):
        for line in open(f):
            r = json.loads(line)
            doc, resp = r["doc"], r["resps"][0][0]
            m = re.findall(r"answer is \(?([A-J])\)?", resp, re.I)
            qs.append({"id": doc.get("question_id"), "subject": doc.get("category"),
                       "q": doc["question"], "options": doc["options"],
                       "gold": "ABCDEFGHIJ"[doc["answer_index"]],
                       "got": (m[0].upper() if m else None),
                       "ok": bool(r["exact_match"]), "resp": resp, "chars": len(resp)})
    by = collections.defaultdict(lambda: [0, 0])
    for q in qs:
        by[q["subject"]][1] += 1
        by[q["subject"]][0] += q["ok"]
    return {"score": round(100 * res["results"]["mmlu_pro"]["exact_match,custom-extract"], 1),
            "stderr": round(100 * res["results"]["mmlu_pro"]["exact_match_stderr,custom-extract"], 1),
            "official": OFFICIAL[tag],
            "minutes": round(float(res["total_evaluation_time_seconds"]) / 60),
            "n_correct": sum(q["ok"] for q in qs), "n": len(qs),
            "no_letter": sum(1 for q in qs if not q["got"]),
            "subjects": dict(sorted(by.items())), "questions": qs,
            "timeline": tl,
            "total_gen_tokens": sum(r["gt"] for r in tl),
            "total_prompt_tokens": sum(r["pt"] for r in tl)}


def graded_timeline(path):
    """Per-request timings for a run that predates the telemetry wrapper,
    recovered from llama-server's journal with parse_llama_log.py."""
    if not os.path.exists(path):
        return []
    rows = [r for r in csv.DictReader(open(path)) if num(r["start_epoch"])]
    rows.sort(key=lambda r: num(r["start_epoch"]))
    t0 = num(rows[0]["start_epoch"]) if rows else 0
    return [{"i": i, "t": round(num(r["start_epoch"]) - t0, 1),
             "pt": int(num(r["prompt_tokens"], 0)), "pms": num(r["prompt_ms"], 0),
             "gt": int(num(r["gen_tokens"], 0)), "gms": num(r["gen_ms"], 0),
             "pts": num(r["prompt_tok_s"], 0), "gts": num(r["gen_tok_s"], 0)}
            for i, r in enumerate(rows)]


def requests_of(path, t0):
    rows = []
    if not os.path.exists(path):
        return rows
    for r in csv.DictReader(open(path)):
        st_, en = num(r["start_epoch"]), num(r["end_epoch"])
        if st_ is None or en is None:
            continue
        rows.append({"t": round(st_ - t0, 1), "d": round(en - st_, 1),
                     "pt": int(num(r["prompt_tokens"], 0)), "pms": num(r["prompt_ms"], 0),
                     "gt": int(num(r["gen_tokens"], 0)), "gms": num(r["gen_ms"], 0),
                     "pts": num(r["prompt_tok_s"], 0), "gts": num(r["gen_tok_s"], 0)})
    rows.sort(key=lambda r: r["t"])
    return rows


def measured(d):
    meta = json.load(open(os.path.join(d, "meta.json")))
    rows = [r for r in csv.DictReader(open(os.path.join(d, "telemetry.csv")))
            if num(r["ts_epoch"])]
    if not rows:
        return None
    t0 = num(rows[0]["ts_epoch"])
    series = {k: [] for _, k in SERIES}
    ts, throttle = [], []
    for r in rows:
        ts.append(round(num(r["ts_epoch"]) - t0, 1))
        for col, key in SERIES:
            series[key].append(num(r[col]))
        if r.get("throttled") not in ("0x0", "", None):
            throttle.append(round(num(r["ts_epoch"]) - t0, 1))
    reqs = requests_of(os.path.join(d, "requests.csv"), t0)

    idle_end = (meta.get("work_start_epoch") or (t0 + 30)) - t0
    idle = [w for t, w in zip(ts, series["w"]) if t <= idle_end and w]
    work = [(t, w) for t, w in zip(ts, series["w"]) if t > idle_end and w]
    energy = sum((w0 + w1) / 2 * (t1 - t0_)
                 for (t0_, w0), (t1, w1) in zip(work, work[1:]) if 0 < t1 - t0_ < 30)
    gen_tok = sum(r["gt"] for r in reqs)
    idle_w = round(st.mean(idle), 2) if idle else None
    work_s = work[-1][0] - work[0][0] if len(work) > 1 else 0
    powers = [w for _, w in work]
    return {
        "label": meta.get("label"), "model": os.path.basename(meta.get("model_path") or ""),
        "server_args": meta.get("server_args", ""), "governor": meta.get("governor"),
        "done": meta.get("exit_code") is not None,
        "start_iso": meta.get("start_epoch"),
        "idle_end_s": round(idle_end, 1),
        "ts": ts, **series, "throttle": throttle, "requests": reqs,
        "stats": {
            "idle_w": idle_w,
            "mean_w": round(st.mean(powers), 2) if powers else None,
            "peak_w": round(max(powers), 2) if powers else None,
            "energy_wh": round(energy / 3600, 3),
            "energy_j": round(energy, 1),
            "above_idle_j": round(energy - (idle_w or 0) * work_s, 1) if powers else None,
            "gen_tokens": gen_tok, "prompt_tokens": sum(r["pt"] for r in reqs),
            "requests": len(reqs),
            "j_per_token": round(energy / gen_tok, 2) if gen_tok else None,
            "j_per_token_above_idle": round((energy - (idle_w or 0) * work_s) / gen_tok, 2)
                if gen_tok else None,
            "decode_tok_s": round(gen_tok / (sum(r["gms"] for r in reqs) / 1000), 2)
                if gen_tok else None,
            "tok_s_per_w": None,  # filled below
            "temp_max": round(max((x for x in series["t"] if x), default=0), 1),
            "temp_mean": round(st.mean([x for x in series["t"] if x]), 1) if series["t"] else None,
            "cpu_mean": round(st.mean([x for x in series["cpu"] if x is not None]), 1),
            "rss_max": round(max((x for x in series["rss"] if x), default=0), 1),
            "mem_max": round(max((x for x in series["mem"] if x), default=0), 1),
            "throttle_samples": len(throttle),
            "work_s": round(work_s, 1), "samples": len(ts),
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(ROOT, "findings/viz/mmlupro_run.html"))
    ap.add_argument("--template", default=os.path.join(ROOT, "findings/viz/template.html"))
    args = ap.parse_args()

    data = {"models": {}, "runs": {}}
    for tag in ("E2B", "E4B"):
        d = os.path.join(ROOT, f"findings/stdbench/mmlupro100-{tag.lower()}")
        if os.path.isdir(d) and glob.glob(d + "/results_*.json"):
            data["models"][tag] = graded(tag, d)
    for d in sorted(glob.glob(os.path.join(ROOT, "findings/measured/*"))):
        if os.path.exists(os.path.join(d, "telemetry.csv")):
            m = measured(d)
            if not m:
                continue
            s = m["stats"]
            if s["decode_tok_s"] and s["mean_w"]:
                s["tok_s_per_w"] = round(s["decode_tok_s"] / s["mean_w"], 3)
            data["runs"][os.path.basename(d)] = m

    page = open(args.template).read().replace("/*__DATA__*/{}", json.dumps(data))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    open(args.out, "w").write(page)
    print(f"{len(data['models'])} graded model(s), {len(data['runs'])} measured run(s) "
          f"-> {args.out} ({os.path.getsize(args.out) / 1024:.0f} KB)")
    for k, v in data["runs"].items():
        print(f"  {k}: {v['stats']['samples']} samples, {v['stats']['requests']} requests, "
              f"{v['stats']['mean_w']}W mean, {v['stats']['j_per_token']} J/token")


if __name__ == "__main__":
    main()
