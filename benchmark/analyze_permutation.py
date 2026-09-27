#!/usr/bin/env python3
"""Permutation ensemble: does agreement across option orders predict correctness?

    python3 analyze_permutation.py --subset s1 --model e2b

The cascade needs a gate that answers "will the cheap path get this right?",
and the previous attempt (escalate where the model is numerically unstable)
failed because instability tracks difficulty, which defeats both paths.

This tests a different signal. The same question is asked K ways with the
option order rotated; the model's choice is mapped back to the option TEXT it
picked, so rotation needs no un-doing. Two things then get measured:

  * ensemble accuracy — majority vote over the K choices, which is the
    debiased answer that arXiv 2309.03882 argues for
  * agreement as a gate — accuracy when all K agree against when they do not.
    A wide split means a usable confidence signal; a narrow one means the
    ensemble is just as confused as a single pass and the cascade has no gate.

Nothing here uses ground truth to route. Agreement is computed from the
model's own outputs, so a gate built on it is deployable.
"""
import argparse, glob, json, os, re
from collections import Counter

ANS = re.compile(r"answer is \(?([A-J])\)?", re.I)


def picks(root, run, task):
    """{question: chosen option text} — the letter resolved through that run's
    own (rotated) option list, which is what makes the rotations comparable."""
    out = {}
    for f in sorted(glob.glob(f"{root}/stdbench/{run}/*/samples_{task}_*.jsonl")):
        for line in open(f):
            r = json.loads(line)
            doc, resp = r["doc"], r["resps"][0][0]
            m = ANS.findall(resp)
            chosen = None
            if m:
                i = "ABCDEFGHIJ".index(m[-1].upper())
                if i < len(doc["options"]):
                    chosen = doc["options"][i]
            out[doc["question"]] = {
                "chosen": chosen,
                "gold": doc["options"][doc["answer_index"]],
                "ok": bool(r["exact_match"]),
            }
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    home = os.path.expanduser("~")
    ap.add_argument("--root", default=next((p for p in (f"{home}/Research", f"{home}/research")
                                            if os.path.isdir(p)), home))
    ap.add_argument("--subset", default="s1")
    ap.add_argument("--model", default="e2b")
    ap.add_argument("--rotations", default="0,2,4,6,8")
    args = ap.parse_args()

    runs = {}
    for r in [int(x) for x in args.rotations.split(",")]:
        run = (f"mmlupro100-{args.model}-{args.subset}-letter" if r == 0
               else f"mmlupro100-{args.model}-{args.subset}-letter-r{r}")
        task = "mmlu_pro_letter" if r == 0 else f"mmlu_pro_letter_r{r}"
        d = picks(args.root, run, task)
        if d:
            runs[r] = d
        else:
            print(f"  (rotation {r}: no samples at {run} — skipped)")
    if len(runs) < 2:
        print("need at least two rotations"); return

    base = runs[min(runs)]
    qs = [q for q in base if all(q in d for d in runs.values())]
    K = len(runs)
    print(f"  rotations {sorted(runs)}   paired questions {len(qs)}\n")

    for r in sorted(runs):
        acc = 100 * sum(runs[r][q]["ok"] for q in qs) / len(qs)
        print(f"    rotation {r}: {acc:5.1f}%")

    ens_ok = agree_n = agree_ok = dis_ok = 0
    buckets = Counter()
    for q in qs:
        votes = [runs[r][q]["chosen"] for r in sorted(runs)]
        gold = base[q]["gold"]
        top, n_top = Counter([v for v in votes if v]).most_common(1)[0] if any(votes) else (None, 0)
        ens_ok += (top == gold)
        buckets[n_top] += 1
        if n_top == K:
            agree_n += 1; agree_ok += (top == gold)
        else:
            dis_ok += (top == gold)

    single = 100 * sum(base[q]["ok"] for q in qs) / len(qs)
    print(f"\n    single pass (r={min(runs)}) {single:5.1f}%")
    print(f"    ENSEMBLE majority       {100*ens_ok/len(qs):5.1f}%   ({100*ens_ok/len(qs) - single:+.1f})")

    print(f"\n  AGREEMENT AS A GATE")
    dis_n = len(qs) - agree_n
    print(f"    all {K} agree : {agree_n:3} questions ({100*agree_n/len(qs):.0f}%)  "
          f"accuracy {100*agree_ok/agree_n if agree_n else 0:5.1f}%")
    print(f"    they differ  : {dis_n:3} questions ({100*dis_n/len(qs):.0f}%)  "
          f"accuracy {100*dis_ok/dis_n if dis_n else 0:5.1f}%")
    if agree_n and dis_n:
        sep = 100*agree_ok/agree_n - 100*dis_ok/dis_n
        print(f"    separation   : {sep:+.1f} points"
              f"   {'-> a usable gate' if sep > 15 else '-> too weak to route on'}")
    print(f"\n    vote distribution (how many of {K} picked the winner): "
          + ", ".join(f"{k}:{v}" for k, v in sorted(buckets.items(), reverse=True)))


if __name__ == "__main__":
    main()
