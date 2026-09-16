#!/usr/bin/env python3
"""Aggregate results/*.json into one comparison table across
device x engine x model x quant x cuda x mtp x thinking.

    python3 report.py               # reads ./results
    python3 report.py path/to/dir   # reads any directory of result JSON files

Stdlib only, markdown table on stdout — paste straight into a doc or PR.
"""
import glob
import json
import os
import sys


def load_all(results_dir):
    runs = []
    for path in sorted(glob.glob(os.path.join(results_dir, "*.json"))):
        with open(path) as f:
            try:
                runs.append(json.load(f))
            except json.JSONDecodeError:
                print(f"skipping unparseable {path}", file=sys.stderr)
    return runs


def row_for(run):
    c = run["config"]
    m = c.get("model", {})
    s = run.get("summary", {})
    return {
        "device": c.get("device", "?"),
        "engine": c["engine"],
        "model": m.get("name", "?"),
        "quant": m.get("quant", "?"),
        "cuda": "yes" if c.get("cuda") else "no",
        "mtp": "on" if c.get("mtp") else "off",
        "thinking": "on" if c.get("thinking") else "off",
        "avg_total_s": s.get("avg_total_s", "-"),
        "avg_tok_s": s.get("avg_tokens_per_s", "-"),
        "tool_acc": s.get("tool_calls_correct") or "-",
        "answer_acc": s.get("answers_correct") or "-",
        "ok": f"{s.get('n_ok', '?')}/{s.get('n', '?')}",
        "gpu": (run.get("gpu") or {}).get("name") or "-",
    }


def main():
    results_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "results")
    runs = load_all(results_dir)
    if not runs:
        print(f"no result files in {results_dir} — run run_benchmark.py first")
        return

    rows = [row_for(r) for r in runs]
    cols = [("device", "device"), ("engine", "engine"), ("model", "model"),
            ("quant", "quant"), ("cuda", "cuda"), ("gpu", "gpu"),
            ("mtp", "mtp"), ("thinking", "think"),
            ("avg_total_s", "avg total (s)"), ("avg_tok_s", "avg tok/s"),
            ("tool_acc", "tool acc"), ("answer_acc", "answer acc"), ("ok", "ok/n")]

    print(f"{len(runs)} run(s) from {results_dir}\n")
    print("| " + " | ".join(h for _, h in cols) + " |")
    print("|" + "|".join(["---"] * len(cols)) + "|")
    for r in rows:
        print("| " + " | ".join(str(r[k]) for k, _ in cols) + " |")


if __name__ == "__main__":
    main()
