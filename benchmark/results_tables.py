#!/usr/bin/env python3
"""Write findings/TABLES.md: every result in the repository as tables,
generated from the committed data and nothing else.

    python3 benchmark/results_tables.py            # rewrite findings/TABLES.md
    python3 benchmark/results_tables.py --check    # exit 1 if it is out of date

Sources, all under findings/ unless noted:
    runs/jetson/         the manuscript's Jetson runs (collect_runs.py)
    export/              the Pi's MMLU-Pro baseline runs
    phone/               the iPhone runs
    stdbench/            tinyGSM8k (Pi)
    benchmark/results/   the own suite (rendered by report.py)

The manuscript's own tables are rebuilt by the same functions paper_tables.py
checks against the paper, so the two cannot disagree. Stdlib only.
"""
import argparse
import collections
import contextlib
import glob
import gzip
import io
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paper_tables as pt  # noqa: E402
import report  # noqa: E402

ROOT = pt.ROOT
OUT = os.path.join(ROOT, "findings", "TABLES.md")
F = os.path.join(ROOT, "findings")
ENGINES = ("llama.cpp", "llama.cpp+n-gram", "little-gemma", "CoPR", "+ prompt lookup", "+ prefix reuse")
LABEL = {"llama.cpp": "llama.cpp", "llama.cpp+n-gram": "llama.cpp + n-gram (width 4)",
         "little-gemma": "little-gemma", "CoPR": "**CoPR**",
         "+ prompt lookup": "little-gemma + prompt lookup", "+ prefix reuse": "little-gemma + prefix reuse"}


def table(head, rows, align=None):
    align = align or ["---"] + ["---:"] * (len(head) - 1)
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(align) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def ci95(p, n):
    return 196 * math.sqrt(p * (1 - p) / n)  # in points, normal approximation


def pct(p, n=None):
    return "%.1f" % (100 * p) if n is None else "%.1f ± %.1f" % (100 * p, ci95(p, n))


def f(x, nd):
    return "—" if x is None else "%.*f" % (nd, x)


# ------------------------------------------------------------ sections

