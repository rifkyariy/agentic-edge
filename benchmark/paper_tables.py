#!/usr/bin/env python3
"""Rebuild the manuscript's tables from the data committed under findings/,
and check every number against the paper.

    python3 benchmark/paper_tables.py            # all tables, with checks
    python3 benchmark/paper_tables.py --table 3  # one table

"Never Compute Twice: Exact-Output Speedups for Gemma 4 on Edge Devices".
Every figure below is recomputed from raw per-run files — lm-eval samples,
run_measured.sh summaries and telemetry, engine logs — never copied from the
text. Each line prints the paper's value next to the recomputed one; the exit
status is 1 if any differs at the paper's precision.

Inputs (see README.md, "Reproducing the paper"):
    findings/runs/jetson/<run>/      the Jetson runs (collect_runs.py --paper)
    findings/export/                 the Pi baseline runs (Table VIII)
    findings/phone/                  the iPhone runs (Table VIII)

Not rebuilt here: Table VII and the Sec. III replay figures, which
replay_lookup.py computes once its token cache is filled, and the Pi
batched-verify costs of Sec. VII, whose llama-batched-bench output is still
only on the Pi. Stdlib only.
"""
import argparse
import csv
import gzip
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, "findings", "runs", "jetson")
SUBSETS = ("s1", "s2", "s3")
MODELS = ("e2b", "e4b")
# Table columns -> the run-name row each engine writes (std_mmlupro_jetson.sh,
# std_mmlupro_lg_jetson.sh): mmlupro100-<row><model>-<subset>
ROW = {"llama.cpp": "", "llama.cpp+n-gram": "ngram-n3m3-", "little-gemma": "lg-",
       "CoPR": "ae-full-", "+ prompt lookup": "ae-ngram-", "+ prefix reuse": "ae-reuse-"}

FAILS = []
# Places where the data is right and the manuscript is not, found by this
# script. Printed every time and kept out of the failure count; fix the paper,
# then delete the entry here and the check turns strict again.
ERRATA = {
    "mmlupro100-ngram-n3m3-e2b-s1: above idle":
        "0.22447 J rounded twice (0.2245 -> 0.225); correct value 0.224",
    "mmlupro100-ae-full-e2b-s1: J/tok":
        "0.36947 J rounded twice (0.3695 -> 0.370); correct value 0.369",
}


def check(label, paper, got):
    """Print one comparison. paper is the manuscript's string; got is formatted
    the same way, so equality means 'equal at the paper's precision'."""
    ok = str(paper) == str(got)
    if ok:
        verdict = "ok"
    elif label in ERRATA:
        verdict = "ERRATUM: " + ERRATA[label]
    else:
        verdict = "DIFFERS"
        FAILS.append(label)
    print("  %-58s paper %-10s here %-10s %s" % (label, paper, got, verdict))


def f(x, nd):
    return "%.*f" % (nd, x)


def thousands(x):
    return "{:,}".format(int(round(x)))


# ---------------------------------------------------------------- inputs

def run_dir(row, model, subset):
    return os.path.join(RUNS, "mmlupro100-%s%s-%s" % (row, model, subset))


def summary(path):
    with open(os.path.join(path, "measured", "summary.json")) as fh:
        return json.load(fh)


def replies(path):
    """(category, doc_id) -> (reply text, correct) from lm-eval's samples."""
    out = {}
    with gzip.open(os.path.join(path, "samples.jsonl.gz"), "rt") as fh:
        for line in fh:
            s = json.loads(line)
            out[(s["doc"]["category"], s["doc_id"])] = (s["resps"][0][0], float(s["exact_match"]) > 0)
    return out


def pooled_replies(row, model, subsets=SUBSETS):
    out = {}
    for s in subsets:
        for k, v in replies(run_dir(row, model, s)).items():
            out[(s,) + k] = v
    return out


