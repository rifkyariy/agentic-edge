# Agentic edge benchmark

Harness for the Agentic Edge study: the same fixed workload across
(device, model, quantization, architecture, MTP, thinking), with **accuracy and
device cost measured in the same run**, producing one comparable JSON result
file each time.

Two halves:

| half | scripts | what it produces |
|---|---|---|
| **own suite** — architectures, tool calling, MTP, quant | `run_benchmark.py`, `pi5_run.sh`, `report.py` | `results/*.json`, tables T1-T4 |
| **standard benchmarks + telemetry** | `std_mmlupro.sh`, `run_measured.sh`, `telemetry.py` | `~/Research/stdbench/`, `~/Research/measured/` |

The protocol, the statistical design, and the revisions that results forced are
in [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md). Measured results are in
[../findings/RESULTS.md](../findings/RESULTS.md).

**Zero setup on a new device.** Stdlib only, no `pip install`. Clone the
repo, copy an example config, point it at that device's model/engine, run.

```bash
git clone <this repo> && cd benchmark
$EDITOR devices/pi5.json          # once per box: paths, endpoints, cuda, models
./sweep.sh tier1 devices/pi5.json  # 10 runs: 5 architectures x 2 models
python3 report.py t1               # the headline table
```

Config is **two layers**, so nothing is ever duplicated:

| layer | holds | written |
|---|---|---|
| `devices/<box>.json` | model paths, endpoints, binaries, `cuda`, power mode | **once per device** |
| `conditions/<X>.json` | engine, `offer_tools`, `mtp`, `thinking` | once, shared by every device |

A run is one of each plus a model key:

```bash
python3 run_benchmark.py --device devices/pi5.json \
                        --condition conditions/E.json --model e4b
```

New device = one new file. New condition = one new file, applies everywhere.
Moving the study to another box is `git pull` plus a device file — no code
edits, no per-run config duplication.

**The protocol** — what to build first, what to run in what order on which
device, and what each table proves — is in
[EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md).

## What this answers

| # | question | how |
|---|---|---|
| a | Pi 5 vs Jetson Orin Nano | `config["device"]` is a free label; run the same config (same model, quant, engine) on each, diff the rows |
| b | Gemma 4 E4B vs E2B | `config["model"]["name"]` |
| c | quantization levels | `config["model"]["quant"]` — a label; point `path`/`endpoint` at that build |
| d | llama.cpp / LiteRT-LM / little-gemma / our proposed architecture | `config["engine"]` — one adapter per architecture, see below |
| e | how much CUDA matters | `config["cuda"]`; `report.py` also records `nvidia-smi` GPU name/utilization when present, absent entirely on the Pi |
| f | MTP / tool calling / thinking trade-offs | `config["mtp"]`, `config["thinking"]`; tool-calling is inherent to `proposed` and absent from the other three, so it is measured by comparing `proposed` against them on the same tool-requiring cases, not by a separate flag |

## The four engines

| engine | what it is | mtp / thinking | tool calling |
|---|---|---|---|
| `llama_cpp` | any llama.cpp-compatible `/v1/chat/completions` server | **server-launch flags** (`--spec-type draft-mtp`, `-rea on`) — `cfg["mtp"]`/`cfg["thinking"]` are labels for the report; start the server to match before running | none (bare model) |
| `little_gemma` | bare CLI (`lg "<prompt>"`), no server | not supported — always the floor case | none |
| `proposed` | this repo's own [`voice-agent`](../voice-agent/), full pipeline | **toggled live** via `POST /option` before the run starts (`configure_proposed()` in `adapters.py`) — no manual step | intent classification + `match_result`/`f1_result`/`currency_rate`/`weather_forecast`/`web_search` |

## Conditions

