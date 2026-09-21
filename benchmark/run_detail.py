#!/usr/bin/env python3
"""Everything the dashboard needs about one benchmark run, as JSON.

    python3 run_detail.py --run mmlupro100-e2b-s1

Finished runs come straight from lm-eval's per-question samples. A run still in
flight has no samples file yet, so answers are recovered from lm-eval's response
cache and matched back to their question by the option text they quote — a
best-effort mapping, flagged as such, so progress can be inspected without
waiting hours for the run to end.

Run it with the eval venv's python (it needs `datasets` for the partial path);
the finished path is stdlib only.
"""
import argparse
import csv
import glob
import json
import os
import re
import sqlite3
import time

HOME = os.path.expanduser("~")
ROOT = next((p for p in (f"{HOME}/Research", f"{HOME}/research") if os.path.isdir(p)), HOME)
ANS = re.compile(r"answer is \(?([A-J])\)?", re.I)


def _rows(csv_path):
    rows = [r for r in csv.DictReader(open(csv_path)) if r.get("start_epoch")]
    if not rows:
        return []
    t0 = min(float(r["start_epoch"]) for r in rows)
    return [{"i": i, "t": round(float(r["start_epoch"]) - t0, 1),
             "start_epoch": float(r["start_epoch"]), "end_epoch": float(r["end_epoch"] or 0),
             "pt": int(r["prompt_tokens"] or 0), "pms": float(r["prompt_ms"] or 0),
             "gt": int(r["gen_tokens"] or 0), "gms": float(r["gen_ms"] or 0),
             "pts": float(r["prompt_tok_s"] or 0), "gts": float(r["gen_tok_s"] or 0)}
            for i, r in enumerate(sorted(rows, key=lambda r: float(r["start_epoch"])))]


def measured_dir(model, subset):
    """The measured run that produced this benchmark run, matched on model and
    subset — never just the newest, since both boards work through a queue."""
    for d in sorted(glob.glob(f"{ROOT}/measured/*"), key=os.path.getmtime, reverse=True):
        base = os.path.basename(d).lower()
        if model not in base:
            continue
        got = re.search(r"-(s\d)-\d{8}", base)
        if (got[1] if got else "s1") != subset:
            continue
        return d
    return None


def _journal(since, until, here):
    """Per-request rows out of the llama-server journal for a time window."""
    fmt = "%Y-%m-%d %H:%M:%S"
    cmd = (f'python3 {here}/parse_llama_log.py '
           f'--since "{time.strftime(fmt, time.localtime(since))}" '
           f'--until "{time.strftime(fmt, time.localtime(until))}" --out /tmp/_rt.csv')
    os.system(cmd + " >/dev/null 2>&1")
    if not os.path.exists("/tmp/_rt.csv"):
        return []
    rows = _rows("/tmp/_rt.csv")
    os.remove("/tmp/_rt.csv")
    return rows


def timeline(run_dir, run, model, subset, mdir=None):
    """Per-request timings for THIS run, in order of preference:
    its own requests.csv, the measured run that produced it (matched on model
    and subset, never just the newest), its own server log, or the journal
    window reconstructed from the results file and the run's duration."""
    own = os.path.join(run_dir, "requests.csv")
    if os.path.exists(own):
        rows = _rows(own)
        if rows:
            return rows
    if mdir:
        csv_path = os.path.join(mdir, "requests.csv")
        if os.path.exists(csv_path):
            rows = _rows(csv_path)
            if rows:
                return rows
    here = os.path.dirname(os.path.abspath(__file__))
    log = os.path.join(run_dir, "server.log")
    if os.path.exists(log):
        os.system(f"python3 {here}/parse_llama_log.py --file {log} --out /tmp/_rt.csv >/dev/null 2>&1")
        if os.path.exists("/tmp/_rt.csv"):
            rows = _rows("/tmp/_rt.csv")
            os.remove("/tmp/_rt.csv")
            if rows:
                return rows
    # Still in flight: requests.csv is only written when run_measured.sh
    # finishes, so read the journal from the run's own start up to now.
    if mdir:
        try:
            meta = json.load(open(os.path.join(mdir, "meta.json")))
            start = meta.get("work_start_epoch") or meta.get("start_epoch")
            if start:
                # no slack backwards: it would pull in the tail of whatever
                # run this one replaced on the queue.
                rows = _journal(start, time.time() + 60, here)
                if rows:
                    return rows
        except (OSError, ValueError):
            pass

    res = sorted(glob.glob(f"{run_dir}/*/results_*.json"))
    if res:
        try:
            end = os.path.getmtime(res[-1])
            secs = float(json.load(open(res[-1])).get("total_evaluation_time_seconds", 0))
            if secs:
                fmt = "%Y-%m-%d %H:%M:%S"
                since = time.strftime(fmt, time.localtime(end - secs - 120))
                until = time.strftime(fmt, time.localtime(end + 120))
                os.system(f'python3 {here}/parse_llama_log.py --since "{since}" '
                          f'--until "{until}" --out /tmp/_rt.csv >/dev/null 2>&1')
                if os.path.exists("/tmp/_rt.csv"):
                    rows = _rows("/tmp/_rt.csv")
                    os.remove("/tmp/_rt.csv")
                    return rows
        except (OSError, ValueError):
            pass
    return []