def manuscript():
    s = ["## 1. The manuscript's tables, from the data\n",
         "Rebuilt from `findings/runs/jetson/` by the functions `paper_tables.py` checks "
         "against the paper (203 values match; the two Table IV rounding errata are noted "
         "where they fall). Jetson Orin Nano 8 GB, 15 W, greedy, thinking off.\n"]

    s.append("### Table I — baseline anatomy, E2B, n=300\n")
    rows = []
    for col in ("llama.cpp", "little-gemma"):
        p, rep = pt.pooled(pt.ROW[col], "e2b"), pt.pooled_replies(pt.ROW[col], "e2b")
        rows.append([col, pt.thousands(p["gen"]), f(p["decode"], 2), pt.thousands(p["prompt_q"]),
                     f(p["prefill_share"], 1), f(pt.accuracy(rep), 1)])
    s.append(table(["engine", "generated tokens", "decode tok/s", "prompt tokens prefilled / q",
                    "share of time in prefill %", "accuracy %"], rows))

    s.append("\n### Table III — the engine comparison, n=300 per cell\n")
    for m in pt.MODELS:
        lg = pt.pooled_replies("lg-", m)
        base = pt.pooled_replies("", m)
        rows = []
        for col in ("llama.cpp", "llama.cpp+n-gram", "little-gemma", "CoPR"):
            p, rep = pt.pooled(pt.ROW[col], m), pt.pooled_replies(pt.ROW[col], m)
            if col == "little-gemma":
                same = "—"
            elif col == "llama.cpp+n-gram":
                same = "%d/300 to llama.cpp" % pt.identical(rep, base)
            else:
                same = "%d/300" % pt.identical(rep, lg)
            rows.append([LABEL[col], pct(pt.accuracy(rep) / 100, 300), same, f(p["decode"], 2),
                         pt.thousands(p["prompt_q"]), f(p["wall_q"], 1), f(p["gen_w"], 2),
                         f(p["j_tok"], 3), f(p["j_tok_idle"], 3)])
        s.append("**Gemma 4 %s**\n\n" % m.upper())
        s.append(table(["engine", "accuracy % (95% CI)", "replies = little-gemma", "decode tok/s",
                        "prompt tok / q", "wall s / q", "W generating", "J / gen. token",
                        "J above idle"], rows) + "\n")

    s.append("### Table IV — llama.cpp's own n-gram drafting against CoPR, E2B, s1 (n=100)\n")
    rows = []
    spec = [("llama.cpp, no drafting", "mmlupro100-e2b-s1", None),
            ("llama.cpp n-gram, width 3 (`n3m2`) — never drafted, see §8", "mmlupro100-ngram-n3m2-e2b-s1", "mmlupro100-e2b-s1"),
            ("llama.cpp n-gram, width 4 (`n3m3`)", "mmlupro100-ngram-n3m3-e2b-s1", "mmlupro100-e2b-s1"),
            ("llama.cpp n-gram, stock settings", "mmlupro100-ngram-default-e2b-s1", "mmlupro100-e2b-s1"),
            ("**CoPR**, width 3", "mmlupro100-ae-full-e2b-s1", "mmlupro100-lg-e2b-s1"),
            ("**CoPR**, repeat three days later", "mmlupro100-ae-full-r2-e2b-s1", "mmlupro100-lg-e2b-s1")]
    for name, run, ref in spec:
        path = os.path.join(pt.RUNS, run)
        sm, rep = pt.summary(path), pt.replies(path)
        g = sm["tokens"]["generated_tokens"]
        ex = "—" if not ref else "%d/100" % pt.identical(rep, pt.replies(os.path.join(pt.RUNS, ref)))
        rows.append([name, ex, f(pt.accuracy(rep), 0), f(sm["tokens"]["decode_tok_s"], 2),
                     f(sm["wall_s"] / 100, 1), f(sm["power"]["energy_j"] / g, 3),
                     f(sm["power"]["energy_above_idle_j"] / g, 3), f(sm["power"]["idle_w"], 2),
                     run_date(path)])
    s.append(table(["row", "exact", "acc %", "decode tok/s", "wall s/q", "J / tok", "above idle",
                    "idle W", "run"], rows))
    s.append("\n\"exact\": replies identical to the same engine without drafting. The paper prints "
             "0.225 and 0.370 for two of these cells; the data gives 0.224 and 0.369 (rounded twice).\n")

    s.append("\n### Table V — ablation, n=300 per row; every row byte-identical to little-gemma\n")
    rows = []
    for m in pt.MODELS:
        lg = pt.pooled_replies("lg-", m)
        for col in ("little-gemma", "+ prompt lookup", "+ prefix reuse", "CoPR"):
            p = pt.pooled(pt.ROW[col], m)
            same = "—" if col == "little-gemma" else "%d/300" % pt.identical(pt.pooled_replies(pt.ROW[col], m), lg)
            rows.append([m.upper(), LABEL[col] if col != "CoPR" else "+ both (**CoPR**)", f(p["decode"], 2),
                         pt.thousands(p["prompt_q"]), f(p["wall_q"], 1), f(p["j_tok"], 3), same])
    s.append(table(["model", "engine", "decode tok/s", "prompt tok / q", "wall s / q", "J / tok",
                    "replies = little-gemma"], rows, ["---", "---"] + ["---:"] * 5))

    s.append("\n### Table VI — verify width, 28 s1 questions (2 per subject)\n")
    plain_ms = 1000 / pt.sweep("ae-sweep-e2b-b0")["decode"]
    rows = []
    for b in (0, 2, 3, 4):
        e2, e4 = pt.sweep("ae-sweep-e2b-b%d" % b), pt.sweep("ae-sweep-e4b-b%d" % b)
        rows.append([b or "none", f(e2["decode"], 2), f(e2["j_tok"], 3), f(e4["decode"], 2), f(e4["j_tok"], 3),
                     f(e2["per_verify"], 2) if b else "—", f(e2["verify_ms"] / plain_ms, 2) if b else "1.00",
                     "%d/%d · %d/%d" % (e2["same"] + e4["same"])])
    s.append(table(["width", "E2B tok/s", "E2B J/tok", "E4B tok/s", "E4B J/tok", "+tokens / verify (E2B)",
                    "verify cost, plain steps (E2B)", "byte-identical E2B · E4B"], rows))
    rows = []
    for name in ("ae-sweep-e2b-b0-r2", "ae-sweep-e2b-b2-r2"):
        e = pt.sweep(name)
        rows.append([name, f(e["decode"], 2), f(e["j_tok"], 3), f(e["per_verify"], 2), "%d/%d" % e["same"]])
    s.append("\nRepeats of two E2B sweeps, not in the paper:\n\n")
    s.append(table(["run", "tok/s", "J/tok", "+tokens / verify", "byte-identical"], rows))

    s.append("\n### Table VIII — the same checkpoint and 300 questions on three devices\n")
    s.append(table(["device", "engine", "model", "accuracy %", "decode tok/s", "J / token"],
                   [r for r in devices()], ["---", "---", "---", "---:", "---:", "---:"]))
    s.append("\nPi rates are pooled over the two subsets with request logs (s2, s3); the iPhone's "
             "energy is a whole-phone battery estimate, not board DC power, and it ran thermally "
             "throttled. These rows compare deployments, not engines.\n")
    return "\n".join(s)


