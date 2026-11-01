#!/usr/bin/env python3
"""Re-execute a Code Mode run's recorded scripts under another harness, without the model.

Valid because both code modes send the model the same prompt and decoding is
deterministic (temp 0, top-k 1, seed 42; the clock-locked T0 reruns matched on
301/301 tasks), so a full rerun would produce the same scripts.

    python3 reexec.py tasks/t0.jsonl runs/t0-code-q8_0-off-e2b runs/t0-code-lenient-q8_0-off-e2b
    python3 reexec.py --repair-iife tasks/t1.jsonl runs/t1-code-lenient-turbo3-off-e4b runs/<name>-iife

--repair-iife also fixes `async () => {...}();` scripts first (codemode.repair_iife), a
sensitivity check: the lenient harness the runs used does not.
"""
import json, sys
from pathlib import Path

from run import run_code
import codemode

repair = "--repair-iife" in sys.argv
tasks_path, src, dst = [a for a in sys.argv[1:] if a != "--repair-iife"]
src, dst = Path(src), Path(dst)
T = {t["id"]: t for t in map(json.loads, open(tasks_path))}
dst.mkdir(parents=True, exist_ok=True)
with (dst / "results.jsonl").open("w") as f:
    for rec in map(json.loads, (src / "results.jsonl").open()):
        runs = rec.get("code", {}).get("runs")
        if runs:  # no_script and bad_tool_args never reach the sandbox, so they stay as they were
            calls = [{"name": codemode.CODE_TOOL, "args": {"code": codemode.repair_iife(r["code"]) if repair else r["code"]}}
                     for r in runs]
            rec["code"] = run_code(T[rec["id"]], calls, lenient=True)
            rec["calls"] = rec["code"].pop("calls")
        f.write(json.dumps(rec) + "\n")
(dst / "reexec.json").write_text(json.dumps({"source": str(src), "harness": "code-lenient" + ("+repair-iife" if repair else "")}, indent=2))
