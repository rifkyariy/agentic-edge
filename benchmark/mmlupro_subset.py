import json, random, os, urllib.request
from datasets import load_dataset
os.chdir(os.path.expanduser("~/Research/stdbench"))
test = load_dataset("TIGER-Lab/MMLU-Pro", split="test")
val = load_dataset("TIGER-Lab/MMLU-Pro", split="validation")
cats = sorted(set(test["category"]))
by = {c: [i for i, x in enumerate(test["category"]) if x == c] for c in cats}
N, total = 100, len(test)
# Proportional allocation (largest remainder), at least 1 per subject.
raw = {c: N * len(by[c]) / total for c in cats}
alloc = {c: max(1, int(raw[c])) for c in cats}
for c in sorted(cats, key=lambda c: raw[c] - int(raw[c]), reverse=True):
    if sum(alloc.values()) >= N: break
    alloc[c] += 1
rng = random.Random(20260918)
samples, qids = {}, {}
for c in cats:
    pick = sorted(rng.sample(range(len(by[c])), alloc[c]))  # positions within the subject task
    task = "mmlu_pro_" + c.replace(" ", "_")
    samples[task] = pick
    qids[task] = [test[by[c][p]]["question_id"] for p in pick]
print("total", sum(len(v) for v in samples.values()), {k: len(v) for k, v in samples.items()})
json.dump(samples, open("mmlupro_subset100_samples.json", "w"))
json.dump({"seed": 20260918, "method": "proportional stratified by category, largest remainder, min 1; indices are positions within each lm-eval mmlu_pro_<subject> task (test split filtered by category, dataset order)", "question_ids": qids}, open("mmlupro_subset100_ids.json", "w"), indent=1)
# Longest prompt estimate: 5 same-subject CoT examples + the question, tokenized by the live server.
def fmt(x, cot):
    s = "Question:\n" + x["question"] + "\nOptions:\n" + "\n".join(f"{'ABCDEFGHIJ'[i]}. {o}" for i, o in enumerate(x["options"]))
    return s + "\n" + (x["cot_content"] if cot else "Answer: Let's think step by step.")
lens = {}
for c in cats:
    shots = "\n\n".join(fmt(x, True) for x in [v for v in val if v["category"] == c][:5])
    longest = max((test[by[c][p]] for p in samples["mmlu_pro_" + c.replace(" ", "_")]), key=lambda x: len(x["question"]) + sum(map(len, x["options"])))
    body = json.dumps({"content": shots + "\n\n" + fmt(longest, False)}).encode()
    try:
        r = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/tokenize", data=body, headers={"Content-Type": "application/json"}), timeout=30)
        lens[c] = len(json.load(r)["tokens"])
    except Exception as e:
        lens[c] = f"ERR {e}"
print("longest prompt tokens per subject:", lens)