def devices():
    export = json.load(gzip.open(os.path.join(F, "export", "experiment-full.json.gz")))
    pi = export["boards"]["pi"]["runs"]
    pi_acc = {"e2b": ["mmlupro100-e2b", "mmlupro100-e2b-s2", "mmlupro100-e2b-s3"],
              "e4b": ["mmlupro100-e4b-s1", "mmlupro100-e4b-s2", "mmlupro100-e4b-s3"]}
    pi_rate = {"e2b": ["mmlupro100-e2b-s2", "mmlupro100-e2b-s3"], "e4b": ["mmlupro100-e4b-s2", "mmlupro100-e4b-s3"]}
    rows = []
    for m in pt.MODELS:
        c = pt.pooled("ae-full-", m)
        rows.append(["Jetson Orin Nano, 15 W", "CoPR", m.upper(), f(pt.accuracy(pt.pooled_replies("ae-full-", m)), 1),
                     f(c["decode"], 2), f(c["j_tok"], 3)])
        b = pt.pooled("", m)
        rows.append(["Jetson Orin Nano, 15 W", "llama.cpp", m.upper(), f(pt.accuracy(pt.pooled_replies("", m)), 1),
                     f(b["decode"], 2), f(b["j_tok"], 3)])
        acc = sum(pi[r]["summary"]["score"] for r in pi_acc[m]) / 3
        gt = sum(t["gt"] for r in pi_rate[m] for t in pi[r]["timeline"])
        gms = sum(t["gms"] for r in pi_rate[m] for t in pi[r]["timeline"])
        e = sum(pi[r]["summary_json"]["energy_wh"] * 3600 for r in pi_rate[m])
        rows.append(["Raspberry Pi 5 (CPU)", "llama.cpp", m.upper(), f(acc, 1), f(1000 * gt / gms, 2), f(e / gt, 3)])
        runs = [json.load(gzip.open(p)) for p in phone_current(m)]
        qs = [q for d in runs for q in d["questions"]]
        gt = sum(t["gt"] for d in runs for t in d["timeline"])
        gms = sum(t["gms"] for d in runs for t in d["timeline"])
        e = sum(d["device"]["energy_wh"] * 3600 for d in runs)
        gen = sum(d["device"]["gen_tokens"] for d in runs)
        rows.append(["iPhone 15 Pro", "MLX 4-bit", m.upper(), f(100 * sum(bool(q.get("ok")) for q in qs) / len(qs), 1),
                     f(1000 * gt / gms, 2), f(e / gen, 3) + " (battery est.)"])
    return rows