def pooled(row, model, subsets=SUBSETS):
    """Pooled ratios over the subsets: sum(tokens) / sum(time), never a mean of
    per-run rates (Sec. V). Per-question figures divide by the questions, not
    the requests (Table III note b: one run re-sent 5 prompts)."""
    ss = [summary(run_dir(row, model, s)) for s in subsets]
    t = lambda k: sum(s["tokens"][k] for s in ss)
    p = lambda k: sum(s["power"][k] for s in ss)
    n = 100 * len(ss)
    gen, dec, pre = t("generated_tokens"), t("decode_s"), t("prefill_s")
    return {
        "gen": gen,
        "decode": gen / dec,
        "prompt_q": t("prompt_tokens") / n,
        "prefill_share": 100 * pre / (pre + dec),
        "wall_q": sum(s["wall_s"] for s in ss) / n,
        # mean board power while generating, weighted by decode time
        "gen_w": sum(s["power"]["generation_mean_w"] * s["tokens"]["decode_s"] for s in ss) / dec,
        "j_tok": p("energy_j") / gen,
        "j_tok_idle": p("energy_above_idle_j") / gen,
    }


def accuracy(rep):
    return 100 * sum(ok for _, ok in rep.values()) / len(rep)


def identical(a, b):
    return sum(1 for k in a if k in b and a[k][0] == b[k][0])


def mcnemar(a, b):
    """Exact two-sided McNemar over paired correctness: (p, a-only, b-only)."""
    x = sum(1 for k in a if a[k][1] and not b[k][1])
    y = sum(1 for k in a if b[k][1] and not a[k][1])
    n = x + y
    if n == 0:
        return 1.0, x, y
    tail = sum(math.comb(n, i) for i in range(min(x, y) + 1)) / 2 ** n
    return min(1.0, 2 * tail), x, y


def request_window_energy(path):
    """Energy over the requests' own windows only (Sec. V): the trapezoidal
    integral of board power from each request's start to its end."""
    with gzip.open(os.path.join(path, "measured", "telemetry.csv.gz"), "rt") as fh:
        tel = [(float(r["ts_epoch"]), float(r["power_w"])) for r in csv.DictReader(fh) if r["power_w"]]

    def at(x):
        for (t0, w0), (t1, w1) in zip(tel, tel[1:]):
            if t0 <= x <= t1:
                return w0 + (w1 - w0) * (x - t0) / (t1 - t0) if t1 > t0 else w0
        return tel[-1][1]

    joules = tokens = 0
    with open(os.path.join(path, "measured", "requests.csv")) as fh:
        for q in csv.DictReader(fh):
            a, b = float(q["start_epoch"]), float(q["end_epoch"])
            pts = [(a, at(a))] + [(t, w) for t, w in tel if a < t < b] + [(b, at(b))]
            joules += sum((t1 - t0) * (w0 + w1) / 2 for (t0, w0), (t1, w1) in zip(pts, pts[1:]))
            tokens += int(q["gen_tokens"])
    return joules, tokens


_TURN = re.compile(r"^turn: \d+ in [\d.]+s .*?, (\d+) out ([\d.]+)s")
_NGRAM = re.compile(r"^ngram:\s+(\d+) rounds, \+(\d+) tokens .*verify ([\d.]+)s")


def sweep(name):
    """One verify-width run (ae_gate.py): decode rate from the engine's turn
    lines, energy from its telemetry, tokens and cost per verify pass from its
    ngram lines."""
    path = os.path.join(RUNS, name)
    out = sec = rounds = extra = verify_s = 0
    with gzip.open(os.path.join(path, "engine.log.gz"), "rt", errors="replace") as fh:
        for line in fh:
            m = _TURN.match(line)
            if m:
                out += int(m.group(1))
                sec += float(m.group(2))
            m = _NGRAM.match(line)
            if m:
                rounds += int(m.group(1))
                extra += int(m.group(2))
                verify_s += float(m.group(3))
    with open(os.path.join(path, "measured", "command.log")) as fh:
        gate = re.findall(r"(\d+)/(\d+) byte-identical", fh.read())
    return {"decode": out / sec, "j_tok": summary(path)["power"]["energy_j"] / out,
            "per_verify": extra / rounds if rounds else None,
            "verify_ms": 1000 * verify_s / rounds if rounds else None,
            "same": tuple(map(int, gate[-1])) if gate else None}


