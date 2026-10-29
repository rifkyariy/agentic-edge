# T0 results on the Jetson: JSON vs Code Mode, q8_0 vs TurboQuant

Stage: T0 baselines (plan §8), thinking off. All numbers come from the run folders in
[`toolcall/runs/`](../../toolcall/runs/), each with its `manifest.json`, `results.jsonl`,
`score.json` and `energy.json`.

## Setup

| | |
| --- | --- |
| Tasks | T0: 301 BFCL v4 tasks, the paper's Table 6 counts per category, seed 0 ([`build_t0.py`](../../toolcall/build_t0.py)) |
| Board | Jetson Orin Nano 8 GB, 15 W mode, clocks locked by `jetson_clocks` (GPU 612 MHz, CPU 1.4976 GHz) |
| Engine | llama.cpp TurboQuant fork `TheTom/llama-cpp-turboquant@bcb85fc`, `--jinja`, `-c 8192`, `-rea off`, temp 0, top-k 1, seed 42, no prompt-cache reuse |
| Models | Gemma 4 E2B and E4B, QAT `UD-Q4_K_XL` GGUFs |
| KV cache | `q8_0`, or `turbo3` (effective K = q8_0, V = turbo3) |
| JSON | the task's tools through the OpenAI `tools` parameter, one model call |
| Code Mode | the tools as a typed TypeScript API behind one `execute_typescript` tool, one script per task, run in Deno 2.9.8 with no permissions and echo stubs (D3a, D4) |
| Scoring | **pass**: every expected call matched (the paper's rule); **strict**: also no extra calls (BFCL's rule) ([`score.py`](../../toolcall/score.py)) |

Code Mode has two harness settings that send the model the same prompt (D12):
**strict** accepts only `tools.fn(...)` and no top-level `return`; **lenient** also accepts bare
`fn(...)` and wraps the script in an async function. Lenient is the setting from here on. Its
numbers come from re-running the strict runs' saved scripts ([`reexec.py`](../../toolcall/reexec.py)),
which equals a full rerun because decoding is deterministic: re-running them under the strict
harness reproduced 590 of 591 scripts, and the other one reads the current time.

## Accuracy

| Interface | KV | E2B pass | E2B strict | E4B pass | E4B strict |
| --- | --- | --- | --- | --- | --- |
| JSON | q8_0 | 75.7% | 75.1% | 73.8% | 73.1% |
| JSON | turbo3 | 74.4% | 74.1% | 73.4% | 72.8% |
| Code Mode, strict harness | q8_0 | 69.1% | 68.4% | 79.1% | 78.1% |
| **Code Mode, lenient harness** | q8_0 | **78.4%** | **77.4%** | **80.4%** | **79.4%** |

Paired comparisons on the same 301 tasks (pass rule; exact McNemar test, 95% CI on the difference):

| Comparison | Model | Difference | 95% CI | Only first passes / only second | p |
| --- | --- | --- | --- | --- | --- |
| Code (lenient) vs JSON | E2B | +2.7 points | −2.0 to +7.3 | 22 / 30 | 0.33 |
| Code (lenient) vs JSON | E4B | **+6.6 points** | +2.4 to +10.9 | 12 / 32 | **0.004** |
| Code (strict) vs JSON | E2B | −6.6 points | −12.0 to −1.3 | 44 / 24 | 0.021 |
| Code (strict) vs JSON | E4B | +5.3 points | +0.9 to +9.7 | 15 / 31 | 0.026 |
| turbo3 vs q8_0 (JSON) | E2B | −1.3 points | −3.4 to +0.7 | — | 0.34 |
| turbo3 vs q8_0 (JSON) | E4B | −0.3 points | −2.7 to +2.0 | — | 1.00 |

TurboQuant shows no significant loss, but T0 alone cannot establish non-inferiority at the
2-point margin (D5): both lower CI bounds fall below −2.

### By category (pass rate, JSON vs Code Mode lenient, q8_0)

| Category | n | E2B JSON | E2B Code | E4B JSON | E4B Code |
| --- | --- | --- | --- | --- | --- |
| simple_python | 40 | 92.5% | 95.0% | 87.5% | 95.0% |
| multiple | 20 | 85.0% | 95.0% | 95.0% | 90.0% |
| parallel | 40 | 80.0% | 85.0% | 82.5% | 87.5% |
| parallel_multiple | 40 | 90.0% | 85.0% | 87.5% | 87.5% |
| live_simple | 25 | 80.0% | 68.0% | 72.0% | 84.0% |
| live_multiple | 96 | 60.4% | 69.8% | 58.3% | 65.6% |
| live_parallel | 16 | 75.0% | 68.8% | 62.5% | 93.8% |
| live_parallel_multiple | 24 | 66.7% | 66.7% | 66.7% | 70.8% |

