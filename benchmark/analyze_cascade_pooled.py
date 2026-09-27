#!/usr/bin/env python3
"""The permutation cascade, pooled over subsets, with K and the threshold swept.

    python3 analyze_cascade_pooled.py --subsets s1,s2,s3 --rotations 0,2,4,6

Pools first, then sweeps — the other order lets you pick the configuration that
happens to look best on one subset, which at n=100 is noise. Reports every
configuration rather than a chosen one, and marks which are distinguishable
from the CoT baseline by a paired test.

Costs are measured per-subset figures scaled by the escalation rate the gate
actually produces, not assumed.
"""
import argparse, glob, itertools, json, math, os, re
from collections import Counter

ANS = re.compile(r"answer is \(?([A-J])\)?", re.I)


def picks(root, run, task):
    """{question: (chosen option text, gold option text)}. Resolving the letter
    through that run's own rotated options makes rotations comparable without
    un-rotating anything."""
    out = {}
    for f in sorted(glob.glob(f"{root}/stdbench/{run}/*/samples_{task}_*.jsonl")):
        for line in open(f):
            r = json.loads(line)
            doc, m = r["doc"], ANS.findall(r["resps"][0][0])
            chosen = None
            if m:
                i = "ABCDEFGHIJ".index(m[-1].upper())
                if i < len(doc["options"]):
                    chosen = doc["options"][i]
            out[doc["question"]] = (chosen, doc["options"][doc["answer_index"]])
    return out


def mcnemar(a, b):
    """exact two-sided, over the questions where the two disagree"""
    x = sum(1 for q in a if a[q] and not b[q])
    y = sum(1 for q in a if not a[q] and b[q])
    n, k = x + y, min(x, y)
    if not n:
        return 1.0, x, y
    return min(1.0, 2*sum(math.comb(n, i) for i in range(k+1))/2**n), x, y


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    home = os.path.expanduser("~")
    ap.add_argument("--root", default=next((p for p in (f"{home}/Research", f"{home}/research")
                                            if os.path.isdir(p)), home))
    ap.add_argument("--model", default="e2b")
    ap.add_argument("--subsets", default="s1,s2,s3")
    ap.add_argument("--rotations", default="0,2,4,6")
    # measured per-100-question costs; defaults are the Pi's E2B figures
    ap.add_argument("--letter-cost", nargs=2, type=float, default=[1.26, 9.3],
                    metavar=("WH", "MIN"))
    ap.add_argument("--cot-cost", nargs=2, type=float, default=[21.37, 181.1],
                    metavar=("WH", "MIN"))
    args = ap.parse_args()

    ROT = [int(x) for x in args.rotations.split(",")]
    subs = args.subsets.split(",")
    votes, gold, cot = {}, {}, {}
    for sub in subs:
        per = {}
        for r in ROT:
            run = (f"mmlupro100-{args.model}-{sub}-letter" if r == 0
                   else f"mmlupro100-{args.model}-{sub}-letter-r{r}")
            task = "mmlu_pro_letter" if r == 0 else f"mmlu_pro_letter_r{r}"
            d = picks(args.root, run, task)
            if not d:
                print(f"  (missing: {run}) — skipping subset {sub}")
                per = None
                break
            per[r] = d
        if not per:
            continue
        c = picks(args.root, f"mmlupro100-{args.model}-{sub}", "mmlu_pro")
        common = [q for q in per[ROT[0]] if q in c and all(q in per[r] for r in ROT)]
        for q in common:
            key = (sub, q)
            votes[key] = {r: per[r][q][0] for r in ROT}
            gold[key] = per[ROT[0]][q][1]
            cot[key] = (c[q][0] == c[q][1])

    n = len(votes)
    if not n:
        print("no paired questions"); return
    base = 100*sum(cot.values())/n
    lw, lm = args.letter_cost; cw, cm = args.cot_cost
    print(f"  pooled n={n} over {','.join(subs)}   rotations {ROT}")
    print(f"  CoT baseline {base:.1f}%   {cw:.2f} Wh   {cm:.0f} min  (per 100 q)\n")

    # The rotation set is printed because choosing among sets is a further
    # degree of freedom; hiding it would make several rows look like repeats
    # and invite picking the flattering one.
    print(f"  {'rotations':14} {'thr':>4} {'kept%':>6} {'keptAcc':>8} {'cascade':>8} "
          f"{'Wh':>7} {'min':>7} {'ΔWh':>6} {'Δmin':>6} {'p':>7}")
    for K in range(2, len(ROT)+1):
        for rots in itertools.combinations(ROT, K):
            if rots[0] != ROT[0]:
                continue                      # keep r0 in, so K rows are comparable
            for thr in range(max(2, K//2 + 1), K+1):
                res, kept = {}, 0
                for key in votes:
                    v = [votes[key][r] for r in rots if votes[key][r]]
                    top, cnt = Counter(v).most_common(1)[0] if v else (None, 0)
                    if cnt >= thr:
                        kept += 1
                        res[key] = (top == gold[key])
                    else:
                        res[key] = cot[key]
                acc = 100*sum(res.values())/n
                kacc = 100*sum(res[k] for k in res if True) / n   # placeholder, refined below
                keep_ok = sum(1 for key in votes
                              if (lambda v: (Counter(v).most_common(1)[0][1] if v else 0) >= thr)
                                 ([votes[key][r] for r in rots if votes[key][r]])
                              and res[key])
                f = 1 - kept/n
                wh, mn = K*lw + f*cw, K*lm + f*cm
                p, x, y = mcnemar(res, cot)
                tag = "+".join(f"r{r}" for r in rots)
                print(f"  {tag:14} {thr:>4} {100*kept/n:5.0f}% {100*keep_ok/kept if kept else 0:7.1f}% "
                      f"{acc:7.1f}% {wh:6.2f} {mn:6.1f} {100*(1-wh/cw):5.0f}% "
                      f"{100*(1-mn/cm):5.0f}% {p:7.3f}")
    print("\n  p is a paired exact McNemar against the CoT baseline on the same questions.")
    print("  p > 0.05 means 'not distinguishable at this n', NOT 'equivalent'.")
    print("  Rows differ in rotation set as well as K and threshold; picking the")
    print("  best-looking row is selecting over all three at once.")


if __name__ == "__main__":
    main()