# ---------------------------------------------------------------- tables

def table1():
    print("\nTable I — baseline anatomy, E2B, Jetson Orin Nano 15 W, n=300")
    paper = {"llama.cpp": ("198,706", "23.00", "381", "2.7", "52.7"),
             "little-gemma": ("197,977", "25.58", "1,444", "3.2", "53.0")}
    for col, (gen, dec, pq, share, acc) in paper.items():
        p = pooled(ROW[col], "e2b")
        check(col + ": generated tokens", gen, thousands(p["gen"]))
        check(col + ": decode tok/s", dec, f(p["decode"], 2))
        check(col + ": prompt tokens prefilled / question", pq, thousands(p["prompt_q"]))
        check(col + ": share of request time in prefill %", share, f(p["prefill_share"], 1))
        check(col + ": accuracy %", acc, f(accuracy(pooled_replies(ROW[col], "e2b")), 1))


def table3():
    print("\nTable III — engines on the Jetson Orin Nano at 15 W, n=300 per cell")
    paper = {  # acc, decode, prompt/q, wall/q, W generating, J/tok, above idle
        ("e2b", "llama.cpp"): ("52.7", "23.00", "381", "31.0", "10.26", "0.465", "0.258"),
        ("e2b", "llama.cpp+n-gram"): ("53.3", "26.63", "381", "27.9", "10.84", "0.429", "0.228"),
        ("e2b", "little-gemma"): ("53.0", "25.58", "1,444", "28.3", "10.86", "0.446", "0.254"),
        ("e2b", "CoPR"): ("53.0", "29.52", "385", "24.1", "10.58", "0.370", "0.207"),
        ("e4b", "llama.cpp"): ("66.0", "11.62", "381", "62.6", "10.77", "0.965", "0.552"),
        ("e4b", "llama.cpp+n-gram"): ("65.0", "13.83", "381", "54.3", "11.53", "0.871", "0.487"),
        ("e4b", "little-gemma"): ("65.3", "15.05", "1,446", "51.9", "11.62", "0.838", "0.490"),
        ("e4b", "CoPR"): ("65.3", "17.67", "385", "41.6", "11.39", "0.676", "0.396"),
    }
    for (m, col), (acc, dec, pq, wall, w, j, ji) in paper.items():
        p, rep = pooled(ROW[col], m), pooled_replies(ROW[col], m)
        tag = "%s %s: " % (m.upper(), col)
        check(tag + "accuracy %", acc, f(accuracy(rep), 1))
        check(tag + "decode tok/s", dec, f(p["decode"], 2))
        check(tag + "prompt tokens processed / q", pq, thousands(p["prompt_q"]))
        check(tag + "wall time / question s", wall, f(p["wall_q"], 1))
        check(tag + "mean power generating W", w, f(p["gen_w"], 2))
        check(tag + "energy / generated token J", j, f(p["j_tok"], 3))
        check(tag + "  above idle J", ji, f(p["j_tok_idle"], 3))
    print("  replies identical:")
    a, b = replies(run_dir("", "e2b", "s1")), replies(run_dir("lg-", "e2b", "s1"))
    check("E2B s1 llama.cpp vs little-gemma (note a)", "12/100", "%d/100" % identical(a, b))
    for m, want in (("e2b", "29/300"), ("e4b", "20/300")):
        check("%s llama.cpp+n-gram vs llama.cpp, no drafting (note f)" % m.upper(), want,
              "%d/300" % identical(pooled_replies(ROW["llama.cpp+n-gram"], m), pooled_replies("", m)))
        check("%s CoPR vs little-gemma" % m.upper(), "300/300",
              "%d/300" % identical(pooled_replies("ae-full-", m), pooled_replies("lg-", m)))


