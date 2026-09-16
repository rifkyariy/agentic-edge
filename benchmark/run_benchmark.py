#!/usr/bin/env python3
"""Benchmark harness. One config in, one JSON result file out.

    python3 run_benchmark.py examples/llama_cpp.json
    python3 run_benchmark.py examples/proposed.json --repeat 5

Stdlib only — clone this repo on any device, edit a config file to point at
that device's engine/model/quant, run. Nothing to pip install. See README.md
for the config schema, what each engine adapter needs, and how to add cases.
"""
import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adapters


def gpu_info():
    """Best-effort CUDA telemetry: absent on the Pi, present on Jetson. Never
    fatal — a missing nvidia-smi just means this field is null in the result,
    which is itself part of the CUDA-vs-no-CUDA comparison."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,utilization.gpu",
             "--format=csv,noheader"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            name, mem, util = [x.strip() for x in out.stdout.splitlines()[0].split(",")]
            return {"name": name, "memory_used": mem, "utilization": util}
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def run_case(run_fn, cfg, case, repeat):
    out = []
    for n in range(repeat):
        print(f"  {case['id']} ({n + 1}/{repeat})...", end=" ", flush=True)
        r = run_fn(cfg, case)
        r["case_id"], r["category"], r["repeat_n"] = case["id"], case.get("category"), n
        if case.get("expected_substring") is not None:
            r["correct"] = case["expected_substring"].lower() in (r.get("text") or "").lower()
        if case.get("expected_tool") is not None:
            r["tool_correct"] = r.get("tool_called") == case["expected_tool"]
        out.append(r)
        print("ok" if r.get("ok") else f"FAILED: {r.get('error')}",
              f" total={r.get('total_s')}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", help="path to a config JSON file (see examples/)")
    ap.add_argument("--cases", default=os.path.join(os.path.dirname(__file__), "cases.json"))
    ap.add_argument("--repeat", type=int, default=None,
                    help="override config['repeat']")
    ap.add_argument("--out", default=None, help="result filename (default: auto)")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)
    with open(args.cases) as f:
        cases = json.load(f)
    repeat = args.repeat if args.repeat is not None else cfg.get("repeat", 1)

    run_fn = adapters.ENGINES.get(cfg["engine"])
    if not run_fn:
        sys.exit(f"unknown engine {cfg['engine']!r} — have: {', '.join(adapters.ENGINES)}")

    if cfg["engine"] == "proposed" and ("mtp" in cfg or "thinking" in cfg):
        print(f"configuring proposed architecture: mtp={cfg.get('mtp')} "
              f"thinking={cfg.get('thinking')} (restarts va-llm, waiting)...")
        adapters.configure_proposed(cfg)

    m = cfg.get("model", {})
    print(f"device={cfg.get('device')} engine={cfg['engine']} model={m.get('name')} "
          f"quant={m.get('quant')} cuda={cfg.get('cuda')} mtp={cfg.get('mtp')} "
          f"thinking={cfg.get('thinking')}  ({len(cases)} cases x{repeat})\n")

    results = []
    for case in cases:
        results += run_case(run_fn, cfg, case, repeat)

    ok = [r for r in results if r.get("ok")]
    totals = [r["total_s"] for r in ok if r.get("total_s") is not None]
    tps = [r["tokens_per_s"] for r in ok if r.get("tokens_per_s")]
    n_tool_cases = sum(1 for r in results if "tool_correct" in r)
    n_tool_ok = sum(1 for r in results if r.get("tool_correct"))
    n_ans_cases = sum(1 for r in results if "correct" in r)
    n_ans_ok = sum(1 for r in results if r.get("correct"))
    summary = {
        "n": len(results), "n_ok": len(ok),
        "avg_total_s": round(statistics.mean(totals), 3) if totals else None,
        "avg_tokens_per_s": round(statistics.mean(tps), 2) if tps else None,
        "tool_calls_correct": f"{n_tool_ok}/{n_tool_cases}" if n_tool_cases else None,
        "answers_correct": f"{n_ans_ok}/{n_ans_cases}" if n_ans_cases else None,
    }
    print("\nsummary:", json.dumps(summary))

    run = {
        "config": cfg, "host": platform.node(), "python": platform.python_version(),
        "gpu": gpu_info(), "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "summary": summary, "results": results,
    }

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(out_dir, exist_ok=True)
    tag = (f"{cfg.get('device', 'device')}-{cfg['engine']}-{m.get('name', 'model')}-"
           f"{m.get('quant', 'q')}-mtp{int(bool(cfg.get('mtp')))}-"
           f"think{int(bool(cfg.get('thinking')))}")
    fname = args.out or f"{time.strftime('%Y%m%d-%H%M%S')}-{tag}.json"
    path = os.path.join(out_dir, fname)
    with open(path, "w") as f:
        json.dump(run, f, indent=2)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
