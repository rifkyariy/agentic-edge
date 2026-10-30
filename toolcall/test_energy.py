#!/usr/bin/env python3
"""Self-check for energy.py on synthetic samples. Run: python3 test_energy.py"""
from energy import integrate, summarize

ts = [float(t) for t in range(100)]
# 5 W idle, 10 W while the one task runs from t=40 to t=50
w = [10.0 if 40 <= t <= 50 else 5.0 for t in range(100)]
assert abs(integrate(ts, w, 0, 10) - 50) < 1e-9
assert abs(integrate(ts, w, 41.5, 42.25) - 7.5) < 1e-9  # between two samples
assert abs(integrate(ts, [float(t) for t in range(100)], 2.5, 3.5) - 3.0) < 1e-9  # interpolated ramp

samples = [(t, x, 2000, 90, 55.0) for t, x in zip(ts, w)]
rec = {"id": "a", "start_epoch": 40.0, "end_epoch": 50.0, "usage": {"completion_tokens": 20, "prompt_tokens": 100},
       "timings": {"prompt_n": 100, "prompt_ms": 2000.0, "predicted_n": 20, "predicted_ms": 8000.0},
       "outcome": "ok", "calls": [{"name": "f", "args": {"x": 1}}]}
s = summarize(samples, [rec], idle=30)
assert s["idle_w"] == 5.0 and s["idle_post_w"] == 5.0, s
assert s["energy_j"] == 100.0 and s["energy_above_idle_j"] == 50.0, s
assert s["j_per_generated_token"] == 5.0 and s["per_task"]["a"] == {"j": 100.0, "j_above_idle": 50.0}, s
# main's set: decode-only power (t=42..50), phase speeds, J per token of either kind
assert s["generation_mean_w"] == 10.0 and s["work_peak_w"] == 10.0, s
assert s["prefill_tok_s"] == 50.0 and s["decode_tok_s"] == 2.5 and s["decode_tok_s_per_w"] == 0.25, s
assert s["j_per_token_all"] == round(100 / 120, 3) and s["model_calls"] == 1, s
# per group, with pass rate; a JSON chain counts each turn as its own model call
task = {"id": "a", "category": "chain", "n": 3, "names": {}, "ground_truth": [{"f": {"x": [1]}}]}
g = summarize(samples, [rec], idle=30, tasks={"a": task})["by_group"]
assert g["chain"] == g["chain_len02-05"] == {"tasks": 1, "acc": 1.0, "j_per_task": 100.0, "j_per_task_above_idle": 50.0,
                                            "s_per_task": 10.0, "passes_per_wh": 36.0}, g
two = {**rec, "turns": [{"start_epoch": 40.0, "timings": rec["timings"]}, {"start_epoch": 45.0, "timings": rec["timings"]}]}
assert summarize(samples, [two], idle=30)["model_calls"] == 2
# an old run without epochs: whole log, no idle, no per-task split
old = summarize(samples, [{"id": "a", "usage": rec["usage"]}])
assert old["idle_w"] is None and old["per_task"] is None and old["work_s"] == 99.0, old
print("energy.py self-check: all passed")