def table4():
    print("\nTable IV — llama.cpp's own n-gram drafting against CoPR, E2B, s1 (n=100)")
    rows = [  # run, exact-against, paper (exact, acc, decode, wall, J/tok, above idle)
        ("mmlupro100-e2b-s1", None, ("-", "56", "23.04", "27.9", "0.466", "0.259")),
        ("mmlupro100-ngram-n3m2-e2b-s1", "mmlupro100-e2b-s1", ("100/100", "56", "23.80", "27.4", "0.491", "0.266")),
        ("mmlupro100-ngram-n3m3-e2b-s1", "mmlupro100-e2b-s1", ("8/100", "56", "26.97", "26.1", "0.424", "0.225")),
        ("mmlupro100-ngram-default-e2b-s1", "mmlupro100-e2b-s1", ("9/100", "53", "25.15", "26.8", "0.458", "0.249")),
        ("mmlupro100-ae-full-e2b-s1", "mmlupro100-lg-e2b-s1", ("100/100", "54", "29.54", "23.8", "0.370", "0.207")),
        ("mmlupro100-ae-full-r2-e2b-s1", "mmlupro100-lg-e2b-s1", ("100/100", "54", "29.78", "24.6", "0.404", "0.219")),
    ]
    for run, ref, (ex, acc, dec, wall, j, ji) in rows:
        path = os.path.join(RUNS, run)
        s, rep = summary(path), replies(path)
        g = s["tokens"]["generated_tokens"]
        if ref:
            check(run + ": exact", ex, "%d/100" % identical(rep, replies(os.path.join(RUNS, ref))))
        check(run + ": accuracy %", acc, f(accuracy(rep), 0))
        check(run + ": decode tok/s", dec, f(s["tokens"]["decode_tok_s"], 2))
        check(run + ": wall s/q", wall, f(s["wall_s"] / 100, 1))
        check(run + ": J/tok", j, f(s["power"]["energy_j"] / g, 3))
        check(run + ": above idle", ji, f(s["power"]["energy_above_idle_j"] / g, 3))
    p, x, y = mcnemar(replies(os.path.join(RUNS, "mmlupro100-ngram-n3m3-e2b-s1")),
                      replies(os.path.join(RUNS, "mmlupro100-e2b-s1")))
    check("width 4 vs no drafting: flips each way", "4/4", "%d/%d" % (x, y))
    check("width 4 vs no drafting: exact McNemar p", "1.00", f(p, 2))


def table5():
    print("\nTable V — ablation, n=300 per row; every row byte-identical to little-gemma")
    paper = {
        "e2b": {"little-gemma": ("25.58", "1,444", "28.3", "0.446"),
                "+ prompt lookup": ("29.51", "1,444", "24.8", "0.378"),
                "+ prefix reuse": ("25.81", "385", "27.2", "0.464"),
                "CoPR": ("29.52", "385", "24.1", "0.370")},
        "e4b": {"little-gemma": ("15.05", "1,446", "51.9", "0.838"),
                "+ prompt lookup": ("17.82", "1,444", "42.7", "0.696"),
                "+ prefix reuse": ("15.47", "385", "47.6", "0.853"),
                "CoPR": ("17.67", "385", "41.6", "0.676")},
    }
    same = 0
    for m, rows in paper.items():
        lg = pooled_replies("lg-", m)
        for col, (dec, pq, wall, j) in rows.items():
            p = pooled(ROW[col], m)
            tag = "%s %s: " % (m.upper(), col)
            check(tag + "decode tok/s", dec, f(p["decode"], 2))
            check(tag + "prompt tok / q", pq, thousands(p["prompt_q"]))
            check(tag + "wall s / q", wall, f(p["wall_q"], 1))
            check(tag + "J / tok", j, f(p["j_tok"], 3))
            if col != "little-gemma":
                same += identical(pooled_replies(ROW[col], m), lg)
    check("replies byte-identical to little-gemma, all six switch rows", "1,800", thousands(same))


