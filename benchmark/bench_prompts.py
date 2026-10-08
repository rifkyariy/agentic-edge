#!/usr/bin/env python3
"""Send a fixed prompt set (agent_prompts.py) through one engine, greedily, and
record the replies in lm-eval's sample format, so replay_lookup.py and
ae_gate.py --diff read them unchanged.

    ./bench_prompts.py --engine llama --model e2b --prompts prompts_bfcl.jsonl --out DIR
    ./bench_prompts.py --engine lg    --model e2b --prompts prompts_bfcl.jsonl --out DIR
    ./bench_prompts.py --engine ae    --model e2b --flags "-reuse -ngram -block 3" ...

llama is llama-server with the S1 baseline flags (-c 8192 -ngl 99 -rea off
--reasoning-budget -1 --cache-ram 0); lg / ae are little-gemma / the S9
build behind lg_openai_shim.py, thinking off. DIR gets samples_<set>.jsonl,
requests.jsonl (wall time per request, plus llama-server's own timings),
engine.log, and .done when every prompt was answered. Run it under
run_measured.sh (queue kind raw) for telemetry. stdlib only.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.expanduser("~/research")
MODELS = {"e2b": "gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf", "e4b": "gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf"}
BIN = {"llama": os.path.expanduser("~/build/llama.cpp/build/bin/llama-server"),
       "lg": os.path.expanduser("~/build/little-gemma/build/run-cuda-i8"),
       "ae": os.path.expanduser("~/build/little-gemma-ae/build/run-cuda-i8")}


def post(port, body):
    req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % port,
                                 json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=3600))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=BIN, required=True)
    ap.add_argument("--model", choices=MODELS, required=True)
    ap.add_argument("--flags", default="", help="little-gemma engine switches (ae)")
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=8091)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=False)
    model = os.path.join(R, "models", MODELS[args.model])
    if args.engine == "llama":
        cmd = [BIN["llama"], "-m", model, "-c", "8192", "--host", "127.0.0.1", "--port", str(args.port),
               "-ngl", "99", "-rea", "off", "--reasoning-budget", "-1", "--cache-ram", "0"]
    else:
        cmd = [sys.executable, os.path.join(HERE, "lg_openai_shim.py"), "--engine", BIN[args.engine],
               "-m", model, "--thinking", "off", "--think", "-1", "--port", str(args.port),
               "--sock", "/tmp/bench-prompts.sock", "--engine-flags=" + args.flags]
    log = open(os.path.join(args.out, "engine.log"), "w")
    proc = subprocess.Popen(cmd, stdout=log, stderr=log)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # a cancelled job still stops its engine
    try:
        for _ in range(300):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/health" % args.port, timeout=2)
                break
            except OSError:
                if proc.poll() is not None:
                    sys.exit("engine exited during load; see engine.log")
                time.sleep(2)
        rows = [json.loads(line) for line in open(args.prompts)]
        name = os.path.splitext(os.path.basename(args.prompts))[0].replace("prompts_", "")
        with open(os.path.join(args.out, "samples_%s.jsonl" % name), "w") as sf, \
                open(os.path.join(args.out, "requests.jsonl"), "w") as rf:
            for i, r in enumerate(rows):
                t0 = time.time()
                out = post(args.port, {"model": "bench", "messages": r["messages"], "temperature": 0,
                                       "max_tokens": r["max_tokens"], "stop": r["stop"], "seed": 1234})
                dt = time.time() - t0
                reply = out["choices"][0]["message"]["content"]
                sf.write(json.dumps({"doc_id": i, "doc": {"category": r["category"], "id": r["id"]},
                                     "arguments": {"gen_args_0": {"arg_0": [json.dumps(r["messages"])],
                                                                  "arg_1": {"until": r["stop"], "max_gen_toks": r["max_tokens"]}}},
                                     "resps": [[reply]]}) + "\n")
                rf.write(json.dumps({"id": r["id"], "wall_s": round(dt, 3), "chars": len(reply),
                                     "timings": out.get("timings"), "usage": out.get("usage")}) + "\n")
                sf.flush()
                rf.flush()
        open(os.path.join(args.out, ".done"), "w").close()
        print("%s %s %s: %d prompts" % (args.engine, args.model, name, len(rows)), flush=True)
        return 0
    finally:
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    sys.exit(main())