| cond | architecture | tools offered | orchestration |
|---|---|---|---|
| `A` | little-gemma | none | none — the floor. Auto-labelled `A-cpu` / `A-cuda` by the device's `cuda` flag, because little-gemma is C/CUDA by design and a GPU row is not the same condition as a CPU one. |
| `B` | llama.cpp | none | none |
| `D` | llama.cpp | **yes**, `tool_choice: auto` | none — the model decides alone |
| `E` | **proposed** | yes | classify → pin → orchestrator-side fallback execution |
| `B-mtp`, `E-think`, … | as above | | with MTP and/or thinking on (Tier 2) |

**D vs E was the original claim** — see EXPERIMENT_PLAN §7.2 for how results revised it.

**Condition C (LiteRT-LM) was dropped** on 2026-09-20 and its runtime removed from the Pi. Its runs remain in `results/` unreported.

**D vs E, as first framed.** A/B/C have no tool access at all, so beating them
proves only that a system with internet access beats one without. D is the
same engine with the same schemas offered naively — the thing the
orchestration layer has to actually improve on.

Unsupported combinations skip themselves and **record why**
(`little_gemma` + `mtp` → "no speculative-decoding flag"), so an `n/a` cell
in the report has a reason attached instead of being a mysteriously missing
row. LiteRT-LM's MTP support is marked *unverified* rather than
false — confirm on the box before claiming a number either way.

## Test cases (`cases.json`)

Ten cases across `knowledge`, `thinking` (a deterministic arithmetic problem
— see `gemma4-pi5-benchmarks.md` for why this one specifically separates
thinking on/off), `creative`, and five tool-requiring categories
(`weather`, `currency`, `match_result`, `fixture`, `race_result`, `news`).
Two kinds of automatic scoring, both optional per case:

- `expected_substring` — case-insensitive substring check against the
  answer text (`"correct": true/false` in the result)
- `expected_tool` — did the run call this exact tool
  (`"tool_correct": true/false`)

Add a case by appending an object to `cases.json` — no code changes needed.
A case with neither field just records latency/tokens with no pass/fail
(use this for cases you plan to score by hand — read `result["text"]` back
out of the result JSON and annotate separately, since automatic scoring for
open-ended answers is out of scope here).

## Running

### Standard benchmarks with device telemetry

```bash
# once: build the question subsets (disjoint, seeded, committed)
python3 mmlupro_subset.py --seed 20260918 --tag s1
python3 mmlupro_subset.py --seed 20260919 --tag s2 --exclude s1

# one accuracy run, wrapped in 1Hz power/thermal/utilisation telemetry
./run_measured.sh mmlupro-e2b-s1 -- env SUBSET=s1 ./std_mmlupro.sh e2b
```