def table6():
    print("\nTable VI — verify-width selection, 28 s1 questions per row")
    paper = {0: ("25.63", "0.451", "15.39", "0.879", "-", "1.00"),
             2: ("29.62", "0.386", "17.76", "0.736", "0.57", "1.24"),
             3: ("29.93", "0.381", "17.91", "0.707", "0.90", "1.47"),
             4: ("28.81", "0.393", "17.63", "0.713", "1.12", "1.76")}
    plain = sweep("ae-sweep-e2b-b0")
    plain_ms = 1000 / plain["decode"]
    same = total = 0
    for b, (d2, j2, d4, j4, tok, cost) in paper.items():
        e2, e4 = sweep("ae-sweep-e2b-b%d" % b), sweep("ae-sweep-e4b-b%d" % b)
        w = "width %s: " % (b or "none")
        check(w + "E2B tok/s", d2, f(e2["decode"], 2))
        check(w + "E2B J/tok", j2, f(e2["j_tok"], 3))
        check(w + "E4B tok/s", d4, f(e4["decode"], 2))
        check(w + "E4B J/tok", j4, f(e4["j_tok"], 3))
        check(w + "+tokens per verify (E2B)", tok, f(e2["per_verify"], 2) if b else "-")
        # a verify pass's cost in plain decode steps of the same board
        check(w + "cost per verify, plain steps (E2B)", cost,
              f(e2["verify_ms"] / plain_ms, 2) if b else "1.00")
        for e in (e2, e4):
            same += e["same"][0]
            total += e["same"][1]
    check("replies byte-identical to little-gemma", "224/224", "%d/%d" % (same, total))


def table8():
    print("\nTable VIII — same checkpoint and 300 questions on other edge devices")
    export = json.load(gzip.open(os.path.join(ROOT, "findings", "export", "experiment-full.json.gz")))
    pi = export["boards"]["pi"]["runs"]
    pi_acc = {"e2b": ["mmlupro100-e2b", "mmlupro100-e2b-s2", "mmlupro100-e2b-s3"],
              "e4b": ["mmlupro100-e4b-s1", "mmlupro100-e4b-s2", "mmlupro100-e4b-s3"]}
    # note a: Pi rates pooled over the two subsets with request logs
    pi_rate = {"e2b": ["mmlupro100-e2b-s2", "mmlupro100-e2b-s3"],
               "e4b": ["mmlupro100-e4b-s2", "mmlupro100-e4b-s3"]}
    phone = {"e2b": ["mmlupro-e2b-s1-20261003-150850", "mmlupro-e2b-s2-20261003-233936",
                     "mmlupro-e2b-s3-20261004-115841"],
             "e4b": ["mmlupro-e4b-oq4-s1-20261004-211929", "mmlupro-e4b-oq4-s2-20261005-112446",
                     "mmlupro-e4b-oq4-s3-20261005-152451"]}
    paper = {"e2b": (("51.7", "6.87", "1.130"), ("51.0", "14.50", "0.354"), ("-1.7", "0.55"), "-0.7"),
             "e4b": (("65.7", "3.37", "2.223"), ("66.0", "9.18", "0.593"), ("0.0", "1.00"), "0.3")}
    for m, (pp, ph, (d_jet, p_jet), d_pi) in paper.items():
        tag = m.upper() + " "
        acc = sum(pi[r]["summary"]["score"] for r in pi_acc[m]) / 3
        gt = sum(t["gt"] for r in pi_rate[m] for t in pi[r]["timeline"])
        gms = sum(t["gms"] for r in pi_rate[m] for t in pi[r]["timeline"])
        e = sum(pi[r]["summary_json"]["energy_wh"] * 3600 for r in pi_rate[m])
        check(tag + "Raspberry Pi 5, llama.cpp: accuracy %", pp[0], f(acc, 1))
        check(tag + "Raspberry Pi 5, llama.cpp: tok/s", pp[1], f(1000 * gt / gms, 2))
        check(tag + "Raspberry Pi 5, llama.cpp: J/tok", pp[2], f(e / gt, 3))
        runs = [json.load(gzip.open(os.path.join(ROOT, "findings", "phone", r + ".json.gz"))) for r in phone[m]]
        qs = [q for d in runs for q in d["questions"]]
        gt = sum(t["gt"] for d in runs for t in d["timeline"])
        gms = sum(t["gms"] for d in runs for t in d["timeline"])
        e = sum(d["device"]["energy_wh"] * 3600 for d in runs)
        gen = sum(d["device"]["gen_tokens"] for d in runs)
        check(tag + "iPhone 15 Pro, MLX: accuracy %", ph[0], f(100 * sum(bool(q.get("ok")) for q in qs) / len(qs), 1))
        check(tag + "iPhone 15 Pro, MLX: tok/s", ph[1], f(1000 * gt / gms, 2))
        check(tag + "iPhone 15 Pro, MLX: J/tok (battery estimate)", ph[2], f(e / gen, 3))
        # Sec. VII: paired over question ids against the Jetson's llama.cpp run
        jet = {}
        for s in SUBSETS:
            with gzip.open(os.path.join(run_dir("", m, s), "samples.jsonl.gz"), "rt") as fh:
                for line in fh:
                    x = json.loads(line)
                    jet[x["doc"]["question_id"]] = (None, float(x["exact_match"]) > 0)
        ip = {q["question_id"]: (None, bool(q.get("ok"))) for q in qs}
        p, _, _ = mcnemar(ip, jet)
        check(tag + "iPhone minus Jetson, points", d_jet, f(accuracy(ip) - accuracy(jet), 1))
        check(tag + "iPhone vs Jetson, exact McNemar p", p_jet, f(p, 2))
        check(tag + "iPhone minus Pi, points", d_pi, f(accuracy(ip) - acc, 1))


