#!/usr/bin/env python3
"""Every result in the repository as tables, generated from the committed
data and nothing else: findings/TABLES.md (markdown) and findings/tables/
(one image per table, SVG plus a 2x PNG).

    python3 benchmark/results_tables.py            # rewrite TABLES.md and the images
    python3 benchmark/results_tables.py --check    # exit 1 if any of it is out of date

Sources, all under findings/ unless noted:
    runs/jetson/         the manuscript's Jetson runs (collect_runs.py)
    export/              the Pi's MMLU-Pro baseline runs
    phone/               the iPhone runs
    stdbench/            tinyGSM8k (Pi)
    benchmark/results/   the own suite (rendered by report.py, markdown only)

The manuscript's own tables are rebuilt by the same functions paper_tables.py
checks against the paper, and laid out the way the paper lays them out, so
the two cannot disagree. Each table is built once (table_render.Tab) and
written both ways. PNGs need headless Chrome; --check compares the markdown
and the SVGs only. Stdlib only.
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
from table_render import Tab, png  # noqa: E402

ROOT = pt.ROOT
F = os.path.join(ROOT, "findings")
OUT = os.path.join(F, "TABLES.md")
IMG = os.path.join(F, "tables")
COLS = ("llama.cpp", "llama.cpp+n-gram", "little-gemma", "CoPR")
ENGINES = COLS + ("+ prompt lookup", "+ prefix reuse")
SHORT = {"llama.cpp": "llama.cpp", "llama.cpp+n-gram": "llama.cpp+n-gram", "little-gemma": "little-gemma",
         "CoPR": "CoPR (ours)", "+ prompt lookup": "+ prompt lookup", "+ prefix reuse": "+ prefix reuse"}
LABEL = {"llama.cpp": "llama.cpp", "llama.cpp+n-gram": "llama.cpp + n-gram (width 4)",
         "little-gemma": "little-gemma", "CoPR": "CoPR (ours)",
         "+ prompt lookup": "little-gemma + prompt lookup", "+ prefix reuse": "little-gemma + prefix reuse"}


def ci95(p, n):
    return 196 * math.sqrt(p * (1 - p) / n)  # in points, normal approximation


def pct(p, n=None):
    return "%.1f" % (100 * p) if n is None else "%.1f ± %.1f" % (100 * p, ci95(p, n))


def f(x, nd):
    return "—" if x is None else "%.*f" % (nd, x)


def num(s):
    try:
        return float(str(s).replace(",", "").replace("**", "").split()[0])
    except (ValueError, IndexError):
        return None


def best(rows, cells, lower=True):
    """{(row, col)} of the best value among the given (row, col) cells."""
    vals = [(num(rows[r][c]), (r, c)) for r, c in cells if num(rows[r][c]) is not None]
    if not vals:
        return set()
    target = (min if lower else max)(v for v, _ in vals)
    return {rc for v, rc in vals if v == target}


# ------------------------------------------------------------ the manuscript's tables

def t1():
    rows = [["Generated tokens"], ["Decode rate (tok/s)"], ["Prompt tokens prefilled / question"],
            ["Share of request time in prefill (%)"], ["Accuracy (%)"]]
    for col in ("llama.cpp", "little-gemma"):
        p, rep = pt.pooled(pt.ROW[col], "e2b"), pt.pooled_replies(pt.ROW[col], "e2b")
        for i, v in enumerate((pt.thousands(p["gen"]), f(p["decode"], 2), pt.thousands(p["prompt_q"]),
                               f(p["prefill_share"], 1), f(pt.accuracy(rep), 1))):
            rows[i].append(v)
    return Tab("table1", "Table I — Baseline anatomy, E2B, Jetson at 15 W",
               ["", "llama.cpp", "little-gemma"], rows,
               caption="Gemma 4 E2B on the Jetson Orin Nano 8 GB at 15 W, 300 MMLU-Pro questions (s1–s3).")


def t3():
    metrics = ["Accuracy (%)", "Replies identical to little-gemma", "Decode (tok/s)", "Prompt tokens processed / q",
               "Wall time / question (s)", "Mean power, generating (W)", "Energy / gen. token (J)", "  above idle (J)"]
    rows = [[m] for m in metrics]
    for m in pt.MODELS:
        lg, base = pt.pooled_replies("lg-", m), pt.pooled_replies("", m)
        for col in COLS:
            p, rep = pt.pooled(pt.ROW[col], m), pt.pooled_replies(pt.ROW[col], m)
            if col == "little-gemma":
                same = "–"
            elif col == "llama.cpp+n-gram":
                same = "%d/300ᶠ" % pt.identical(rep, base)
            elif col == "llama.cpp":
                same = "%d/300" % pt.identical(rep, lg)
            else:
                same = "%d/300" % pt.identical(rep, lg)
            for i, v in enumerate((f(pt.accuracy(rep), 1), same, f(p["decode"], 2), pt.thousands(p["prompt_q"]),
                                   f(p["wall_q"], 1), f(p["gen_w"], 2), f(p["j_tok"], 3), f(p["j_tok_idle"], 3))):
                rows[i].append(v)
    bold = set()
    for i, lower in ((2, False), (3, True), (4, True), (5, True), (6, True), (7, True)):
        for g in (range(1, 5), range(5, 9)):
            bold |= best(rows, [(i, c) for c in g], lower)
    return Tab("table3", "Table III — Engines on the Jetson Orin Nano 8 GB at 15 W, MMLU-Pro, n=300 per cell",
               [""] + [SHORT[c] for c in COLS] * 2, rows, shade=(4, 8), bold=bold,
               groups=[("", 1), ("Gemma 4 E2B", 4), ("Gemma 4 E4B", 4)],
               caption="Energy is board DC energy over the working window per generated token. Bold: best in row "
                       "within a model; shaded: the proposed system. Accuracy is not bolded: all engines are "
                       "statistically tied. llama.cpp+n-gram is llama.cpp's own drafting at width 4 (not exact). "
                       "ᶠ identical to llama.cpp without drafting, not to little-gemma. Replies identical are "
                       "pooled over s1–s3 (the paper's 12/100 is s1 alone).")


T4_SPEC = [("llama.cpp, no drafting", "mmlupro100-e2b-s1", None),
           ("llama.cpp n-gram, width 3 ✝", "mmlupro100-ngram-n3m2-e2b-s1", "mmlupro100-e2b-s1"),
           ("llama.cpp n-gram, width 4", "mmlupro100-ngram-n3m3-e2b-s1", "mmlupro100-e2b-s1"),
           ("llama.cpp n-gram, stock", "mmlupro100-ngram-default-e2b-s1", "mmlupro100-e2b-s1"),
           ("CoPR (ours), width 3", "mmlupro100-ae-full-e2b-s1", "mmlupro100-lg-e2b-s1"),
           ("CoPR (ours), repeat", "mmlupro100-ae-full-r2-e2b-s1", "mmlupro100-lg-e2b-s1")]


def t4():
    rows = []
    for name, run, ref in T4_SPEC:
        path = os.path.join(pt.RUNS, run)
        sm, rep = pt.summary(path), pt.replies(path)
        g = sm["tokens"]["generated_tokens"]
        ex = "–" if not ref else "%d/100" % pt.identical(rep, pt.replies(os.path.join(pt.RUNS, ref)))
        rows.append([name, ex, f(pt.accuracy(rep), 0), f(sm["tokens"]["decode_tok_s"], 2), f(sm["wall_s"] / 100, 1),
                     f(sm["power"]["energy_j"] / g, 3), f(sm["power"]["energy_above_idle_j"] / g, 3),
                     f(sm["power"]["idle_w"], 2), run_date(path)[:10]])
    bold = set()
    for c, lower in ((3, False), (4, True), (5, True), (6, True)):
        bold |= best(rows, [(r, c) for r in range(len(rows))], lower)
    return Tab("table4", "Table IV — llama.cpp's own n-gram drafting against CoPR, E2B, subset s1 (n=100)",
               ["", "Exact", "Acc. (%)", "Decode tok/s", "Wall s/q", "J/tok", "above idle", "idle W", "run"],
               rows, shade_rows=(4, 5), bold=bold,
               caption="Exact: replies identical to the same engine without drafting. Bold: best per column; "
                       "accuracy not bolded (all tied). Rows of the same date share the board's idle floor. "
                       "✝ This run never drafted (no draft-acceptance line in any of its 100 requests): it is a "
                       "plain llama.cpp rerun. The paper prints 0.225 and 0.370 for the width-4 'above idle' and "
                       "CoPR 'J/tok' cells; the data gives 0.224 and 0.369 (the paper rounded twice).")


def t5():
    rows, bold, shade = [], set(), []
    for m in pt.MODELS:
        rows.append(("group", "Gemma 4 %s" % m.upper()))
        lg = pt.pooled_replies("lg-", m)
        first = len(rows)
        for col in ("little-gemma", "+ prompt lookup", "+ prefix reuse", "CoPR"):
            p = pt.pooled(pt.ROW[col], m)
            same = "–" if col == "little-gemma" else "%d/300" % pt.identical(pt.pooled_replies(pt.ROW[col], m), lg)
            rows.append(["little-gemma (no switches)" if col == "little-gemma" else
                         "+ both (CoPR, ours)" if col == "CoPR" else col,
                         f(p["decode"], 2), pt.thousands(p["prompt_q"]), f(p["wall_q"], 1), f(p["j_tok"], 3), same])
        shade.append(len(rows) - 1)
        for c, lower in ((1, False), (2, True), (3, True), (4, True)):
            bold |= best(rows, [(r, c) for r in range(first, len(rows))], lower)
    return Tab("table5", "Table V — Ablation, n=300 per row; every row byte-identical to little-gemma",
               ["", "Decode (tok/s)", "Prompt tok / q", "Wall s / q", "J / tok", "= little-gemma"],
               rows, shade_rows=shade, bold=bold,
               caption="The first row of each model is little-gemma (S3); CoPR with every switch off reproduces it "
                       "byte for byte. Bold: best per column within a model. The prefix-reuse rows ran on "
                       "2026-10-07/08 with the Jetson's clocks pinned (+5–9% energy).")


def t6():
    plain_ms = 1000 / pt.sweep("ae-sweep-e2b-b0")["decode"]
    rows = []
    for b in (0, 2, 3, 4):
        e2, e4 = pt.sweep("ae-sweep-e2b-b%d" % b), pt.sweep("ae-sweep-e4b-b%d" % b)
        rows.append([str(b) if b else "none", f(e2["decode"], 2), f(e2["j_tok"], 3), f(e4["decode"], 2),
                     f(e4["j_tok"], 3), f(e2["per_verify"], 2) if b else "–",
                     f(e2["verify_ms"] / plain_ms, 2) if b else "1.00"])
    full = []
    for m in pt.MODELS:
        c = pt.pooled("ae-full-", m)
        full += [f(c["decode"], 2), f(c["j_tok"], 3)]
    rows.append(["3, n=300"] + full + ["–", "–"])
    bold = set()
    for c, lower in ((1, False), (2, True), (3, False), (4, True)):
        bold |= best(rows, [(r, c) for r in range(4)], lower)
    return Tab("table6", "Table VI — Verify-width selection, 28 s1 questions per row",
               ["Width", "tok/s", "J/tok", "tok/s", "J/tok", "+tokens", "cost"], rows,
               groups=[("", 1), ("E2B", 2), ("E4B", 2), ("per verify (E2B)", 2)], shade_rows=(2,), bold=bold,
               caption="2 questions per subject. CoPR -reuse -ngram; all 224 replies byte-identical to little-gemma. +tokens: extra tokens "
                       "a verify pass confirms; cost: a verify pass in plain decode steps. Last row: the chosen "
                       "width over all 300 questions (Table III).")


def t8():
    export = json.load(gzip.open(os.path.join(F, "export", "experiment-full.json.gz")))
    pi = export["boards"]["pi"]["runs"]
    pi_acc = {"e2b": ["mmlupro100-e2b", "mmlupro100-e2b-s2", "mmlupro100-e2b-s3"],
              "e4b": ["mmlupro100-e4b-s1", "mmlupro100-e4b-s2", "mmlupro100-e4b-s3"]}
    pi_rate = {"e2b": ["mmlupro100-e2b-s2", "mmlupro100-e2b-s3"], "e4b": ["mmlupro100-e4b-s2", "mmlupro100-e4b-s3"]}
    rows, shade = [], []
    for m in pt.MODELS:
        rows.append(("group", "Gemma 4 %s" % m.upper()))
        c = pt.pooled("ae-full-", m)
        rows.append(["Jetson Orin Nano, 15 W", "CoPR (ours)", f(pt.accuracy(pt.pooled_replies("ae-full-", m)), 1),
                     f(c["decode"], 2), f(c["j_tok"], 3)])
        shade.append(len(rows) - 1)
        acc = sum(pi[r]["summary"]["score"] for r in pi_acc[m]) / 3
        gt = sum(t["gt"] for r in pi_rate[m] for t in pi[r]["timeline"])
        gms = sum(t["gms"] for r in pi_rate[m] for t in pi[r]["timeline"])
        e = sum(pi[r]["summary_json"]["energy_wh"] * 3600 for r in pi_rate[m])
        rows.append(["Raspberry Pi 5 (CPU)", "llama.cpp", f(acc, 1), "%sᵃ" % f(1000 * gt / gms, 2), f(e / gt, 3)])
        runs = [json.load(gzip.open(p)) for p in phone_current(m)]
        qs = [q for d in runs for q in d["questions"]]
        gt = sum(t["gt"] for d in runs for t in d["timeline"])
        gms = sum(t["gms"] for d in runs for t in d["timeline"])
        e = sum(d["device"]["energy_wh"] * 3600 for d in runs)
        gen = sum(d["device"]["gen_tokens"] for d in runs)
        rows.append(["iPhone 15 Pro", "MLXᵈ", f(100 * sum(bool(q.get("ok")) for q in qs) / len(qs), 1),
                     "%sᵉ" % f(1000 * gt / gms, 2), "%sᵇ" % f(e / gen, 3)])
    return Tab("table8", "Table VIII — Same checkpoint and 300 questions on other edge devices", ["Device", "Engine", "Acc. (%)", "tok/s", "J/tok"], rows,
               shade_rows=shade,
               caption="Deployment context, not an engine comparison. ᵃ Pi rates pooled over the two subsets with request logs (n=200). ᵇ Whole-phone battery "
                       "estimate (battery % × capacity, 1% steps, screen on), not board DC: not comparable. "
                       "ᵈ MLX 4-bit builds of the same QAT checkpoints. ᵉ Thermally throttled: iOS state ≥2 for "
                       "most of each run.")


def phone_current(m):
    """The current (complete, latest) iPhone run per subset."""
    tag = "e2b" if m == "e2b" else "e4b-oq4"
    latest = {}
    for p in sorted(glob.glob(os.path.join(F, "phone", "mmlupro-%s-s?-*.json.gz" % tag))):
        d = json.load(gzip.open(p))
        if d.get("status") == "done":
            latest[d["subset"]] = p
    return [latest[s] for s in sorted(latest)]


# ------------------------------------------------------------ beyond the paper

def t_identity(m):
    reps = {c: pt.pooled_replies(pt.ROW[c], m) for c in ENGINES}
    rows = [[LABEL[a]] + ["%d" % pt.identical(reps[a], reps[b]) for b in ENGINES] for a in ENGINES]
    return Tab("identity-%s" % m, "Replies byte-identical between engines, Gemma 4 %s (of 300)" % m.upper(),
               [""] + [SHORT[c] for c in ENGINES], rows, shade=(4,),
               caption="Jetson Orin Nano, same weights and prompts, s1–s3 pooled. Greedy decoding is deterministic "
                       "within one engine; across engines the kernels differ and greedy flips at near-ties.")


def t_subsets():
    rows = []
    for m in pt.MODELS:
        rows.append(("group", "Gemma 4 %s" % m.upper()))
        for col in COLS:
            per = [pt.accuracy(pt.replies(pt.run_dir(pt.ROW[col], m, s))) for s in pt.SUBSETS]
            rep = pt.pooled_replies(pt.ROW[col], m)
            rows.append(["Jetson · " + LABEL[col]] + ["%.0f" % x for x in per] + [pct(pt.accuracy(rep) / 100, 300)])
        export = json.load(gzip.open(os.path.join(F, "export", "experiment-full.json.gz")))
        pi = export["boards"]["pi"]["runs"]
        names = {"e2b": ["mmlupro100-e2b", "mmlupro100-e2b-s2", "mmlupro100-e2b-s3"],
                 "e4b": ["mmlupro100-e4b-s1", "mmlupro100-e4b-s2", "mmlupro100-e4b-s3"]}[m]
        per = [pi[n]["summary"]["score"] for n in names]
        rows.append(["Pi 5 · llama.cpp"] + ["%.0f" % x for x in per] + [pct(sum(per) / 300, 300)])
        runs = [json.load(gzip.open(p)) for p in phone_current(m)]
        per = [100 * sum(bool(q.get("ok")) for q in d["questions"]) / len(d["questions"]) for d in runs]
        rows.append(["iPhone · MLX 4-bit"] + ["%.0f" % x for x in per] + [pct(sum(per) / 300, 300)])
    shade = [i for i, r in enumerate(rows) if not isinstance(r, tuple) and "CoPR" in r[0]]
    return Tab("accuracy-subsets", "MMLU-Pro accuracy by subset (%), every device",
               ["", "s1", "s2", "s3", "pooled (95% CI)"], rows, shade_rows=shade,
               caption="5-shot chain of thought, greedy, thinking off, n=100 per subset. ± is the 95% interval from "
                       "question sampling; repeating the same questions moves a score by about one point.")


def t_paired():
    rows = []
    for m in pt.MODELS:
        base = pt.pooled_replies("", m)
        for col in ("llama.cpp+n-gram", "little-gemma", "CoPR"):
            rep = pt.pooled_replies(pt.ROW[col], m)
            p, x, y = pt.mcnemar(rep, base)
            rows.append([m.upper(), LABEL[col], "%+.1f" % (pt.accuracy(rep) - pt.accuracy(base)), str(x), str(y), f(p, 2)])
    return Tab("paired-tests", "Paired accuracy tests against llama.cpp (exact two-sided McNemar, n=300)",
               ["Model", "Engine", "Δ points", "right only here", "right only in llama.cpp", "p"], rows,
               shade_rows=[i for i, r in enumerate(rows) if "CoPR" in r[1]],
               caption="Same question ids on the same board. No difference is significant.")


def t_subjects(m):
    counts = collections.OrderedDict()
    cols = ("llama.cpp", "little-gemma")
    for col in cols:
        for k, (_, ok) in pt.pooled_replies(pt.ROW[col], m).items():
            c = counts.setdefault(k[1], {x: [0, 0] for x in cols})
            c[col][0] += ok
            c[col][1] += 1
    rows = []
    for subj in sorted(counts):
        n = counts[subj]["llama.cpp"][1]
        rows.append([subj.replace("_", " "), str(n)] +
                    ["%d (%.0f%%)" % (counts[subj][c][0], 100 * counts[subj][c][0] / n) for c in cols])
    ns = [counts[x]["llama.cpp"][1] for x in counts]
    return Tab("subjects-%s" % m, "MMLU-Pro accuracy by subject, Gemma 4 %s, Jetson, s1–s3 pooled" % m.upper(),
               ["Subject", "n", "llama.cpp", "little-gemma = CoPR"], rows,
               caption="%d–%d questions per subject: indicative only. CoPR's replies are byte-identical to "
                       "little-gemma's, so its column is the same." % (min(ns), max(ns)))


def run_date(path):
    try:
        with open(os.path.join(path, "measured", "SOURCE")) as fh:
            mt = re.search(r"(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)\d\d", fh.read())
        return "%s-%s-%s %s:%s" % mt.groups() if mt else "—"
    except OSError:
        return "—"


def fingerprint(path):
    try:
        with open(os.path.join(path, "queue", "fingerprint.json")) as fh:
            fp = json.load(fh)
    except OSError:
        return "by hand"
    return ("ok · " if all(r.get("ok") for r in fp.get("diff", [])) else "DIFF · ") + str(fp.get("baseline"))


ORDER = {"": 0, "ngram-n3m3-": 1, "ngram-n3m2-": 2, "ngram-default-": 3, "lg-": 4,
         "ae-full-": 5, "ae-full-r2-": 6, "ae-ngram-": 7, "ae-reuse-": 8}


def _run_key(n):
    rest = n[len("mmlupro100-"):]
    for row in sorted(ORDER, key=len, reverse=True):
        if row and rest.startswith(row):
            return (ORDER[row], rest)
    return (0, rest)


def t_runs():
    rows, shade = [], []
    names = sorted((d for d in os.listdir(pt.RUNS) if d.startswith("mmlupro100-")), key=_run_key)
    for n in names:
        path = os.path.join(pt.RUNS, n)
        sm, rep = pt.summary(path), pt.replies(path)
        tk, pw, th = sm["tokens"], sm["power"], sm["thermal"]
        g = tk["generated_tokens"]
        rows.append([n[len("mmlupro100-"):], run_date(path), "%.0f" % pt.accuracy(rep), f(tk["decode_tok_s"], 2),
                     f(tk["prefill_tok_s"], 0), "%.0f" % (tk["prompt_tokens"] / 100), pt.thousands(g),
                     f(sm["wall_s"] / 60, 1), f(pw["generation_mean_w"], 2), f(pw["energy_j"] / g, 3),
                     f(pw["energy_above_idle_j"] / g, 3), f(pw["idle_w"], 2), f(th["temp_c"]["max"], 1),
                     f(sm["utilisation"]["gpu_mhz"]["median"], 0), f(th["cpu_mhz_mean"], 0), fingerprint(path)])
        if n.startswith("mmlupro100-ae-full-"):
            shade.append(len(rows) - 1)
    return Tab("jetson-runs", "Every Jetson run in findings/runs/jetson/ (MMLU-Pro, one subset each)",
               ["Run", "Started", "Acc %", "Decode tok/s", "Prefill tok/s", "Prompt tok/q", "Gen. tokens", "Wall min",
                "W gen.", "J/tok", "above idle", "Idle W", "Peak °C", "GPU MHz", "CPU MHz", "Fingerprint"],
               rows, shade_rows=shade,
               caption="Run names: (empty) llama.cpp · ngram-n3m3 llama.cpp n-gram width 4 · lg little-gemma · "
                       "ae-full CoPR · ae-ngram / ae-reuse CoPR's single switches. Runs from 2026-10-07 19:30 on "
                       "had the clocks pinned (CPU ~1,497 MHz): compare their time, not their energy, with earlier "
                       "rows. Fingerprint: the live serving command line checked against benchmark/baselines.json; "
                       "the llama.cpp baseline runs predate the queue and were launched by hand with the same flags.")


def t_failed():
    rows = []
    for n in sorted(os.listdir(os.path.join(pt.RUNS, "failed"))):
        path = os.path.join(pt.RUNS, "failed", n)
        with gzip.open(os.path.join(path, "server.log.gz"), "rt", errors="replace") as fh:
            err = [ln.split("]: ", 1)[-1].strip() for ln in fh if "error:" in ln]
        rows.append([n, run_date(path), err[-1] if err else "—"])
    return Tab("failed-runs", "Failed runs (archived, rerun after the fix)", ["Run", "Started", "Why it failed"], rows,
               caption="All six were rerun after the fix; the reruns are the ae-reuse rows of the run table.")


def t_pi():
    export = json.load(gzip.open(os.path.join(F, "export", "experiment-full.json.gz")))
    rows = []
    for name, r in sorted(export["boards"]["pi"]["runs"].items()):
        if name == "mmlupro100-e4b":
            continue  # the same run as mmlupro100-e4b-s1, exported under its old name too
        sj, tl = r["summary_json"], r["timeline"]
        gt, gms = sum(t["gt"] for t in tl), sum(t["gms"] for t in tl)
        rows.append([name, r.get("subset") or "s1", "%.0f" % r["summary"]["score"], str(r["summary"]["minutes"]),
                     f(1000 * gt / gms, 2) if gms else "—", f(sj.get("mean_w"), 2), f(sj["energy_wh"], 2),
                     f(sj["energy_wh"] * 3600 / gt, 3) if gt else "—", f(sj.get("temp_max"), 0)])
    return Tab("pi-runs", "Raspberry Pi 5, llama.cpp 661643e (CPU): every MMLU-Pro baseline run",
               ["Run", "Subset", "Acc %", "Minutes", "Decode tok/s", "Mean W", "Wh", "J / gen. token", "Peak °C"], rows,
               caption="From findings/export/. Board DC power from the PMIC rails, not wall power.")


def t_phone():
    rows = []
    cur = phone_current("e2b") + phone_current("e4b")
    for p in sorted(glob.glob(os.path.join(F, "phone", "*.json.gz"))):
        d = json.load(gzip.open(p))
        dev, qs = d.get("device") or {}, d["questions"]
        status = "stopped (last snapshot)" if d["status"] == "running" else d["status"]
        rows.append([d["run"], d["subset"], status + (" · current" if p in cur else ""),
                     "%d/%d" % (sum(bool(q.get("ok")) for q in qs), len(qs)), f(dev.get("decode_tok_s"), 1),
                     f(dev.get("energy_wh"), 2) if dev.get("energy_wh") else "—",
                     f(dev.get("j_per_token"), 3) if dev.get("j_per_token") else "—", str(dev.get("thermal_max", "—"))])
    return Tab("iphone-runs", "iPhone 15 Pro, MLX: every upload", ["Run", "Subset", "Status", "Correct", "Decode tok/s",
               "Wh (est.)", "J/tok (est.)", "iOS thermal max"], rows,
               caption="Energy is a whole-phone battery estimate, not board DC power. Stopped runs are kept as their "
                       "last live snapshot.")


def t_gsm8k():
    rows = []
    for d, model, cap in (("B-e2b", "E2B", "256"), ("tiny1024-e2b", "E2B", "1,024"), ("B-e4b", "E4B", "256")):
        r = json.load(open(glob.glob(os.path.join(F, "stdbench", d, "results_*.json"))[0]))["results"]["tinyGSM8k"]
        rows.append([model, cap, pct(r["exact_match,flexible-extract"]), pct(r["exact_match,strict-match"]), d])
    return Tab("tinygsm8k", "tinyGSM8k on the Raspberry Pi 5 (llama.cpp), IRT-estimated GSM8K accuracy (%)",
               ["Model", "Answer cap", "Flexible extract", "Strict match", "Data"], rows,
               caption="100 items. lm-eval's default 256-token cap truncates chain of thought mid-solution; at "
                       "1,024 the same model scores 15 points higher.")


# ------------------------------------------------------------ the document

def own_suite():
    out = io.StringIO()
    runs = report.load(os.path.join(ROOT, "benchmark", "results"))
    with contextlib.redirect_stdout(out):
        for name in ("t1", "t2", "t3", "t4"):
            getattr(report, name)(runs)
            print()
    return re.sub(r"^## T", "### T", out.getvalue(), flags=re.M).lstrip()


def issues():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        pt.issues()
    lines = out.getvalue().strip().splitlines()[1:]
    return "```\n" + "\n".join(l[2:] for l in lines) + "\n```\n"


def tables():
    return {"paper": [t1(), t3(), t4(), t5(), t6(), t8()],
            "identity": [t_identity("e2b"), t_identity("e4b")],
            "accuracy": [t_subsets(), t_paired(), t_subjects("e2b"), t_subjects("e4b")],
            "runs": [t_runs(), t_failed()],
            "devices": [t_pi(), t_phone()],
            "gsm8k": [t_gsm8k()]}


def section(tabs):
    out = []
    for t in tabs:
        out.append("### %s\n\n![%s](tables/%s.svg)\n\n<details><summary>as text</summary>\n\n%s\n</details>\n"
                   % (t.title, t.name, t.name, t.md()))
    return "\n".join(out)


def build():
    T = tables()
    parts = [
        "# Results tables\n",
        "Every result in this repository as tables, **generated from the committed data** by "
        "`python3 benchmark/results_tables.py`. Each table is an image (`tables/<name>.svg`, with a 2x "
        "`.png` beside it for slides and papers) and the same table as text under *as text*. Do not edit by "
        "hand: change the data or the script and regenerate. Interpretation is in [`RESULTS.md`](RESULTS.md); "
        "which experiments exist and where their data lives is in [`../docs/experiments.md`](../docs/experiments.md).\n",
        "**Names.** CoPR is the paper's name for the proposed engine; run names call it `ae` (S9). `lg` is "
        "little-gemma (S3), `ngram-n3m3` is llama.cpp's n-gram drafting at width 4 (S10), an empty row name is "
        "plain llama.cpp (S1). Power is board DC draw (INA3221 on the Jetson, PMIC on the Pi), not wall power.\n",
        "**Contents.** 1 · the manuscript's tables — 2 · reply identity between engines — 3 · accuracy — "
        "4 · every Jetson run — 5 · Pi and iPhone runs — 6 · tinyGSM8k — 7 · own suite — 8 · data vs manuscript\n",
        "## 1. The manuscript's tables, from the data\n",
        "Rebuilt from `findings/runs/jetson/` by the functions `paper_tables.py` checks against the paper "
        "(203 values match), in the paper's layout. Table VII (the replay) follows once its token cache is filled.\n",
        section(T["paper"]),
        "## 2. Which engines give the same replies\n", section(T["identity"]),
        "## 3. Accuracy\n", section(T["accuracy"]),
        "## 4. Every Jetson run\n", section(T["runs"]),
        "## 5. Pi 5 and iPhone, run by run\n", section(T["devices"]),
        "## 6. tinyGSM8k\n", section(T["gsm8k"]),
        "## 7. Own suite (Pi 5, not in the manuscript)\n\n"
        "The 10-case suite against five architectures, MTP × thinking and an E4B quantisation sweep, from "
        "`benchmark/results/*.json` via `benchmark/report.py` (text only). Write-up: `RESULTS.md` §2–§4.\n",
        own_suite(),
        "## 8. Where the data and the manuscript disagree\n\nFrom `paper_tables.py --table issues`:\n",
        issues(),
    ]
    text = "\n".join(p.rstrip() + "\n" for p in parts)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    text = text.replace(os.path.join(ROOT, "benchmark", "results"), "benchmark/results")
    svgs = {t.name: t.svg() for group in T.values() for t in group}
    return text, svgs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if TABLES.md or an SVG is out of date")
    ap.add_argument("--no-png", action="store_true", help="skip the PNGs (they need headless Chrome)")
    args = ap.parse_args()
    text, svgs = build()
    if args.check:
        stale = []
        try:
            with open(OUT) as fh:
                if fh.read() != text:
                    stale.append("TABLES.md")
        except OSError:
            stale.append("TABLES.md")
        for name, (svg, _) in svgs.items():
            p = os.path.join(IMG, name + ".svg")
            if not os.path.exists(p) or open(p).read() != svg:
                stale.append("tables/%s.svg" % name)
        print("findings/ tables are " + ("up to date" if not stale else
                                         "OUT OF DATE (%s) — run benchmark/results_tables.py" % ", ".join(stale)))
        return 1 if stale else 0
    os.makedirs(IMG, exist_ok=True)
    with open(OUT, "w") as fh:
        fh.write(text)
    made = 0
    for name, (svg, size) in svgs.items():
        p = os.path.join(IMG, name + ".svg")
        with open(p, "w") as fh:
            fh.write(svg)
        if not args.no_png:
            made += png(p, size, os.path.join(IMG, name + ".png"))
    print("wrote findings/TABLES.md and %d images in findings/tables/ (%d PNG)" % (len(svgs), made))
    return 0


if __name__ == "__main__":
    sys.exit(main())
