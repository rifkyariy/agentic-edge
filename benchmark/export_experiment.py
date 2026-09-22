#!/usr/bin/env python3
"""One JSON with the whole MMLU-Pro baseline experiment, both boards.

    python3 benchmark/export_experiment.py --out findings/experiment-export.json

Runs on the Mac, not the boards. Every per-run figure comes from
`run_detail.py` over ssh — the documented on-demand path (AGENTS §7) — so this
adds no new queries to either device.

What lands in the file, per run: the score and its stderr, per-request token
timings (prefill/decode tokens, milliseconds and tok/s) each with the device
conditions measured across that request's own window (mean/peak watts, joules
integrated over the window, J/token, cpu, gpu, peak temp, server RSS), the
telemetry series, the run's summary.json in full, and the questions with what
the model answered.

    --raw-telemetry   every 1Hz sample rather than the ~700-point chart series
                      (~10x larger; this is the "all power" option)
    --no-responses    drop the model's answer text, keeping the grading
    --runs a,b        export only these run names
"""
import argparse
import json
import subprocess
import sys
import time

BOXES = {
    "pi": {"label": "Raspberry Pi 5", "host": "MITLAB-EDGE",
           "py": "~/Research/eval-venv/bin/python3",
           "repo": "~/Research/agentic-edge",
           "hardware": {"soc": "Broadcom BCM2712", "cpu": "4x Cortex-A76",
                        "gpu": None, "ram_mb": 8062, "swap_mb": 0,
                        "power_sense": "PMIC rails via vcgencmd pmic_read_adc",
                        "llama_flags": "-t 3 -c 8192 -rea off --reasoning-budget -1 --cache-ram 0"}},
    "jetson": {"label": "Jetson Orin Nano", "host": "MITLAB-JETSON",
               "py": "~/venvs/eval/bin/python3",
               "repo": "~/research/agentic-edge",
               "hardware": {"soc": "NVIDIA Orin (Super dev kit)", "cpu": "6x Cortex-A78AE",
                            "gpu": "Ampere, compute capability sm_87", "ram_mb": 7485,
                            "swap_mb": 0, "power_mode": "15W",
                            "power_sense": "INA3221 hwmon VDD_IN",
                            "llama_flags": "-c 8192 -ngl 99 -rea off --reasoning-budget -1 --cache-ram 0"}},
}

SSH = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]


def ssh_json(box, cmd):
    out = subprocess.run(["ssh", *SSH, box["host"], cmd],
                         capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"{box['host']}: {out.stderr.strip()[:300]}")
    txt = out.stdout[out.stdout.index("{"):]
    return json.loads(txt)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="findings/experiment-export.json")
    ap.add_argument("--raw-telemetry", action="store_true")
    ap.add_argument("--no-responses", action="store_true")
    ap.add_argument("--runs", default=None, help="comma-separated run names")
    args = ap.parse_args()

    only = set(args.runs.split(",")) if args.runs else None
    export = {
        "experiment": "MMLU-Pro baseline, Raspberry Pi 5 vs Jetson Orin Nano",
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "protocol": {
            "task": "lm-evaluation-harness mmlu_pro, unmodified",
            "shots": 5, "chain_of_thought": True, "decoding": "greedy",
            "max_gen_toks": 2048, "extraction": "answer is (X)",
            "subsets": {"s1": 20260918, "s2": 20260919, "s3": 20260920},
            "questions_per_subset": 100,
            "condition": "baseline, thinking off",
            "serving": "llama.cpp, -c 8192 --cache-ram 0 -rea off --reasoning-budget -1",
            "note": ("-rea is --reasoning-format, not a reasoning toggle. Without it "
                     "llama.cpp splits the model's thinking into reasoning_content, "
                     "which lm-eval does not read. Jetson runs before 2026-09-22 "
                     "lacked it and are archived, not included here."),
            "power": ("board DC draw; PMIC rails on the Pi, INA3221 VDD_IN on the "
                      "Jetson. Excludes PSU conversion loss. Not wall power."),
        },
        "telemetry_resolution": "1Hz raw" if args.raw_telemetry else "downsampled to ~700 points",
        "boards": {},
    }

    for bid, box in BOXES.items():
        print(f"== {box['label']}", file=sys.stderr)
        base = ssh_json(box, f"{box['py']} {box['repo']}/benchmark/run_detail.py --baseline")
        board = {"label": box["label"], "host": box["host"],
                 "hardware": box["hardware"], "results_root": base.get("root"),
                 "archived_failed_runs": base.get("failed", []), "runs": {}}

        for row in base.get("runs", []):
            name = row["run"]
            if only and name not in only:
                continue
            print(f"   {name} …", file=sys.stderr, end=" ", flush=True)
            flags = "--raw-telemetry" if args.raw_telemetry else ""
            d = ssh_json(box, f"{box['py']} {box['repo']}/benchmark/run_detail.py "
                              f"--run {name} {flags}")
            if args.no_responses:
                for q in d.get("questions") or []:
                    q.pop("resp", None)
            d["model"] = row["model"]
            d["subset"] = row["subset"]
            d["summary_json"] = row.get("device")
            board["runs"][name] = d
            print(f"{len(d.get('timeline') or [])} requests, "
                  f"{len(d.get('telemetry') or [])} samples", file=sys.stderr)
        export["boards"][bid] = board

    with open(args.out, "w") as f:
        json.dump(export, f, indent=1)
    import os
    print(f"\nwrote {args.out}  ({os.path.getsize(args.out)/1024/1024:.1f} MB)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
