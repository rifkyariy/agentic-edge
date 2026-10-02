"""Build the app's bundled MMLU-Pro prompts: the exact lm-eval mmlu_pro chat
messages (5-shot CoT, same-subject validation shots) for the agentic-edge
subsets s1/s2/s3.

    python3 prep/build_prompts.py            # inside agentic-edge: reads findings/ directly

Stdlib only. Pulls TIGER-Lab/MMLU-Pro through the HF datasets-server (cached in
prep/.cache). Subset ids come from the repo's findings/stdbench. It asserts byte equality against the committed lm-eval
s1 samples (findings/stdbench/mmlupro100-e2b) before writing anything.
"""
import argparse, glob, gzip, json, os, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))  # benchmark/apps/ios/prep -> repo root
OUT = os.path.join(HERE, "..", "GemmaBench", "Resources", "mmlupro.json")
API = "https://datasets-server.huggingface.co/rows?dataset=TIGER-Lab/MMLU-Pro&config=default&split={}&offset={}&length=100"


def page(split, off):
    # One cache file per page: datasets-server rate-limits (429) and resets connections,
    # so a rerun resumes instead of starting over.
    cache = os.path.join(HERE, ".cache", f"{split}-{off}.json")
    if os.path.exists(cache):
        return json.load(open(cache))
    for wait in (0, 5, 15, 30, 60, 120):
        time.sleep(wait)
        try:
            p = json.load(urllib.request.urlopen(API.format(split, off), timeout=60))
            break
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
    else:
        raise SystemExit(f"datasets-server unavailable at {split} offset {off}; rerun to resume")
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    json.dump(p, open(cache, "w"))
    return p


def rows(split):
    out, off = [], 0
    while True:
        p = page(split, off)
        out += [r["row"] for r in p["rows"]]
        off += 100
        if off >= p["num_rows_total"]:
            return out


def question(x):
    s = "Question:\n" + x["question"] + "\nOptions:\n"
    s += "".join(f"{'ABCDEFGHIJKLMNOP'[i]}. {o.strip()}\n" for i, o in enumerate(x["options"]))  # lm-eval strips option text
    return s + "Answer: Let's think step by step."


def messages(doc, shots, subject):
    # lm-eval mmlu_pro, --apply_chat_template, fewshot_as_multiturn: system =
    # description, then one user/assistant turn per shot, then the question.
    m = [{"role": "system", "content": f'The following are multiple choice questions (with answers) about {subject}. Think step by step and then finish your answer with "the answer is (X)" where X is the correct letter choice.\n'}]
    for s in shots:
        m += [{"role": "user", "content": question(s)},
              {"role": "assistant", "content": s["cot_content"].replace("A: Let's think step by step.", "").strip()}]
    return m + [{"role": "user", "content": question(doc)}]


def build(test, val, ids):
    out = []
    for task, qids in ids["question_ids"].items():
        subj = task.removeprefix("mmlu_pro_").replace("_", " ")
        pool = [x for x in test if x["category"] == subj]
        shots = [x for x in val if x["category"] == subj][:5]
        pos = {x["question_id"]: i for i, x in enumerate(pool)}
        for q in qids:
            d = pool[pos[q]]
            out.append({"task": task, "doc_id": pos[q], "question_id": q, "target": d["answer"],
                        "question": d["question"], "options": d["options"], "src": d["src"],
                        "messages": messages(d, shots, subj)})
    return out


def check(ref, s1):
    got = {(x["task"], x["doc_id"]): x["messages"] for x in s1}
    n = 0
    for f in glob.glob(os.path.join(ref, "findings/stdbench/mmlupro100-e2b/samples_*.jsonl")):
        task = os.path.basename(f)[len("samples_"):].rsplit("_2026", 1)[0]
        for line in open(f):
            d = json.loads(line)
            want = json.loads(d["arguments"]["gen_args_0"]["arg_0"][0])
            assert got[(task, d["doc_id"])] == want, f"prompt mismatch {task} doc {d['doc_id']}"
            n += 1
    assert n == 100, n
    print("s1 prompts byte-identical to lm-eval reference:", n)


def references(ref):
    """Pi/Jetson scores and prompt-token totals per model x subset, for the in-app comparison."""
    x = json.load(gzip.open(os.path.join(ref, "findings/export/experiment-full.json.gz")))
    out = {}
    for board, b in x["boards"].items():
        for name, r in b["runs"].items():
            if r.get("status") != "done" or name == "mmlupro100-e4b":  # superseded duplicate, see export README
                continue
            key = f"{r['model']}-{r['subset'] or 's1'}"
            out.setdefault(key, {})[board] = {
                "run": name, "score": r["summary"]["score"],
                "decode_tok_s": (r.get("summary_json") or {}).get("decode_tok_s"),
                "minutes": r["summary"].get("minutes"),
                "energy_wh": (r.get("summary_json") or {}).get("energy_wh"),
                "mean_w": (r.get("summary_json") or {}).get("mean_w"),
                "j_per_token": (r.get("summary_json") or {}).get("j_per_token"),
                "prompt_tokens_total": sum(t["pt"] for t in r.get("timeline", [])),
                # llama.cpp counts only uncached tokens, and lm-eval sends a subject's questions
                # back to back, so later prompts reuse the 5-shot prefix: only the first request
                # is a full prompt, and only it can be compared token for token.
                "first_prompt_tokens": (r.get("timeline") or [{}])[0].get("pt"),
            }
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default=REPO, help="agentic-edge checkout (default: this repo)")
    a = ap.parse_args()
    test, val = rows("test"), rows("validation")
    subsets = {t: build(test, val, json.load(open(os.path.join(a.ref, "findings", "stdbench", f"mmlupro_subset100_{t}_ids.json")))) for t in ("s1", "s2", "s3")}
    if a.ref:
        check(a.ref, subsets["s1"])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"source": "TIGER-Lab/MMLU-Pro test, lm-eval mmlu_pro 5-shot CoT chat prompts",
               "generation": {"max_gen_toks": 2048, "until": ["Question:"], "temperature": 0.0, "do_sample": False},
               "extraction": r"answer is \(?([ABCDEFGHIJ])\)?",
               "subsets": subsets,
               "reference": references(a.ref) if a.ref else {}},
              open(OUT, "w"), ensure_ascii=False)
    print("wrote", OUT, {k: len(v) for k, v in subsets.items()})
