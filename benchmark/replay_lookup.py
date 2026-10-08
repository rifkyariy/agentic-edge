#!/usr/bin/env python3
"""Predict prompt-lookup drafting from recorded greedy replies, before any engine
change is built or run.

Greedy output is fixed, so a draft would have been accepted exactly where it
equals the recorded next tokens: replaying a reply token by token gives the
acceptance a lookup drafter would see, with no model in the loop. Measured on
the Jetson (S9), live tokens per verify matched this replay within 0.03.

    ./replay_lookup.py --model ~/models/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf \\
        --server ~/llama.cpp/build/bin/llama-server --out replay.json \\
        RUN_DIR[:think] ...

RUN_DIR is an lm-eval output directory (samples_*.jsonl directly in it or one
level down); ":think" renders the prompt with the thinking-on system turn. Only
the tokenizer is used: llama-server runs on the CPU with -ngl 0, on a spare port.

stdlib only (plus llama-server for tokenization), like everything on the boards.
"""
import argparse
import glob
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lg_openai_shim import render  # noqa: E402  the prompt exactly as the engines saw it

PORT = 8099


def tokenize(text):
    req = urllib.request.Request("http://127.0.0.1:%d/tokenize" % PORT,
                                 json.dumps({"content": text, "add_special": False}).encode(),
                                 {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))["tokens"]


def lookup(h, k, nmax=3, nmin=2):
    """The up-to-k tokens that followed the most recent earlier occurrence of
    h's last nmax (else down to nmin) tokens; [] when nothing matches. The
    engine's ngram_draft (ae.patch) is the same search."""
    for n in range(nmax, nmin - 1, -1):
        if len(h) <= n:
            continue
        key = h[-n:]
        for s in range(len(h) - n - 1, -1, -1):
            if h[s:s + n] == key:
                return h[s + n:s + n + k]
    return []


def replay(prompt, reply, width):
    """(plain steps, drafted steps, accepted draft tokens) for a width-B verifier."""
    h, i, plain, spec, acc = list(prompt), 0, 0, 0, 0
    while i < len(reply):
        d = lookup(h, width - 1)
        if not d:
            plain += 1
            adv = 1
        else:
            a = 0
            while a < len(d) and i + a < len(reply) and d[a] == reply[i + a]:
                a += 1
            spec += 1
            acc += a
            adv = a + 1
        h += reply[i:i + adv]
        i += adv
    return plain, spec, acc


def samples(run_dir):
    files = sorted(glob.glob(os.path.join(run_dir, "samples_*.jsonl")) +
                   glob.glob(os.path.join(run_dir, "*", "samples_*.jsonl")))
    for f in files:
        seen = set()     # lm-eval logs a sample once per filter (GSM8K: strict + flexible);
        with open(f) as fh:   # the reply is the same, so count each document once
            for line in fh:
                s = json.loads(line)
                if s["doc_id"] in seen:
                    continue
                seen.add(s["doc_id"])
                yield s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="any Gemma 4 GGUF: only its tokenizer is read")
    ap.add_argument("--server", required=True, help="llama-server binary")
    ap.add_argument("--out", required=True, help="result JSON")
    ap.add_argument("--widths", default="2,3,4,5")
    ap.add_argument("runs", nargs="+", help="RUN_DIR or RUN_DIR:think")
    args = ap.parse_args()
    widths = [int(w) for w in args.widths.split(",")]

    srv = subprocess.Popen([args.server, "-m", args.model, "-ngl", "0", "-c", "512", "--cache-ram", "0",
                            "--host", "127.0.0.1", "--port", str(PORT)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # cancelled job: finally still stops the server
    try:
        for _ in range(180):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=2)
                break
            except OSError:
                if srv.poll() is not None:
                    sys.exit("tokenizer server exited during load")
                time.sleep(2)
        out = {"widths": widths, "runs": []}
        for spec in args.runs:
            run_dir, _, mode = spec.partition(":")
            rows = []
            for s in samples(os.path.expanduser(run_dir)):
                msgs = json.loads(s["arguments"]["gen_args_0"]["arg_0"][0])
                rows.append((tokenize(render(msgs, mode == "think")), tokenize(s["resps"][0][0])))
            total = sum(len(r) for _, r in rows)
            res = {"run": run_dir, "thinking": mode == "think", "replies": len(rows), "reply_tokens": total,
                   "capped": sum(len(r) >= 2040 for _, r in rows), "by_width": {}}
            for w in widths:
                plain = spec_n = acc = 0
                for p, r in rows:
                    a, b, c = replay(p, r, w)
                    plain += a
                    spec_n += b
                    acc += c
                steps = plain + spec_n
                res["by_width"][w] = {"tokens_per_step": round(total / steps, 3),
                                      "drafted_share": round(spec_n / steps, 3),
                                      "accepted_per_drafted_step": round(acc / max(spec_n, 1), 3)}
            out["runs"].append(res)
            print("%s%s: %d replies, %d tokens, %s" % (run_dir, " (think)" if res["thinking"] else "", len(rows), total,
                  ", ".join("B=%d %.2f" % (w, res["by_width"][w]["tokens_per_step"]) for w in widths)), flush=True)
        with open(args.out, "w") as f:
            json.dump(out, f, indent=1)
        return 0
    finally:
        srv.terminate()
        srv.wait()


if __name__ == "__main__":
    sys.exit(main())