### Why tasks fail

* **JSON:** most often the model makes no tool call and asks a clarifying question instead
  (34 tasks for E2B, 41 for E4B), then wrong arguments.
* **Code Mode, lenient** (E2B / E4B): the script ran but made wrong calls 47 / 35, made no calls
  9 / 4, no script was written 2 / 9, syntax error 3 / 8, runtime error 4 / 3.
* **The strict harness** failed E2B on 26 bare function calls and 10 top-level `return`s;
  E4B made those mistakes 7 times.

## Time and energy

Board power is `VDD_IN` from tegrastats (the whole board's input, excluding PSU loss),
integrated over the run by [`energy.py`](../../toolcall/energy.py), the same method as
`main`'s `summarize_run.py`.

| Run | Time | Energy | Mean power | J per task | J per output token | Output tokens per Wh | Peak RAM | Peak temp |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E2B JSON q8_0 | 16.7 min | 2.92 Wh | 10.5 W | 35.0 | 0.62 | 5,838 | 2,557 MB | 62.4 °C |
| E2B JSON turbo3 | 17.5 min | 3.04 Wh | 10.4 W | 36.4 | 0.63 | 5,702 | 2,509 MB | 62.6 °C |
| E2B Code q8_0 | 43.2 min | 7.64 Wh | 10.6 W | 91.3 | 0.53 | 6,802 | 2,525 MB | 62.9 °C |
| E4B JSON q8_0 | 32.3 min | 5.99 Wh | 11.1 W | 71.6 | 1.23 | 2,936 | 3,910 MB | 63.8 °C |
| E4B JSON turbo3 | 33.3 min | 6.14 Wh | 11.1 W | 73.5 | 1.24 | 2,900 | 3,781 MB | 63.8 °C |
| E4B Code q8_0 | 54.5 min | 10.23 Wh | 11.3 W | 122.3 | 1.12 | 3,212 | 3,890 MB | 63.9 °C |

* **Code Mode costs 2.6× the energy per task on E2B and 1.7× on E4B.** Power barely changes;
  the runs are longer because the model writes a script: 132 vs 38 output tokens per task
  (median) for E2B, 68 vs 38 for E4B. The sandbox itself takes about 0.05 s and 30 MB per script.
* **The lenient harness does the same model work** as the strict one, so its time and energy are
  the strict run's, plus about 0.03 s of sandbox time per task.
* **TurboQuant** costs 3–5% more time and 2–4% more energy here, and lowers peak RAM by 48–129 MB
  at this 8K context.
* **No idle baseline for these runs.** They predate the 30 s idle windows that
  [`run_jetson.sh`](../../toolcall/run_jetson.sh) now records, so energy is the whole board's,
  not energy above idle. A 10-task smoke run with the new harness measured **4.95 W idle** with
  E2B loaded, and 10.4 W while working (`runs/t0-json-q8_0-off-e2b-smoke10-energy`).
  Runs from now on also store each task's own energy.

## Clock lock

The first JSON q8_0 runs had unlocked clocks; they were repeated after `jetson_clocks`
(`-r2` folders, used above). The repeat made identical calls on 301 of 301 tasks for both models,
so accuracy is unaffected. Time stayed within 1–2%; E4B's energy rose from 5.60 to 5.99 Wh (+7%)
and E2B's did not change (2.93 vs 2.92 Wh). Compare energy only between runs with the same
clock state.

## Reproduce

On the Jetson, from `~/research/toolcall` (one run at a time; the voice agent is stopped):

```bash
./run_jetson.sh e2b
```

```bash
KV=turbo3 ./run_jetson.sh e4b
```

```bash
IFACE=code-lenient ./run_jetson.sh e2b
```

Each run writes `runs/t0-<interface>-<kv>-off-<model>/` with the scores and `energy.json`.
To rebuild the lenient results from a strict Code Mode run without the model:

```bash
python3 reexec.py tasks/t0.jsonl runs/t0-code-q8_0-off-e2b runs/t0-code-lenient-q8_0-off-e2b
```
