#!/usr/bin/env python3
"""Replay prompt-lookup drafting on recorded greedy replies: how many tokens
per verify pass a context-copying drafter would have earned, with no device
time (manuscript Sec. III and Table VII).

    python3 benchmark/replay_lookup.py tokenize --via MITLAB-JETSON   # once: fill the token cache
    python3 benchmark/replay_lookup.py                                # Table VII + Sec. III, offline

Because decoding is greedy, the effect of any drafter is exact from the
replies alone: a drafted token would have been accepted exactly where it
equals the recorded next token. The drafter is the one CoPR runs (Sec. IV-A):
at each step, find the most recent earlier occurrence of the last 3 tokens of
prompt + reply-so-far (falling back to 2) and propose the up to B-1 tokens
that followed it. One verify pass emits the accepted prefix plus the model's
own next token, so tokens per pass = reply tokens / passes.

Tokens come from the Gemma 4 vocabulary through llama.cpp's own tokenizer
(llama-tokenize, vocabulary only; any build reading the same GGUF gives the
same ids). Prompts are rendered with lg_openai_shim.render, which tests hold
byte-identical to llama-server's chat template. Token ids are cached in
findings/replay/tokens.jsonl.gz, keyed by the text's sha1, so the replay
itself needs no tokenizer once the cache is filled.

Reply sets (all committed):
    lg-e2b         little-gemma E2B, Jetson   findings/runs/jetson/mmlupro100-lg-e2b-s*
    pi-e2b, pi-e4b llama.cpp, Raspberry Pi 5  findings/export/ (answers, matched to prompts by question)
    gsm8k-e2b      llama.cpp E2B tinyGSM8k    findings/stdbench/B-e2b + tiny1024-e2b (200 replies)
    jetson-e2b/e4b llama.cpp, Jetson          findings/runs/jetson/mmlupro100-e?b-s* (not in the paper)
The Pi's thinking-on replies (a Table VII row) are not in the repository.
Stdlib only.
"""
import argparse
import ast
import glob
import gzip
import hashlib
import json
import os
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lg_openai_shim import render  # noqa: E402

ROOT = os.path.dirname(HERE)
F = os.path.join(ROOT, "findings")
CACHE = os.path.join(F, "replay", "tokens.jsonl.gz")
GGUF = "~/research/models/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf"   # E2B and E4B share the vocabulary
TOKENIZE = "~/build/engines/llama.cpp-a894dae/bin/llama-tokenize"


# ---------------------------------------------------------------- inputs

def _messages(sample):
    """lm-eval's chat request -> the message list llama-server received."""
    arg = sample["arguments"]["gen_args_0"]["arg_0"]
    if isinstance(arg, str):                 # older lm-eval wrote the list as its repr
        arg = ast.literal_eval(arg)
    return json.loads(arg[0])


def _lm_eval(paths, subset):
    """One row per question. lm-eval logs a GSM8K sample once per answer filter
    (strict, flexible); the reply is the same, so keep the first."""
    out, seen = [], set()
    for p in paths:
        opener = gzip.open if p.endswith(".gz") else open
        with opener(p, "rt") as fh:
            for line in fh:
                s = json.loads(line)
                key = (s["doc"].get("category", ""), s["doc_id"])
                if key in seen:
                    continue
                seen.add(key)
                out.append({"subset": subset, "key": key,
                            "question": s["doc"].get("question"),
                            "prompt": render(_messages(s), False), "reply": s["resps"][0][0]})
    return out


def jetson(row, model):
    out = []
    for s in ("s1", "s2", "s3"):
        out += _lm_eval([os.path.join(F, "runs", "jetson", "mmlupro100-%s%s-%s" % (row, model, s), "samples.jsonl.gz")], s)
    return out


def pi(model):
    """The Pi's baseline answers from the export, paired with the prompt lm-eval
    sent for the same question (identical on every board)."""
    prompts = {r["question"]: r for r in jetson("", model)}
    export = json.load(gzip.open(os.path.join(F, "export", "experiment-full.json.gz")))
    runs = export["boards"]["pi"]["runs"]
    names = {"e2b": ["mmlupro100-e2b", "mmlupro100-e2b-s2", "mmlupro100-e2b-s3"],
             "e4b": ["mmlupro100-e4b-s1", "mmlupro100-e4b-s2", "mmlupro100-e4b-s3"]}[model]
    out = []
    for n in names:
        for q in runs[n]["questions"]:
            ref = prompts[q["q"]]
            out.append({"subset": ref["subset"], "key": ref["key"], "question": q["q"],
                        "prompt": ref["prompt"], "reply": q["resp"]})
    return out