def phone_current(m):
    """The current (complete, latest) iPhone run per subset."""
    tag = "e2b" if m == "e2b" else "e4b-oq4"
    best = {}
    for p in sorted(glob.glob(os.path.join(F, "phone", "mmlupro-%s-s?-*.json.gz" % tag))):
        d = json.load(gzip.open(p))
        if d.get("status") == "done":
            best[d["subset"]] = p
    return [best[s] for s in sorted(best)]


def identity():
    s = ["## 2. Which engines give the same replies\n",
         "Replies byte-identical between two engines, out of 300 questions per model (Jetson, "
         "same weights and prompts). Greedy decoding on one engine is deterministic; across "
         "engines, kernels differ and greedy flips at near-ties.\n"]
    for m in pt.MODELS:
        reps = {c: pt.pooled_replies(pt.ROW[c], m) for c in ENGINES}
        rows = [[LABEL[a]] + [("%d" % pt.identical(reps[a], reps[b])) for b in ENGINES] for a in ENGINES]
        s.append("**%s**\n\n" % m.upper())
        s.append(table([""] + [LABEL[c] for c in ENGINES], rows) + "\n")
    return "\n".join(s)


def accuracy():
    s = ["## 3. Accuracy\n",
         "MMLU-Pro, 5-shot chain of thought, greedy, thinking off. ± is the 95% interval from "
         "question sampling (±9.7 points at n=100, ±5.6 at n=300); runs differ far less than "
         "that from one repeat to the next.\n",
         "### By subset\n"]
    rows = []
    for m in pt.MODELS:
        for col in ("llama.cpp", "llama.cpp+n-gram", "little-gemma", "CoPR"):
            per = [pt.accuracy(pt.replies(pt.run_dir(pt.ROW[col], m, s))) for s in pt.SUBSETS]
            rep = pt.pooled_replies(pt.ROW[col], m)
            rows.append(["Jetson", LABEL[col], m.upper()] + ["%.0f" % x for x in per] +
                        [pct(pt.accuracy(rep) / 100, 300)])
    export = json.load(gzip.open(os.path.join(F, "export", "experiment-full.json.gz")))
    pi = export["boards"]["pi"]["runs"]
    for m, names in (("e2b", ["mmlupro100-e2b", "mmlupro100-e2b-s2", "mmlupro100-e2b-s3"]),
                     ("e4b", ["mmlupro100-e4b-s1", "mmlupro100-e4b-s2", "mmlupro100-e4b-s3"])):
        per = [pi[n]["summary"]["score"] for n in names]
        rows.append(["Pi 5", "llama.cpp", m.upper()] + ["%.0f" % x for x in per] + [pct(sum(per) / 300, 300)])
    for m in pt.MODELS:
        runs = [json.load(gzip.open(p)) for p in phone_current(m)]
        per = [100 * sum(bool(q.get("ok")) for q in d["questions"]) / len(d["questions"]) for d in runs]
        rows.append(["iPhone", "MLX 4-bit", m.upper()] + ["%.0f" % x for x in per] + [pct(sum(per) / 300, 300)])
    s.append(table(["device", "engine", "model", "s1", "s2", "s3", "pooled % (95% CI)"], rows,
                   ["---", "---", "---", "---:", "---:", "---:", "---:"]))

    s.append("\n### Paired tests (exact two-sided McNemar, same question ids)\n")
    rows = []
    for m in pt.MODELS:
        base = pt.pooled_replies("", m)
        for col in ("llama.cpp+n-gram", "little-gemma", "CoPR"):
            rep = pt.pooled_replies(pt.ROW[col], m)
            p, x, y = pt.mcnemar(rep, base)
            rows.append([m.upper(), LABEL[col] + " vs llama.cpp", "%+.1f" % (pt.accuracy(rep) - pt.accuracy(base)),
                         x, y, f(p, 2)])
    s.append(table(["model", "comparison", "Δ points", "right only in first", "right only in llama.cpp", "p"], rows,
                   ["---", "---", "---:", "---:", "---:", "---:"]))

    s.append("\n### By subject, pooled s1–s3 (Jetson)\n")
    for m in pt.MODELS:
        counts = collections.OrderedDict()
        cols = ("llama.cpp", "little-gemma", "CoPR")
        for col in cols:
            for k, (_, ok) in pt.pooled_replies(pt.ROW[col], m).items():
                c = counts.setdefault(k[1], {x: [0, 0] for x in cols})
                c[col][0] += ok
                c[col][1] += 1
        rows = []
        for subj in sorted(counts):
            n = counts[subj]["llama.cpp"][1]
            rows.append([subj.replace("_", " "), n] + ["%d (%.0f%%)" % (counts[subj][c][0], 100 * counts[subj][c][0] / n)
                                                       for c in cols])
        ns = [counts[x]["llama.cpp"][1] for x in counts]
        s.append("**%s** — %d–%d questions per subject, so read these as indicative only.\n\n"
                 % (m.upper(), min(ns), max(ns)))
        s.append(table(["subject", "n", "llama.cpp", "little-gemma", "CoPR (= little-gemma)"], rows,
                       ["---", "---:", "---:", "---:", "---:"]) + "\n")
    return "\n".join(s)


