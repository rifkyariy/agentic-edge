#!/usr/bin/env python3
"""Ceiling for a confidence-gated model cascade, from runs already on a board.

    python3 analyze_cascade.py                       # on a board, its own results
    python3 analyze_cascade.py --root ~/research
    python3 analyze_cascade.py --export findings/export/experiment-full.json --board pi

The --export path needs no board, which matters: the boards are only reachable
from the lab network, and this is the kind of analysis you want on a train.

Pairs E2B and E4B on the *same* questions and asks what a router could achieve
if it knew which questions E2B would get wrong. That oracle is not attainable,
but it bounds the method: no gate can beat it, and a random gate at the same
escalation rate is reported alongside so the gap between them is visible —
that gap is the part a real method has to earn.

Energy figures are per 100 questions, measured, and passed in rather than
derived, because they depend on the board and engine (see --wh).
"""
import argparse, glob, json, os, re

ANS = re.compile(r"answer is \(?([A-J])\)?", re.I)


def answers(root, model):
    """{question: correct?} pooled over s1/s2/s3 for one model."""
    out = {}
    for s in ("s1", "s2", "s3"):
        names = [f"mmlupro100-{model}-{s}"]
        if s == "s1":
            names.append(f"mmlupro100-{model}")      # pre-subset naming
        for n in names:
            fs = sorted(glob.glob(f"{root}/stdbench/{n}/*/samples_mmlu_pro_*.jsonl"))
            if not fs:
                continue
            for f in fs:
                for line in open(f):
                    r = json.loads(line)
                    out[r["doc"]["question"]] = bool(r["exact_match"])
            break
    return out


def from_export(path, board):
    """Same pairing, out of an exported run file rather than off a board."""
    d = json.load(open(path))
    out = {"e2b": {}, "e4b": {}}
    for name, r in d["boards"][board]["runs"].items():
        if name == "mmlupro100-e4b":          # duplicate of -e4b-s1
            continue
        for q in r.get("questions") or []:
            if q.get("q") is not None and q.get("ok") is not None:
                out[r["model"]][q["q"]] = bool(q["ok"])
    return out["e2b"], out["e4b"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    home = os.path.expanduser("~")
    ap.add_argument("--root", default=next((p for p in (f"{home}/Research", f"{home}/research")
                                            if os.path.isdir(p)), home))
    ap.add_argument("--wh", nargs=2, type=float, metavar=("E2B", "E4B"),
                    help="Wh per 100 questions for each model on this board")
    ap.add_argument("--export", help="read a findings/export JSON instead of a board")
    ap.add_argument("--board", default="pi", choices=("pi", "jetson"),
                    help="which board, when reading --export")
    args = ap.parse_args()

    if args.export:
        small, large = from_export(args.export, args.board)
        args.root = f"{args.export} [{args.board}]"
    else:
        small, large = answers(args.root, "e2b"), answers(args.root, "e4b")
    common = [q for q in small if q in large]
    if not common:
        print(json.dumps({"error": "no paired questions found", "root": args.root})); return

    n = len(common)
    both = sum(1 for q in common if small[q] and large[q])
    s_only = sum(1 for q in common if small[q] and not large[q])
    l_only = sum(1 for q in common if large[q] and not small[q])
    neither = n - both - s_only - l_only
    e2, e4 = 100*(both+s_only)/n, 100*(both+l_only)/n
    oracle = 100*(both+s_only+l_only)/n
    err = (s_only + neither) / n          # what E2B gets wrong = what a perfect gate escalates

    print(f"root {args.root}   paired questions {n}\n")
    print(f"  E2B alone            {e2:5.1f}%")
    print(f"  E4B alone            {e4:5.1f}%")
    print(f"  both right           {100*both/n:5.1f}%")
    print(f"  E2B only             {100*s_only/n:5.1f}%   <- why the ceiling beats E4B")
    print(f"  E4B only             {100*l_only/n:5.1f}%   <- what escalation buys")
    print(f"  neither              {100*neither/n:5.1f}%   <- unreachable by any gate")
    print(f"\n  ORACLE CASCADE       {oracle:5.1f}%  escalating {100*err:.0f}% of questions")
    print(f"     vs E4B alone      {oracle-e4:+5.1f} pts")

    if args.wh:
        w2, w4 = args.wh
        casc = w2 + err*w4
        fmax = (w4 - w2)/w4
        rand = e2 + fmax*(e4-e2)
        print(f"\n  energy per 100 questions (measured)")
        print(f"     E2B alone         {w2:5.1f} Wh")
        print(f"     E4B alone         {w4:5.1f} Wh")
        cut = 100*(1 - casc/w4)
        print(f"     oracle cascade    {casc:5.1f} Wh   "
              f"({abs(cut):.0f}% {'less' if cut > 0 else 'more'} than E4B alone)")
        print(f"     cheaper than E4B while escalating < {100*fmax:.0f}%")
        print(f"     a RANDOM gate at that rate: {rand:.1f}%  <- the gate is the method")


if __name__ == "__main__":
    main()