def telemetry_for(run, model, subset):
    """The 1Hz device samples belonging to this run, matched the same way the
    request timings are: by model and subset, never just the newest."""
    d = measured_dir(model, subset)
    if d:
        path = os.path.join(d, "telemetry.csv")
        if not os.path.exists(path):
            return [], None, None
        rows = []
        for r in csv.DictReader(open(path)):
            t = _f(r.get("ts_epoch"))
            if t is None:
                continue
            rows.append({"t": t, "w": _f(r.get("power_w")), "cpu": _f(r.get("cpu_pct")),
                         "temp": _f(r.get("temp_c")), "gpu": _f(r.get("gpu_pct")),
                         "mem": _f(r.get("mem_used_mb")), "rss": _f(r.get("proc_rss_mb")),
                         "mhz": _f(r.get("cpu0_mhz")), "mhz_gpu": _f(r.get("gpu_mhz")),
                         "thr": (r.get("throttled") or "") not in ("", "0x0")})
        summary = None
        sp = os.path.join(d, "summary.json")
        if os.path.exists(sp):
            try:
                summary = json.load(open(sp))
            except ValueError:
                pass
        return rows, summary, os.path.basename(d)
    return [], None, None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def attach_device(tl, tele):
    """Per-request device conditions: what the board was doing while it answered.

    Energy is the trapezoidal integral of power across the request's own window,
    so J/token here is a real per-question measurement rather than a run average."""
    if not tl or not tele:
        return tl
    tele = sorted(tele, key=lambda r: r["t"])
    times = [r["t"] for r in tele]
    import bisect
    for q in tl:
        lo = bisect.bisect_left(times, q["start_epoch"])
        hi = bisect.bisect_right(times, q["end_epoch"])
        win = tele[max(0, lo - 1):hi + 1]
        if not win:
            continue
        w = [r["w"] for r in win if r["w"] is not None]
        energy = 0.0
        for a, b in zip(win, win[1:]):
            if a["w"] is not None and b["w"] is not None and 0 < b["t"] - a["t"] < 30:
                energy += (a["w"] + b["w"]) / 2 * (b["t"] - a["t"])
        vals = lambda k: [r[k] for r in win if r[k] is not None]
        cpu, temp, gpu, rss = vals("cpu"), vals("temp"), vals("gpu"), vals("rss")
        q["dev"] = {
            "w_mean": round(sum(w) / len(w), 2) if w else None,
            "w_max": round(max(w), 2) if w else None,
            "j": round(energy, 1) if energy else None,
            "j_per_token": round(energy / q["gt"], 2) if energy and q.get("gt") else None,
            "cpu": round(sum(cpu) / len(cpu), 1) if cpu else None,
            "temp_max": round(max(temp), 1) if temp else None,
            "gpu": round(sum(gpu) / len(gpu), 1) if gpu else None,
            "rss_mb": round(max(rss)) if rss else None,
            "throttled": any(r["thr"] for r in win),
            "samples": len(win),
        }
    return tl


