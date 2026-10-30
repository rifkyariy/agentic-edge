#!/usr/bin/env python3
"""Score tool calls against BFCL v4 ground truth (plan §5.3).

A task passes when every expected call is present with correct arguments
(the paper's rule); "strict" also requires no extra calls (BFCL's rule);
"enum" only asks whether every required call was issued, arguments aside (the
paper's enumeration accuracy for fan-out). T1 tasks are also reported by chain
length band and fan-out size.
Strings are compared with BFCL's own standardize_string; an argument whose
acceptable values include "" or None may be left out.

    python3 score.py <tasks.jsonl> <results.jsonl>   # prints and writes score.json beside results
"""
import json, re, sys
from collections import Counter, defaultdict
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
    tried = []
    for i, c in enumerate(calls):
        if c in tried:  # identical calls are interchangeable; trying each would backtrack exponentially
            continue
        tried.append(c)
        if c["name"] == name and args_ok(c["args"], spec) and matches(expected[1:], calls[:i] + calls[i + 1:]):
            return True
    return False


def score_task(task, calls):
    """calls: [{"name": <name as the model sent it>, "args": {...}}]"""
    calls = [{"name": task["names"].get(c["name"], c["name"]), "args": c["args"]} for c in calls]
    ok = matches(task["ground_truth"], calls)
    need, got = Counter(n for gt in task["ground_truth"] for n in gt), Counter(c["name"] for c in calls)
    return {"pass": ok, "strict": ok and len(calls) == len(task["ground_truth"]),
            "enum": all(got[n] >= k for n, k in need.items())}


def group(task):
    """T1's breakdown: chains by the paper's length thresholds (6, 13), fan-out by size."""
    n = task.get("n")
    if task["category"] == "chain":
        return "chain_len" + ("02-05" if n < 6 else "06-12" if n < 13 else "13-20")
    return f"fanout_n{n:02d}" if task["category"] == "fanout" else None


def main():
    tasks = {t["id"]: t for t in map(json.loads, open(sys.argv[1]))}
    res_path = Path(sys.argv[2])
    by_cat = defaultdict(lambda: {"n": 0, "pass": 0, "strict": 0, "enum": 0, "outcomes": defaultdict(int)})
    for r in map(json.loads, res_path.open()):
        t = tasks[r["id"]]
        s = score_task(t, r.get("calls") or []) if r["outcome"] == "ok" else {"pass": False, "strict": False, "enum": False}
        for k in {t["category"], "all", group(t)} - {None}:
            c = by_cat[k]
            c["n"] += 1
            for m in ("pass", "strict", "enum"):
                c[m] += s[m]
            c["outcomes"][r["outcome"]] += 1
    out = {k: {**v, "acc": round(v["pass"] / v["n"], 4), "acc_strict": round(v["strict"] / v["n"], 4),
               "acc_enum": round(v["enum"] / v["n"], 4)}
           for k, v in sorted(by_cat.items())}
    (res_path.parent / "score.json").write_text(json.dumps(out, indent=2) + "\n")
    for k, v in out.items():
        print(f"{k:24} n={v['n']:3}  acc={v['acc']:.3f}  strict={v['acc_strict']:.3f}  "
              f"enum={v['acc_enum']:.3f}  {dict(v['outcomes'])}")


if __name__ == "__main__":
    main()