def text():
    print("\nIn-text figures")
    for m, x, y in (("e2b", "1.28", "1.15"), ("e4b", "1.52", "1.17")):
        c, l, g = pooled("ae-full-", m), pooled("", m), pooled("lg-", m)
        check("Abstract/VI-B %s: CoPR decode vs llama.cpp" % m.upper(), x + "x", f(c["decode"] / l["decode"], 2) + "x")
        check("VI-B %s: CoPR decode vs little-gemma" % m.upper(), y + "x", f(c["decode"] / g["decode"], 2) + "x")
    for m, want in (("e2b", "20"), ("e4b", "30")):
        c, l = pooled("ae-full-", m), pooled("", m)
        check("Abstract %s: less energy per token than llama.cpp %%" % m.upper(), want, f(100 * (1 - c["j_tok"] / l["j_tok"]), 0))
    for m, want in (("e2b", "271"), ("e4b", "280")):
        changed = 300 - identical(pooled_replies("ngram-n3m3-", m), pooled_replies("", m))
        check("VI-C %s: replies llama.cpp width 4 changes" % m.upper(), want, str(changed))
    for m, want in (("e2b", "1.11"), ("e4b", "1.28")):
        check("VI-C %s: CoPR decode vs llama.cpp+n-gram" % m.upper(), want + "x",
              f(pooled("ae-full-", m)["decode"] / pooled("ngram-n3m3-", m)["decode"], 2) + "x")
    for m, pw in (("e2b", ("0.86", "17/15")), ("e4b", ("0.69", "11/14"))):
        p, x, y = mcnemar(pooled_replies("ngram-n3m3-", m), pooled_replies("", m))
        check("VI-C %s: n-gram vs llama.cpp, McNemar p" % m.upper(), pw[0], f(p, 2))
    p, x, y = mcnemar(pooled_replies("lg-", "e2b"), pooled_replies("", "e2b"))
    check("VI-A E2B: right only under little-gemma / only llama.cpp", "14/13", "%d/%d" % (x, y))
    check("VI-A E2B: little-gemma vs llama.cpp, exact McNemar p", "1.00", f(p, 2))
    for m, want in (("e2b", ("0.363", "0.458")), ("e4b", ("0.664", "0.948"))):
        got = []
        for row in ("ae-full-", ""):
            jj = tt = 0
            for s in SUBSETS:
                j, t = request_window_energy(run_dir(row, m, s))
                jj, tt = jj + j, tt + t
            got.append(f(jj / tt, 3))
        check("V %s: J/tok over request windows only, CoPR / llama.cpp" % m.upper(), "/".join(want), "/".join(got))
    capped = 0
    for s in SUBSETS:
        with open(os.path.join(run_dir("lg-", "e2b", s), "measured", "requests.csv")) as fh:
            capped += sum(1 for q in csv.DictReader(fh) if int(q["gen_tokens"]) >= 2048)
    check("III: little-gemma E2B replies that hit the 2,048 cap", "17", str(capped))
    a = os.path.join(RUNS, "mmlupro100-ae-full-e2b-s1")
    b = os.path.join(RUNS, "mmlupro100-ae-full-r2-e2b-s1")
    sa, sb = summary(a), summary(b)
    check("V: repeat run, replies byte-identical", "100/100", "%d/100" % identical(replies(a), replies(b)))
    check("V: repeat run, idle floor W (repeat / first)", "5.01/4.55", "%s/%s" % (f(sb["power"]["idle_w"], 2), f(sa["power"]["idle_w"], 2)))
    check("V: repeat run, peak board temperature C", "62/60",
          "%s/%s" % (f(sb["thermal"]["temp_c"]["max"], 0), f(sa["thermal"]["temp_c"]["max"], 0)))
    gpu = sorted({summary(run_dir(ROW[c], m, s))["utilisation"]["gpu_mhz"]["median"]
                  for c in ("llama.cpp", "little-gemma", "CoPR") for m in MODELS for s in SUBSETS})
    check("V: GPU clock under load, MHz (every Table III run)", "612", ",".join(f(g, 0) for g in gpu))


