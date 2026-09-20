"""Build a stratified MMLU-Pro subset.

    python3 mmlupro_subset.py --seed 20260918 --n 100 --tag s1

Proportional allocation over all 14 subjects (largest remainder, at least one
each). Independent seeds give independent subsets: pooling them tightens the
standard error, and the spread between them is an empirical estimate of
question-sampling variance (Miller 2024, arXiv:2411.00640; Madaan et al. 2024,
arXiv:2406.10229) rather than a formula.
"""
import argparse, json, random, os, urllib.request
from datasets import load_dataset

ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, default=20260918)
ap.add_argument("--n", type=int, default=100)
ap.add_argument("--tag", default="s1", help="file suffix, e.g. s1 -> mmlupro_subset100_s1_*.json")
ap.add_argument("--exclude", default="", help="comma-separated tags whose questions to avoid")
args = ap.parse_args()
os.chdir(os.path.expanduser("~/Research/stdbench"))
test = load_dataset("TIGER-Lab/MMLU-Pro", split="test")
val = load_dataset("TIGER-Lab/MMLU-Pro", split="validation")
cats = sorted(set(test["category"]))
by = {c: [i for i, x in enumerate(test["category"]) if x == c] for c in cats}
N, total = args.n, len(test)
# Proportional allocation (largest remainder), at least 1 per subject.
raw = {c: N * len(by[c]) / total for c in cats}
alloc = {c: max(1, int(raw[c])) for c in cats}
for c in sorted(cats, key=lambda c: raw[c] - int(raw[c]), reverse=True):
    if sum(alloc.values()) >= N: break
    alloc[c] += 1
# Independent subsets must not overlap, or pooling would double-count.
taken = set()
for t in [x for x in args.exclude.split(",") if x]:
    f = f"mmlupro_subset{args.n}_{t}_ids.json"
    if os.path.exists(f):
        taken |= {q for v in json.load(open(f))["question_ids"].values() for q in v}
rng = random.Random(args.seed)
samples, qids = {}, {}
for c in cats:
    pool = [i for i in range(len(by[c])) if test[by[c][i]]["question_id"] not in taken]
    pick = sorted(rng.sample(pool, min(alloc[c], len(pool))))  # positions within the subject task
    task = "mmlu_pro_" + c.replace(" ", "_")
    samples[task] = pick
    qids[task] = [test[by[c][p]]["question_id"] for p in pick]
print("total", sum(len(v) for v in samples.values()), {k: len(v) for k, v in samples.items()})
json.dump(samples, open(f"mmlupro_subset{args.n}_{args.tag}_samples.json", "w"))
json.dump({"seed": args.seed, "n": args.n, "tag": args.tag, "method": "proportional stratified by category, largest remainder, min 1; indices are positions within each lm-eval mmlu_pro_<subject> task (test split filtered by category, dataset order)", "question_ids": qids}, open(f"mmlupro_subset{args.n}_{args.tag}_ids.json", "w"), indent=1)
# Longest prompt estimate: 5 same-subject CoT examples + the question, tokenized by the live server.
def fmt(x, cot):
    s = "Question:\n" + x["question"] + "\nOptions:\n" + "\n".join(f"{'ABCDEFGHIJ'[i]}. {o}" for i, o in enumerate(x["options"]))
    return s + "\n" + (x["cot_content"] if cot else "Answer: Let's think step by step.")
lens = {}
for c in cats:
    shots = "\n\n".join(fmt(x, True) for x in [v for v in val if v["category"] == c][:5])
    longest = max((test[by[c][p]] for p in samples.get("mmlu_pro_" + c.replace(" ", "_"), [])), key=lambda x: len(x["question"]) + sum(map(len, x["options"])))
    body = json.dumps({"content": shots + "\n\n" + fmt(longest, False)}).encode()
    try:
        r = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/tokenize", data=body, headers={"Content-Type": "application/json"}), timeout=30)
        lens[c] = len(json.load(r)["tokens"])
    except Exception as e:
        lens[c] = f"ERR {e}"
print("longest prompt tokens per subject:", lens)