def downsample(tele, t0, limit=700):
    """Telemetry for charting, thinned to at most `limit` points but keeping
    peaks: each bucket reports its max power and temperature, mean cpu/gpu."""
    if not tele:
        return []
    step = max(1, len(tele) // limit)
    out = []
    for i in range(0, len(tele), step):
        chunk = tele[i:i + step]
        pick = lambda k, f: (f([r[k] for r in chunk if r[k] is not None])
                             if any(r[k] is not None for r in chunk) else None)
        mean = lambda v: sum(v) / len(v)
        out.append({
            "t": round(chunk[0]["t"] - t0, 1),
            "w": round(pick("w", max), 2) if pick("w", max) is not None else None,
            "cpu": round(pick("cpu", mean), 1) if pick("cpu", mean) is not None else None,
            "temp": round(pick("temp", max), 1) if pick("temp", max) is not None else None,
            "gpu": round(pick("gpu", mean), 1) if pick("gpu", mean) is not None else None,
            "mem": round(pick("mem", max)) if pick("mem", max) is not None else None,
            "thr": any(r["thr"] for r in chunk),
        })
    return out


def finished(run_dir):
    """Questions and answers from lm-eval's own samples files."""
    out = []
    for f in sorted(glob.glob(f"{run_dir}/*/samples_mmlu_pro_*.jsonl")):
        for line in open(f):
            r = json.loads(line)
            doc, resp = r["doc"], r["resps"][0][0]
            m = ANS.findall(resp)
            out.append({"subject": doc.get("category"), "q": doc["question"],
                        "options": doc["options"], "gold": "ABCDEFGHIJ"[doc["answer_index"]],
                        "got": (m[0].upper() if m else None), "ok": bool(r["exact_match"]),
                        "resp": resp, "chars": len(resp)})
    return out


def partial(run_dir, subset):
    """Answers from the response cache, matched to questions by quoted options."""
    db = os.path.join(run_dir, "cache", "cache_rank0.db")
    if not os.path.exists(db):
        db = os.path.join(run_dir, "cache_rank0.db")
    if not os.path.exists(db):
        return [], "no cache yet"
    import pickle
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        resps = []
        for (v,) in con.execute("select value from unnamed order by rowid"):
            r = pickle.loads(v)
            resps.append(r[0] if isinstance(r, (list, tuple)) else r)
    except sqlite3.Error as e:
        return [], f"cache unreadable: {e}"
    if not resps:
        return [], "cache empty"
    try:
        from datasets import load_dataset
    except ImportError:
        return ([{"q": None, "resp": r, "got": (ANS.findall(r) or [None])[0],
                  "chars": len(r), "ok": None} for r in resps],
                "answers only — datasets not importable, so no question mapping")

    samples = json.load(open(f"{ROOT}/stdbench/mmlupro_subset100_{subset}_samples.json"))
    test = load_dataset("TIGER-Lab/MMLU-Pro", split="test")
    by_cat = {}
    for i, c in enumerate(test["category"]):
        by_cat.setdefault(c, []).append(i)
    docs = []
    for task, picks in samples.items():
        cat = task.replace("mmlu_pro_", "").replace("_", " ")
        for p in picks:
            docs.append(test[by_cat[cat][p]])

    def score(doc, text):
        low = text.lower()
        opts = [o for o in doc["options"] if isinstance(o, str) and len(o) > 12]
        hit = sum(1 for o in opts if o.lower()[:40] in low)
        words = set(re.findall(r"[a-z]{6,}", doc["question"].lower()))
        return hit * 3 + sum(1 for w in words if w in low)

    out, used = [], set()
    for text in resps:
        cands = sorted(((score(d, text), i) for i, d in enumerate(docs) if i not in used),
                       reverse=True)
        got = (ANS.findall(text) or [None])[0]
        if not cands or cands[0][0] < 4 or (len(cands) > 1 and cands[0][0] == cands[1][0]):
            out.append({"subject": None, "q": None, "options": [], "gold": None,
                        "got": got and got.upper(), "ok": None, "resp": text,
                        "chars": len(text)})
            continue
        i = cands[0][1]; used.add(i); d = docs[i]
        gold = "ABCDEFGHIJ"[d["answer_index"]]
        out.append({"subject": d["category"], "q": d["question"], "options": d["options"],
                    "gold": gold, "got": got and got.upper(),
                    "ok": (got or "").upper() == gold if got else False,
                    "resp": text, "chars": len(text)})
    return out, ("partial: answers matched to questions by the option text they "
                 "quote, so a few may be unmatched")


def live_device(tele, tl, tdir):
    """Energy and efficiency so far, for a run that has not written summary.json.

    Idle is the lowest 5% of samples, which on both boards is the pre-run
    baseline the wrapper records before work starts."""
    w = [(r["t"], r["w"]) for r in tele if r["w"] is not None]
    if not w:
        return None
    joules = sum((a[1] + b[1]) / 2 * (b[0] - a[0])
                 for a, b in zip(w, w[1:]) if 0 < b[0] - a[0] < 30)
    ws = sorted(v for _, v in w)
    idle = sum(ws[:max(1, len(ws) // 20)]) / max(1, len(ws) // 20)
    work = [v for _, v in w if v > idle * 1.15] or [v for _, v in w]
    gen_tok = sum(q.get("gt") or 0 for q in tl)
    gen_s = sum((q.get("gms") or 0) for q in tl) / 1000
    cpu = [r["cpu"] for r in tele if r["cpu"] is not None]
    gpu = [r["gpu"] for r in tele if r["gpu"] is not None]
    mhz = [r["mhz_gpu"] for r in tele if r.get("mhz_gpu") is not None]
    temp = [r["temp"] for r in tele if r["temp"] is not None]
    mean_w = sum(work) / len(work)
    return {
        "energy_wh": round(joules / 3600, 2),
        "idle_w": round(idle, 2),
        "mean_w": round(mean_w, 2),
        "peak_w": round(max(v for _, v in w), 2),
        "j_per_token": round(joules / gen_tok, 2) if gen_tok else None,
        "tok_s_per_w": round((gen_tok / gen_s) / mean_w, 3) if gen_s and mean_w else None,
        "temp_max": round(max(temp), 1) if temp else None,
        "throttled": sum(1 for r in tele if r["thr"]),
        "cpu_mean": round(sum(cpu) / len(cpu), 1) if cpu else None,
        "gpu_mean": round(sum(gpu) / len(gpu), 1) if gpu else None,
        "gpu_max": round(max(gpu), 1) if gpu else None,
        "gpu_mhz_mean": round(sum(mhz) / len(mhz)) if mhz else None,
        "dir": tdir, "provisional": True,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="directory name under stdbench/")
    ap.add_argument("--max-questions", type=int, default=400)
    args = ap.parse_args()

    run_dir = os.path.join(ROOT, "stdbench", args.run)
    if not os.path.isdir(run_dir):
        print(json.dumps({"error": f"no such run: {args.run}"})); return
    sub = (re.search(r"-(s\d)$", args.run) or [None, "s1"])[1]
    model = "e4b" if "e4b" in args.run.lower() else "e2b"

    res_files = glob.glob(f"{run_dir}/*/results_*.json")
    summary, note = {}, None
    qs = finished(run_dir)
    if qs:
        try:
            j = json.load(open(sorted(res_files)[-1]))
            r = j["results"]["mmlu_pro"]
            # lm-eval writes "N/A" rather than a number when n is tiny.
            def num(x):
                try:
                    return float(x)
                except (TypeError, ValueError):
                    return None
            se = num(r.get("exact_match_stderr,custom-extract"))
            summary = {"score": round(100 * num(r["exact_match,custom-extract"]), 1),
                       "stderr": round(100 * se, 1) if se is not None else None,
                       "minutes": round(num(j.get("total_evaluation_time_seconds")) / 60)}
        except (OSError, KeyError, ValueError, IndexError):
            pass
        status = "done"
    else:
        qs, note = partial(run_dir, sub)
        status = "running"
        graded = [q for q in qs if q.get("ok") is not None]
        if graded:
            summary = {"score": round(100 * sum(q["ok"] for q in graded) / len(graded), 1),
                       "graded": len(graded), "provisional": True}

    mdir = measured_dir(model, sub)
    tl = timeline(run_dir, args.run, model, sub, mdir)
    tele, tsummary, tdir = telemetry_for(args.run, model, sub)
    tl = attach_device(tl, tele)
    t0 = tl[0]["start_epoch"] if tl else (tele[0]["t"] if tele else 0)
    device = None
    if tsummary:
        device = {"energy_wh": tsummary["power"]["energy_wh"],
                  "idle_w": tsummary["power"]["idle_w"],
                  "mean_w": tsummary["power"]["work_mean_w"],
                  "peak_w": tsummary["power"]["work_peak_w"],
                  "j_per_token": tsummary["efficiency"]["j_per_generated_token"],
                  "tok_s_per_w": tsummary["efficiency"]["decode_tok_s_per_w"],
                  "temp_max": (tsummary["thermal"]["temp_c"] or {}).get("max"),
                  "throttled": tsummary["thermal"]["throttled_nonzero_samples"],
                  "cpu_mean": (tsummary["utilisation"]["cpu_pct"] or {}).get("mean"),
                  "gpu_mean": (tsummary["utilisation"].get("gpu_pct") or {}).get("mean"),
                  "gpu_max": (tsummary["utilisation"].get("gpu_pct") or {}).get("max"),
                  "gpu_mhz_mean": (tsummary["utilisation"].get("gpu_mhz") or {}).get("mean"),
                  "dir": tdir}
    elif tele:
        # summary.json only appears when the run ends; compute the same figures
        # from the telemetry so far and mark them provisional.
        device = live_device(tele, tl, tdir)
    print(json.dumps({
        "run": args.run, "subset": sub, "status": status, "note": note,
        "summary": summary, "n": len(qs),
        "questions": qs[:args.max_questions],
        "timeline": tl, "telemetry": downsample(tele, t0), "device": device,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }))


if __name__ == "__main__":
    main()
