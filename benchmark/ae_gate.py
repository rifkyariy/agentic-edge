#!/usr/bin/env python3
"""Quality gate for the proposed engine (S9): replay recorded greedy questions
through an engine configuration and require byte-identical replies.

Every S9 switch is meant to change only speed: drafts are verified greedily,
and a restored prefix holds the same rows a fresh prefill writes. If the
replies to already-answered questions come back byte for byte, accuracy is
unchanged by construction and the run only has to measure cost. A mismatch
is the finding, not noise: greedy decoding has no noise to hide behind.

    ./ae_gate.py --model e2b --flags "-ngram -reuse -block 4" \\
        --against ~/research/stdbench/mmlupro100-lg-e2b-s1 --per-category 3

Under the queue, as a raw job (telemetry, and the dashboard shows it):

    ./queue_ctl.py --add '{"kind":"raw","params":{"label":"ae-sweep-e2b-b4",
        "command":"./ae_gate.py --model e2b --flags \\"-reuse -ngram -block 4\\" --against
        /home/ari/research/stdbench/mmlupro100-lg-e2b-s1 --per-category 2
        --out /home/ari/research/stdbench/ae-sweep-e2b-b4"}}'

Questions are replayed in category order, so consecutive requests share their
few-shot prefix the way a real run's do. The engine's own stderr (turn,
ngram, reuse, mtp lines) is kept in --log for throughput.

stdlib only; runs on the board, one job per device (AGENTS rule 9).
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

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = {"e2b": "gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf", "e4b": "gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf"}


def post(port, body, timeout=3600):
    req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % port,
                                 json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def samples(run_dir, per_category):
    for f in sorted(glob.glob(os.path.join(run_dir, "*", "samples_mmlu_pro_*.jsonl"))):
        with open(f) as fh:
            for i, line in enumerate(fh):
                if i >= per_category:
                    break
                yield json.loads(line)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", choices=MODELS, required=True)
    ap.add_argument("--flags", default="", help="engine switches under test")
    ap.add_argument("--against", required=True, help="stdbench run dir whose replies are the reference")
    ap.add_argument("--per-category", type=int, default=3)
    ap.add_argument("--engine", default=os.path.expanduser("~/build/little-gemma-ae/build/run-cuda-i8"))
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--log", default="/tmp/ae_gate.log")
    ap.add_argument("--out", help="a run directory to create; the engine log is kept there as engine.log "
                                  "(use this under the queue: run_measured.sh takes a plain command)")
    args = ap.parse_args()
    if args.out:
        os.makedirs(args.out, exist_ok=False)
        args.log = os.path.join(args.out, "engine.log")
    # a cancelled job gets SIGTERM: exit through finally, so the shim (and with
    # it the engine, which dies with its parent) is never left holding the GPU
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    research = os.path.expanduser("~/research")
    shim = [sys.executable, os.path.join(HERE, "lg_openai_shim.py"), "--engine", args.engine,
            "-m", os.path.join(research, "models", MODELS[args.model]), "--thinking", "off",
            "--think", "-1", "--port", str(args.port), "--sock", "/tmp/ae-gate.sock",
            "--engine-flags", args.flags]
    log = open(args.log, "w")
    proc = subprocess.Popen(shim, stdout=log, stderr=log)
    try:
        for _ in range(300):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/health" % args.port, timeout=2)
                break
            except OSError:
                if proc.poll() is not None:
                    sys.exit("engine exited during load; see %s" % args.log)
                time.sleep(2)
        same = diff = 0
        t_all = 0.0
        for s in samples(args.against, args.per_category):
            gen = s["arguments"]["gen_args_0"]["arg_1"]
            body = {"model": "gate", "messages": json.loads(s["arguments"]["gen_args_0"]["arg_0"][0]),
                    "max_tokens": gen["max_gen_toks"], "temperature": 0, "stop": gen["until"], "seed": 1234}
            t0 = time.time()
            got = post(args.port, body)["choices"][0]["message"]["content"]
            dt = time.time() - t0
            t_all += dt
            want = s["resps"][0][0]
            ok = got == want
            same += ok
            diff += not ok
            print("%-5s %-16s doc %-5d %6.1fs %5d chars%s" % (
                "same" if ok else "DIFF", s["doc"]["category"], s["doc_id"], dt, len(got),
                "" if ok else "  first difference at char %d" % next(
                    (i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))),
                flush=True)
        result = "%s %r: %d/%d byte-identical, %.0fs of requests" % (
            args.model, args.flags, same, same + diff, t_all)
        print("== " + result, flush=True)
        # The queue counts a job done only by this marker. A DIFF is a finding,
        # not a broken run, so it is written either way and carries the result;
        # "failed" in the queue then means a crash or a cancel, nothing else.
        if args.out:
            with open(os.path.join(args.out, ".done"), "w") as f:
                f.write(result + (", %d DIFF" % diff if diff else "") + "\n")
        return 1 if diff else 0
    finally:
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    sys.exit(main())