def issues():
    """Facts in the data that the manuscript's text gets wrong or leaves out.
    Printed, not checked: there is no paper value to compare them with."""
    print("\nWhere the data and the manuscript disagree (informational)")
    print("  1. Table IV's 'llama.cpp n-gram, width 3' row (n3m2) never drafted.")
    print("     Requests whose llama-server log has a draft-acceptance line:")
    for run in ("mmlupro100-ngram-n3m2-e2b-s1", "mmlupro100-ngram-n3m3-e2b-s1",
                "mmlupro100-ngram-default-e2b-s1"):
        with gzip.open(os.path.join(RUNS, run, "server.log.gz"), "rt", errors="replace") as fh:
            n = sum(1 for line in fh if "draft acceptance" in line)
        print("       %-36s %3d/100" % (run, n))
    print("     So its 100/100 'exact' is plain decoding and its +3% is day-to-day spread;")
    print("     it says nothing about whether width-3 drafting in llama.cpp is exact.")
    print("  2. Runs from 2026-10-07 19:30 on had the Jetson's clocks pinned (jetson_clocks,")
    print("     RESULTS 7.7): CPU at its 1,497.6 MHz cap instead of scaling. The paper puts the")
    print("     cross-day energy band down to idle floor and temperature without naming it.")
    print("       %-36s %-17s %8s %6s" % ("run", "started", "CPU MHz", "idle W"))
    for run in ("mmlupro100-e2b-s1", "mmlupro100-ae-full-e2b-s1", "mmlupro100-ae-full-r2-e2b-s1",
                "mmlupro100-ae-reuse-e2b-s1", "mmlupro100-ngram-n3m3-e2b-s1", "mmlupro100-ngram-n3m2-e2b-s1"):
        sm = summary(os.path.join(RUNS, run))
        with open(os.path.join(RUNS, run, "measured", "SOURCE")) as fh:
            stamp = fh.read().strip()[-15:]
        print("       %-36s %-17s %8.0f %6.2f" % (run, stamp, sm["thermal"]["cpu_mhz_mean"], sm["power"]["idle_w"]))


TABLES = {"1": table1, "3": table3, "4": table4, "5": table5, "6": table6, "8": table8, "text": text, "issues": issues}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--table", choices=sorted(TABLES), help="one table (default: all)")
    args = ap.parse_args()
    for key in ([args.table] if args.table else list(TABLES)):
        TABLES[key]()
    print("\n%s" % ("every number matches the manuscript" if not FAILS else
                    "%d differ: %s" % (len(FAILS), "; ".join(FAILS))))
    if ERRATA:
        print("%d manuscript errata (the data is right, the paper's rounding is not): %s"
              % (len(ERRATA), "; ".join(ERRATA)))
    print("not rebuilt here: Table VII and the Sec. III replay (replay_lookup.py), the Sec. VII Pi batch costs (on the Pi)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