def run_date(path):
    try:
        with open(os.path.join(path, "measured", "SOURCE")) as fh:
            m = re.search(r"(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)\d\d", fh.read())
        return "%s-%s-%s %s:%s" % m.groups() if m else "—"
    except OSError:
        return "—"


def fingerprint(path):
    try:
        with open(os.path.join(path, "queue", "fingerprint.json")) as fh:
            fp = json.load(fh)
    except OSError:
        return "hand-launched"
    ok = all(r.get("ok") for r in fp.get("diff", []))
    return ("ok · " if ok else "DIFF · ") + str(fp.get("baseline"))


def every_run():
    s = ["## 4. Every Jetson run in `findings/runs/jetson/`\n",
         "One row per run, straight from its `measured/summary.json` and samples. Runs from "
         "2026-10-07 19:30 on had the clocks pinned (CPU ~1,497 MHz instead of scaling), which "
         "adds 5–9% energy; compare their time, not their energy, with earlier rows. "
         "\"fingerprint\" is the live serving command line checked against `benchmark/baselines.json`; "
         "the S1 runs predate the queue and were launched by hand with the same flags.\n"]
    rows = []
    names = sorted(d for d in os.listdir(pt.RUNS) if d.startswith("mmlupro100-"))
    order = {"": 0, "ngram-n3m3-": 1, "ngram-n3m2-": 2, "ngram-default-": 3, "lg-": 4,
             "ae-full-": 5, "ae-full-r2-": 6, "ae-ngram-": 7, "ae-reuse-": 8}

    def key(n):
        rest = n[len("mmlupro100-"):]
        for row in sorted(order, key=len, reverse=True):
            if row and rest.startswith(row):
                return (order[row], rest)
        return (0, rest)
    for n in sorted(names, key=key):
        path = os.path.join(pt.RUNS, n)
        sm, rep = pt.summary(path), pt.replies(path)
        tk, pw, th = sm["tokens"], sm["power"], sm["thermal"]
        g = tk["generated_tokens"]
        rows.append(["`%s`" % n[len("mmlupro100-"):], run_date(path), "%.0f" % pt.accuracy(rep),
                     f(tk["decode_tok_s"], 2), f(tk["prefill_tok_s"], 0), "%.0f" % (tk["prompt_tokens"] / 100),
                     pt.thousands(g), f(sm["wall_s"] / 60, 1), f(pw["generation_mean_w"], 2),
                     f(pw["energy_j"] / g, 3), f(pw["energy_above_idle_j"] / g, 3), f(pw["idle_w"], 2),
                     f(th["temp_c"]["max"], 1), f(sm["utilisation"]["gpu_mhz"]["median"], 0),
                     f(th["cpu_mhz_mean"], 0), fingerprint(path)])
    s.append(table(["run", "started", "acc %", "decode tok/s", "prefill tok/s", "prompt tok/q", "gen. tokens",
                    "wall min", "W gen.", "J/tok", "above idle", "idle W", "peak °C", "GPU MHz", "CPU MHz",
                    "fingerprint"], rows, ["---", "---"] + ["---:"] * 13 + ["---"]))

    s.append("\n### Failed runs\n")
    rows = []
    for n in sorted(os.listdir(os.path.join(pt.RUNS, "failed"))):
        path = os.path.join(pt.RUNS, "failed", n)
        with gzip.open(os.path.join(path, "server.log.gz"), "rt", errors="replace") as fh:
            err = [ln.split("]: ", 1)[-1].strip() for ln in fh if "error:" in ln]
        rows.append(["`%s`" % n, run_date(path), err[-1] if err else "—"])
    s.append(table(["run", "started", "why it failed"], rows, ["---", "---", "---"]))
    s.append("\nAll six were rerun after the fix; the reruns are the `ae-reuse-*` rows above.\n")
    return "\n".join(s)