def gsm8k():
    out = []
    for d in ("B-e2b", "tiny1024-e2b"):
        out += _lm_eval(sorted(glob.glob(os.path.join(F, "stdbench", d, "samples_*.jsonl"))), d)
    return out


SETS = {
    "lg-e2b": lambda: jetson("lg-", "e2b"),
    "pi-e2b": lambda: pi("e2b"),
    "pi-e4b": lambda: pi("e4b"),
    "gsm8k-e2b": gsm8k,
    "jetson-e2b": lambda: jetson("", "e2b"),
    "jetson-e4b": lambda: jetson("", "e4b"),
}


# ---------------------------------------------------------------- tokens

def sha(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load_cache():
    cache = {}
    if os.path.exists(CACHE):
        with gzip.open(CACHE, "rt") as fh:
            for line in fh:
                e = json.loads(line)
                cache[e["sha1"]] = e["ids"]
    return cache


def tokenize(args):
    """Fill the cache: every prompt and reply of every set, deduplicated.
    Prompts keep their special tokens (the template's turn markers); replies
    are tokenized as plain text, as the model emitted them."""
    cache = load_cache()
    want = {}
    for name in SETS:
        for r in SETS[name]():
            for kind in ("prompt", "reply"):
                h = sha(r[kind])
                if h not in cache:
                    want[h] = (kind, r[kind])
    print("%d texts to tokenize (%d cached)" % (len(want), len(cache)), file=sys.stderr)
    if not want:
        return 0
    # one remote process for the lot: a JSONL of texts in, a JSONL of ids out
    job = [{"sha1": h, "special": k == "prompt", "text": t} for h, (k, t) in want.items()]
    script = r"""
import json, subprocess, sys, tempfile, os
tok, gguf = os.path.expanduser(sys.argv[1]), os.path.expanduser(sys.argv[2])
for line in sys.stdin:
    j = json.loads(line)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(j["text"]); path = f.name
    cmd = [tok, "-m", gguf, "-f", path, "--ids", "--log-disable", "--no-bos"]
    if not j["special"]:
        cmd.append("--no-parse-special")
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    os.unlink(path)
    ids = json.loads(out.strip().splitlines()[-1])
    print(json.dumps({"sha1": j["sha1"], "ids": ids}), flush=True)
"""
    cmd = ["python3", "-c", script, args.tokenizer, args.gguf]
    if args.via:
        cmd = ["ssh", args.via, " ".join(shlex.quote(c) for c in cmd)]
    proc = subprocess.run(cmd, input="".join(json.dumps(j) + "\n" for j in job),
                          capture_output=True, text=True, check=True)
    got = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    for e in got:
        cache[e["sha1"]] = e["ids"]
    with gzip.GzipFile(CACHE, "wb", mtime=0) as g:
        for h in sorted(cache):
            g.write((json.dumps({"sha1": h, "ids": cache[h]}, separators=(",", ":")) + "\n").encode())
    print("cached %d new, %d total -> %s" % (len(got), len(cache), os.path.relpath(CACHE, ROOT)), file=sys.stderr)
    return 0 if len(got) == len(job) else 1


# ---------------------------------------------------------------- replay

def replay_one(prompt, reply, width, ns=(3, 2)):
    """(passes, steps with a lookup match) for one reply at verify width B."""
    ctx = list(prompt)
    index = {n: {} for n in ns}          # n-gram -> end of its most recent occurrence

    def add(end):
        for n in ns:
            if end >= n:
                index[n][tuple(ctx[end - n:end])] = end

    for end in range(1, len(ctx)):       # every occurrence ending before the current tail
        add(end)
    i = passes = matched = 0
    while i < len(reply):
        draft = []
        for n in ns:
            if len(ctx) >= n:
                e = index[n].get(tuple(ctx[-n:]))
                if e is not None:
                    draft = ctx[e:e + width - 1]
                    break
        k = 0
        while k < len(draft) and i + k < len(reply) and draft[k] == reply[i + k]:
            k += 1
        emit = min(k + 1, len(reply) - i)
        for t in reply[i:i + emit]:
            add(len(ctx))                # the n-gram ending at the old tail is now "earlier"
            ctx.append(t)
        passes += 1
        matched += bool(draft)
        i += emit
    return passes, matched


def replay(rows, cache, width, skip=None):
    tokens = passes = matched = 0
    for r in rows:
        if skip and skip(r, cache):
            continue
        p, m = replay_one(cache[sha(r["prompt"])], cache[sha(r["reply"])], width)
        tokens += len(cache[sha(r["reply"])])
        passes += p
        matched += m
    return tokens / passes, matched / passes


def report(args):
    cache = load_cache()
    rows = {name: SETS[name]() for name in SETS}
    missing = [n for n, rs in rows.items() for r in rs
               if sha(r["prompt"]) not in cache or sha(r["reply"]) not in cache]
    if missing:
        print("token cache incomplete for: %s — run `replay_lookup.py tokenize --via <board>`"
              % ", ".join(sorted(set(missing))), file=sys.stderr)
        return 1

    def by_subset(name, width):
        subs = sorted({r["subset"] for r in rows[name]})
        vals = [replay([r for r in rows[name] if r["subset"] == s], cache, width)[0] for s in subs]
        return vals

    print("Sec. III — little-gemma E2B, 300 replies, 3-gram lookup (fallback 2)")
    for b in (2, 3, 4, 5):
        tpp, match = replay(rows["lg-e2b"], cache, b)
        print("  width %d: %.2f tokens per verify pass, lookup match on %.0f%% of steps" % (b, tpp, 100 * match))
    capped = lambda r, c: len(c[sha(r["reply"])]) >= 2048
    print("  width 3 without the replies that hit the 2,048 cap: %.2f (%d capped)"
          % (replay(rows["lg-e2b"], cache, 3, capped)[0], sum(capped(r, cache) for r in rows["lg-e2b"])))
    print("\nTable VII — tokens per verify pass, B=3 / B=4 (range over s1-s3 where a set has subsets)")
    for name, label in (("lg-e2b", "E2B MMLU-Pro, no thinking   little-gemma (Orin Nano)"),
                        ("pi-e2b", "E2B MMLU-Pro, no thinking   llama.cpp (Pi)"),
                        ("pi-e4b", "E4B MMLU-Pro, no thinking   llama.cpp (Pi)"),
                        ("gsm8k-e2b", "E2B GSM8K (200 replies)     llama.cpp (Pi)"),
                        ("jetson-e2b", "E2B MMLU-Pro, no thinking   llama.cpp (Orin Nano) *"),
                        ("jetson-e4b", "E4B MMLU-Pro, no thinking   llama.cpp (Orin Nano) *")):
        cells = []
        for b in (3, 4):
            if name in ("lg-e2b", "gsm8k-e2b"):
                cells.append("%.2f" % replay(rows[name], cache, b)[0])
            else:
                v = by_subset(name, b)
                cells.append("%.2f-%.2f" % (min(v), max(v)))
        print("  %-52s %-10s %s" % (label, cells[0], cells[1]))
    print("  E2B MMLU-Pro, thinking      llama.cpp (Pi)          not in the repository (Pi only)")
    print("  * not in the paper")
    tpp, match = replay(rows["pi-e2b"], cache, 4)
    print("\nSec. VII — Pi llama.cpp E2B replies at width 4: %.2f tokens per verify pass, match on %.0f%% of steps"
          % (tpp, 100 * match))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="report", choices=("report", "tokenize"))
    ap.add_argument("--via", help="ssh host that has llama-tokenize and the GGUF (tokenize only)")
    ap.add_argument("--tokenizer", default=TOKENIZE, help="llama-tokenize path on that host")
    ap.add_argument("--gguf", default=GGUF, help="a Gemma 4 GGUF on that host (vocabulary only)")
    args = ap.parse_args()
    return tokenize(args) if args.cmd == "tokenize" else report(args)


if __name__ == "__main__":
    sys.exit(main())
