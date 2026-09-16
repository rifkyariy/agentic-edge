#!/usr/bin/env python3
"""Turn results/*.json into the four tables the study actually needs.

    python3 report.py           # all four
    python3 report.py t1        # architecture comparison (the headline)
    python3 report.py t2        # MTP x thinking x CUDA
    python3 report.py t3        # quant sweep
    python3 report.py t4        # per-category classifier behaviour
    python3 report.py t1 --results path/to/dir

One flat table cannot serve four different groupings, so each is built
separately. Latency is reported as warm median (cold shown separately in T1)
because a mean over repeats averages one uncached turn with the rest and
describes neither. Stdlib only; markdown out.
"""
import argparse
import glob
import json
import os
import sys


def load(results_dir):
    runs = []
    for path in sorted(glob.glob(os.path.join(results_dir, "*.json"))):
        try:
            with open(path) as f:
                runs.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            print(f"skipping unreadable {path}", file=sys.stderr)
    return runs


def pct(frac):
    """{'n':30,'k':29,'pct':96.7} -> '96.7% (29/30)'"""
    if not frac or not frac.get("n"):
        return "—"
    return f"{frac['pct']}% ({frac['k']}/{frac['n']})"


def table(headers, rows):
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        print("| " + " | ".join("—" if v is None else str(v) for v in r) + " |")
    print()


def skipped_note(run):
    return "skipped: " + "; ".join(
        f"{s['toggle']} — {s['reason']}" for s in run.get("skipped", []))


def sort_key(run):
    c = run["config"]
    return (c.get("device", ""), c.get("condition", ""),
            c.get("model", {}).get("name", ""), c.get("model", {}).get("quant", ""))


def t1(runs):
    """Architecture comparison. D vs E is the claim; A/B/C are the floor."""
    print("## T1 — Architecture comparison\n")
    print("Tool-selection and fabrication are over the tool-requiring cases; "
          "static accuracy over the fixed-ground-truth cases. Latency is "
          "warm median, cold shown separately.\n")
    rows = []
    for run in sorted(runs, key=sort_key):
        c, s = run["config"], run.get("summary") or {}
        if run.get("skipped"):
            rows.append([c.get("device"), c.get("condition"), c.get("label"),
                         c["model"].get("name"), skipped_note(run),
                         None, None, None, None, None])
            continue
        rows.append([
            c.get("device"), c.get("condition"), c.get("label"),
            c["model"].get("name"),
            pct(s.get("tool_selection")), pct(s.get("fabrication")),
            pct(s.get("static_answers")),
            s.get("warm_ttft_s"), s.get("warm_total_s"), s.get("cold_total_s"),
        ])
    table(["device", "cond", "architecture", "model", "tool sel.",
           "fabrication", "static acc", "TTFT (warm)", "total (warm)",
           "total (cold)"], rows)


def t2(runs):
    """MTP x thinking, split by device — where CUDA either flips MTP's sign
    or does not."""
    print("## T2 — MTP x thinking x CUDA\n")
    print("Only engines that support the toggles appear. `model time` excludes "
          "tool network I/O, which is not the architecture's cost.\n")
    rows = []
    for run in sorted(runs, key=sort_key):
        c, s = run["config"], run.get("summary") or {}
        if not (c.get("mtp") or c.get("thinking")) and c.get("condition") not in ("B", "E"):
            continue
        if run.get("skipped"):
            rows.append([c.get("device"), "yes" if c.get("cuda") else "no",
                         c.get("condition"), c["model"].get("name"),
                         skipped_note(run), None, None, None, None])
            continue
        rows.append([
            c.get("device"), "yes" if c.get("cuda") else "no",
            c.get("condition"), c["model"].get("name"),
            "on" if c.get("mtp") else "off",
            s.get("warm_ttft_s"), s.get("warm_total_s"),
            s.get("warm_model_time_s"), s.get("warm_tokens_per_s"),
            pct(s.get("static_answers")),
        ])
    table(["device", "cuda", "cond", "model", "mtp", "TTFT", "total",
           "model time", "tok/s", "static acc"], rows)


def t3(runs):
    """Quant sweep — robustness check, not a competing headline."""
    print("## T3 — Quantization sweep\n")
    rows = []
    for run in sorted(runs, key=lambda r: r["config"]["model"].get("quant", "")):
        c, s = run["config"], run.get("summary") or {}
        if run.get("skipped") or not s:
            continue
        rows.append([
            c.get("device"), c.get("condition"), c["model"].get("name"),
            c["model"].get("quant"), s.get("warm_tokens_per_s"),
            s.get("warm_ttft_s"), s.get("warm_total_s"),
            pct(s.get("static_answers")), pct(s.get("tool_selection")),
        ])
    table(["device", "cond", "model", "quant", "tok/s", "TTFT", "total",
           "static acc", "tool sel."], rows)
    print("_File size on disk and resident RSS are not captured automatically "
          "— record them by hand for this table._\n")


def t4(runs):
    """Per-category behaviour of the orchestrator: does the classifier fire
    where it should, and stay quiet where it should not."""
    print("## T4 — Classifier behaviour (condition E only)\n")
    print("`creative` calling no tool is a positive result: the classifier "
          "does not over-trigger. Per-category latency shows the tool tax is "
          "paid only where it is needed.\n")
    for run in sorted(runs, key=sort_key):
        c = run["config"]
        if not c.get("condition", "").startswith("E") or run.get("skipped"):
            continue
        by_cat = {}
        for r in run.get("results", []):
            by_cat.setdefault(r.get("category") or "?", []).append(r)
        if not by_cat:
            continue
        print(f"**{c.get('device')} / {c.get('condition')} / "
              f"{c['model'].get('name')} {c['model'].get('quant')}**\n")
        rows = []
        for cat, rs in sorted(by_cat.items()):
            warm = [r for r in rs if r.get("repeat_n", 0) > 0 and r.get("ok")]
            tot = sorted(r["total_s"] for r in warm if r.get("total_s") is not None)
            called = sorted({r.get("tool_called") for r in rs if r.get("tool_called")})
            n_tc = sum(1 for r in rs if "tool_correct" in r)
            k_tc = sum(1 for r in rs if r.get("tool_correct"))
            n_fab = sum(1 for r in rs if r.get("fabricated"))
            rows.append([
                cat, len(rs), ", ".join(called) or "none",
                f"{k_tc}/{n_tc}" if n_tc else "n/a",
                n_fab or 0,
                tot[len(tot) // 2] if tot else None,
            ])
        table(["category", "n", "tool(s) called", "tool correct",
               "fabricated", "total (warm med)"], rows)


TABLES = {"t1": t1, "t2": t2, "t3": t3, "t4": t4}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tables", nargs="*", default=None,
                    help="t1 t2 t3 t4 (default: all)")
    ap.add_argument("--results", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "results"))
    args = ap.parse_args()

    runs = load(args.results)
    if not runs:
        print(f"no result files in {args.results} — run sweep.sh first")
        return
    wanted = args.tables or ["t1", "t2", "t3", "t4"]
    print(f"_{len(runs)} run(s) from {args.results}_\n")
    for name in wanted:
        fn = TABLES.get(name)
        if not fn:
            sys.exit(f"unknown table {name!r} — have: {', '.join(TABLES)}")
        fn(runs)


if __name__ == "__main__":
    main()