def other_devices():
    s = ["## 5. Pi 5 and iPhone, run by run\n", "### Raspberry Pi 5, llama.cpp `661643e` (CPU), from `findings/export/`\n"]
    export = json.load(gzip.open(os.path.join(F, "export", "experiment-full.json.gz")))
    rows = []
    for name, r in sorted(export["boards"]["pi"]["runs"].items()):
        if name == "mmlupro100-e4b":
            continue  # the same run as mmlupro100-e4b-s1, exported under its old name too
        sj, tl = r["summary_json"], r["timeline"]
        gt, gms = sum(t["gt"] for t in tl), sum(t["gms"] for t in tl)
        rows.append(["`%s`" % name, r.get("subset") or "s1", "%.0f" % r["summary"]["score"], r["summary"]["minutes"],
                     f(1000 * gt / gms, 2) if gms else "—", f(sj.get("mean_w"), 2), f(sj["energy_wh"], 2),
                     f(sj["energy_wh"] * 3600 / gt, 3) if gt else "—", f(sj.get("temp_max"), 0)])
    s.append(table(["run", "subset", "acc %", "minutes", "decode tok/s", "mean W", "Wh", "J / gen. token", "peak °C"],
                   rows, ["---", "---"] + ["---:"] * 7))
    s.append("\n### iPhone 15 Pro, MLX, every upload in `findings/phone/`\n")
    rows = []
    for p in sorted(glob.glob(os.path.join(F, "phone", "*.json.gz"))):
        d = json.load(gzip.open(p))
        dev = d.get("device") or {}
        qs = d["questions"]
        current = p in phone_current("e2b") + phone_current("e4b")
        status = "stopped (last live snapshot)" if d["status"] == "running" else d["status"]
        rows.append(["`%s`" % d["run"], d["subset"], status + (" (current)" if current else ""),
                     "%d/%d" % (sum(bool(q.get("ok")) for q in qs), len(qs)), f(dev.get("decode_tok_s"), 1),
                     f(dev.get("energy_wh"), 2) if dev.get("energy_wh") else "—",
                     f(dev.get("j_per_token"), 3) if dev.get("j_per_token") else "—", dev.get("thermal_max", "—")])
    s.append(table(["run", "subset", "status", "correct", "decode tok/s", "Wh (est.)", "J/tok (est.)",
                    "iOS thermal max"], rows, ["---", "---", "---", "---:", "---:", "---:", "---:", "---:"]))
    return "\n".join(s)