Each measured run writes `telemetry.csv` (per-core CPU and MHz, temperature,
throttle flags, memory, disk, server RSS, per-rail and total board power),
`requests.csv` (per-request tokens and timings from llama-server's journal),
`meta.json` and `summary.json` (J per generated token, tok/s/W, idle vs working
watts, peak temperature). Rebuild the results page with
`python3 build_viz.py`.

Two settings the Pi needs, applied by `std_mmlupro.sh` and restored after:
`-c 8192` (longest subset prompt is 2,427 tokens against a 2,048-token answer
budget) and `--cache-ram 0` (llama.cpp's 8192 MiB default host prompt cache
exceeds the board's RAM and gets OOM-killed on 100 distinct prompts).

### Own suite

```bash
./sweep.sh tier1 devices/pi5.json     # 5 conditions x 2 models, full case suite
./sweep.sh tier2 devices/jetson.json  # MTP x thinking, conditions B and E only
./sweep.sh tier3 devices/pi5.json     # quant sweep
./sweep.sh all   devices/pi5.json
COOLDOWN=60 ./sweep.sh tier1 devices/pi5.json   # longer gap between runs
```

Tiers 2 and 3 use reduced case files (`cases_t2.json`, `cases_t3.json`) —
that is most of the wall-clock saving, and neither tier needs all five tool
categories to make its point. `sweep.sh` continues past a failed run rather
than aborting the tier, since the gap is visible in the report anyway.

Each run writes one file to `results/<timestamp>-<tag>.json`: the config
used, host/Python version, best-effort GPU info (`nvidia-smi`, null when
absent), a summary, and every individual case result. Nothing is
overwritten — every run is its own file, so the same config re-run after a
code change produces a second data point rather than replacing the first.

## Comparing

```bash
python3 report.py          # all four tables
python3 report.py t1       # architecture comparison — the headline
python3 report.py t2       # MTP x thinking x CUDA
python3 report.py t3       # quant sweep
python3 report.py t4       # per-category classifier behaviour
python3 report.py t1 --results path/to/other
```

Three objective metrics, no live ground truth required:

- **tool selection** — did it call the right tool
- **fabrication** — answered a live-data question with a substantive claim
  and *no* tool call. Bare engines should be ~100%, `proposed` ~0%. This is
  the metric that carries the reliability argument without needing to know
  what the weather actually was at run time. Refusals and hedges do not
  count as fabrication: declining is correct behaviour for a model that
  cannot look anything up.
- **static answers** — the fixed-ground-truth cases (Jakarta, the arithmetic
  29), which is where thinking mode's value shows up

Latency is **warm median with cold reported separately**, never a mean across
repeats: turn 1 is ~1.7–2.2× slower than turn 2 from system-prompt prefill
caching (measured again during development: 80.5s cold vs 47.6s warm), so a
mean over `repeat: 4` describes neither state. For `proposed`, `model time`
excludes tool network I/O (Sofascore/Open-Meteo round trips), which is not
the architecture's cost and varies with the internet.

For (e) specifically: the same `conditions/B.json` and `--model e4b` on both
`devices/pi5.json` and `devices/jetson.json` — identical condition, identical
model and quant, only the device file differs. Then diff those two rows in
`report.py t2`. The `A-cpu` vs `A-cuda` pair is the sharper version of the
same comparison, since little-gemma is the one engine designed around CUDA.

## Honest limitations

- **Sequential, single-flight only.** One case runs to completion before the
  next starts; there is no concurrent-user simulation. That is a different,
  larger benchmark than this one.
- **The harness does not own the server's launch flags.** `run_benchmark.py`
  verifies the loaded model through `/props` and switches it when needed, and
  MTP/thinking are pushed through va-web's `/option`, but a server started by
  hand with different flags would still be mislabeled. Check `ps` before
  trusting those columns.
- **Tool-call detection for `llama_cpp`** reads
  `delta.tool_calls` from the stream, which requires you to have actually
  offered tool schemas in that server's request — this harness sends a bare
  `messages` array with no `tools` field, so those two engines will show
  `tool_correct: false` on every tool-requiring case by construction. That
  is the point: it is the "no agentic layer at all" baseline the `proposed`
  architecture is being compared against.
- **`expected_substring` is a crude correctness proxy.** It catches an
  obviously wrong number or a missing key fact, not answer quality. Treat
  cases without it (`creative-poem`, `knowledge-socket`) as latency-only and
  score their text by hand if quality matters for your writeup.


## Scripts

| script | what it does |
|---|---|
| `run_benchmark.py` | one run of the own suite: device + condition + model key |
| `pi5_run.sh` | tiers 1-3 on the Pi, with the server juggling each condition needs |
| `report.py` | tables T1-T4 from `results/` |
| `mmlupro_subset.py` | draws a stratified, seeded, disjoint MMLU-Pro subset |
| `std_mmlupro.sh` | one MMLU-Pro run (`SUBSET=`, `THINKING=`) via lm-eval |
| `std_run.sh` | tinyGSM8k now; IFEval and BFCL deferred |
| `run_measured.sh` | wraps any of the above with idle baselines and telemetry |
| `telemetry.py` | 1 Hz device sampler, stdlib only |
| `parse_llama_log.py` | per-request token timings from llama-server's journal |
| `summarize_run.py` | energy, J/token, tok/s/W, thermals for one measured run |
| `build_viz.py` | builds `findings/viz/mmlupro_run.html` from results + telemetry |
