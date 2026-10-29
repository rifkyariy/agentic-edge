#!/usr/bin/env python3
"""Score tool calls against BFCL v4 ground truth (plan §5.3).

A task passes when every expected call is present with correct arguments
(the paper's rule); "strict" also requires no extra calls (BFCL's rule).
Strings are compared with BFCL's own standardize_string; an argument whose
acceptable values include "" or None may be left out.

    python3 score.py <tasks.jsonl> <results.jsonl>   # prints and writes score.json beside results
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path


def standardize(s):
    # bfcl_eval/eval_checker/ast_eval/ast_checker.py standardize_string
    return re.sub(r"[ \,\.\/\-\_\*\^]", "", s).lower().replace("'", '"')


def same(v, a):
    """One model value against one acceptable value."""
    if isinstance(a, bool) or isinstance(v, bool):
        return v is a
    if isinstance(a, (int, float)):
        return isinstance(v, (int, float)) and float(v) == float(a)
    if isinstance(a, str):
        return isinstance(v, str) and standardize(v) == standardize(a)
    if isinstance(a, list):
        return isinstance(v, list) and len(v) == len(a) and all(map(same, v, a))
    if isinstance(a, dict):
        if a and all(isinstance(x, list) for x in a.values()):
            return isinstance(v, dict) and args_ok(v, a)  # a nested spec: key -> acceptable values
        return isinstance(v, dict) and v.keys() == a.keys() and all(same(v[k], a[k]) for k in a)
    return v == a  # None


def args_ok(args, spec):
    if not set(args) <= set(spec):
        return False
    return all(any(same(args[k], a) for a in acc) if k in args else ("" in acc or None in acc)
               for k, acc in spec.items())


def matches(expected, calls):
    """Assign each expected call to a distinct model call; backtracks, so ambiguous specs don't mis-pair."""
    if not expected:
        return True
    (name, spec), = expected[0].items()
    return any(c["name"] == name and args_ok(c["args"], spec) and matches(expected[1:], calls[:i] + calls[i + 1:])
               for i, c in enumerate(calls))


def score_task(task, calls):
    """calls: [{"name": <name as the model sent it>, "args": {...}}]"""
    calls = [{"name": task["names"].get(c["name"], c["name"]), "args": c["args"]} for c in calls]
    ok = matches(task["ground_truth"], calls)
    return {"pass": ok, "strict": ok and len(calls) == len(task["ground_truth"])}


def main():
    tasks = {t["id"]: t for t in map(json.loads, open(sys.argv[1]))}
    res_path = Path(sys.argv[2])
    by_cat = defaultdict(lambda: {"n": 0, "pass": 0, "strict": 0, "outcomes": defaultdict(int)})
    for r in map(json.loads, res_path.open()):
        t = tasks[r["id"]]
        s = score_task(t, r.get("calls") or []) if r["outcome"] == "ok" else {"pass": False, "strict": False}
        for c in (by_cat[t["category"]], by_cat["all"]):
            c["n"] += 1
            c["pass"] += s["pass"]
            c["strict"] += s["strict"]
            c["outcomes"][r["outcome"]] += 1
    out = {k: {**v, "acc": round(v["pass"] / v["n"], 4), "acc_strict": round(v["strict"] / v["n"], 4)}
           for k, v in sorted(by_cat.items())}
    (res_path.parent / "score.json").write_text(json.dumps(out, indent=2) + "\n")
    for k, v in out.items():
        print(f"{k:24} n={v['n']:3}  acc={v['acc']:.3f}  strict={v['acc_strict']:.3f}  {dict(v['outcomes'])}")


if __name__ == "__main__":
    main()