def gsm8k():
    s = ["## 6. tinyGSM8k (Pi 5, llama.cpp)\n",
         "100 items, IRT-estimated full-GSM8K accuracy. The 256-token cap is lm-eval's default and "
         "truncates chain of thought mid-solution; at 1,024 the same model scores 15 points higher.\n"]
    rows = []
    for d, model, cap in (("B-e2b", "E2B", "256"), ("tiny1024-e2b", "E2B", "1,024"), ("B-e4b", "E4B", "256")):
        r = json.load(open(glob.glob(os.path.join(F, "stdbench", d, "results_*.json"))[0]))["results"]["tinyGSM8k"]
        rows.append([model, cap, pct(r["exact_match,flexible-extract"]), pct(r["exact_match,strict-match"]), "`%s`" % d])
    s.append(table(["model", "answer cap", "flexible extract %", "strict match %", "data"], rows,
                   ["---", "---:", "---:", "---:", "---"]))
    return "\n".join(s)


def own_suite():
    out = io.StringIO()
    runs = report.load(os.path.join(ROOT, "benchmark", "results"))
    with contextlib.redirect_stdout(out):
        for name in ("t1", "t2", "t3", "t4"):
            getattr(report, name)(runs)
            print()
    body = re.sub(r"^## T", "### T", out.getvalue(), flags=re.M)
    return ("## 7. Own suite (Pi 5, not in the manuscript)\n\n"
            "The 10-case suite against five architectures, MTP × thinking and an E4B quantisation "
            "sweep, from `benchmark/results/*.json` via `benchmark/report.py`. Write-up: "
            "`findings/RESULTS.md` §2–§4.\n\n" + body.lstrip())


def issues():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        pt.issues()
    lines = out.getvalue().strip().splitlines()[1:]
    return ("## 8. Where the data and the manuscript disagree\n\n"
            "From `paper_tables.py --table issues`:\n\n```\n" + "\n".join(l[2:] for l in lines) + "\n```\n")


def build():
    parts = [
        "# Results tables\n",
        "Every result in this repository as tables, **generated from the committed data** by "
        "`python3 benchmark/results_tables.py`. Do not edit by hand: change the data or the "
        "script and regenerate. The write-up and interpretation are in [`RESULTS.md`](RESULTS.md); "
        "which experiments exist and where their data lives is in "
        "[`../docs/experiments.md`](../docs/experiments.md).\n",
        "**Names.** CoPR is the paper's name for the proposed engine; run names call it `ae` "
        "(S9). `lg` is little-gemma (S3), `ngram-n3m3` is llama.cpp's n-gram drafting at width 4 "
        "(S10), an empty row name is plain llama.cpp (S1). Power is board DC draw (INA3221 on the "
        "Jetson, PMIC on the Pi), not wall power.\n",
        "**Contents.** 1 · the manuscript's tables — 2 · reply identity between engines — "
        "3 · accuracy by subset, paired tests, by subject — 4 · every Jetson run — "
        "5 · Pi and iPhone runs — 6 · tinyGSM8k — 7 · own suite — 8 · data vs manuscript\n",
        manuscript(), identity(), accuracy(), every_run(), other_devices(), gsm8k(), own_suite(), issues(),
    ]
    text = "\n".join(p.rstrip() + "\n" for p in parts)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    # report.py names the directory it read; keep the file machine-independent
    return text.replace(os.path.join(ROOT, "benchmark", "results"), "benchmark/results")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if findings/TABLES.md is out of date")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    text = build()
    if args.check:
        try:
            with open(args.out) as fh:
                same = fh.read() == text
        except OSError:
            same = False
        print("findings/TABLES.md is %s" % ("up to date" if same else "OUT OF DATE — run benchmark/results_tables.py"))
        return 0 if same else 1
    with open(args.out, "w") as fh:
        fh.write(text)
    print("wrote %s (%d lines)" % (os.path.relpath(args.out, ROOT), text.count("\n")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
