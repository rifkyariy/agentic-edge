# Agentic edge benchmark

Cross-device, cross-architecture comparison harness for running the same
fixed suite of test cases against different (device, model, quantization,
architecture, MTP, thinking) combinations and getting back one comparable
JSON result file per run.

**Zero setup on a new device.** Stdlib only, no `pip install`. Clone the
repo, copy an example config, point it at that device's model/engine, run.

```bash
git clone <this repo>
cd benchmark
python3 run_benchmark.py examples/llama_cpp.json     # or litert_lm / little_gemma / proposed
python3 report.py                                     # comparison table across every result so far
```

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
| `litert_lm` | same adapter as llama.cpp — same HTTP shape | same as above | none |
| `little_gemma` | bare CLI (`lg "<prompt>"`), no server | not supported — always the floor case | none |
| `proposed` | this repo's own [`voice-agent`](../voice-agent/), full pipeline | **toggled live** via `POST /option` before the run starts (`configure_proposed()` in `adapters.py`) — no manual step | intent classification + `match_result`/`f1_result`/`currency_rate`/`weather_forecast`/`web_search` |

Config schema per engine is documented inline in `examples/*.json` — copy the
one matching your architecture and edit `device`, `model`, and the
engine-specific field (`endpoint`, `binary`, or `proposed_url`).

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

```bash
python3 run_benchmark.py examples/llama_cpp.json          # config's own "repeat"
python3 run_benchmark.py examples/llama_cpp.json --repeat 5
python3 run_benchmark.py examples/llama_cpp.json --cases my_cases.json
python3 run_benchmark.py examples/llama_cpp.json --out my_run.json
```

Each run writes one file to `results/<timestamp>-<tag>.json`: the config
used, host/Python version, best-effort GPU info (`nvidia-smi`, null when
absent), a summary, and every individual case result. Nothing is
overwritten — every run is its own file, so the same config re-run after a
code change produces a second data point rather than replacing the first.

## Comparing

```bash
python3 report.py                 # reads ./results
python3 report.py path/to/other   # reads any directory of result JSON files
```

One markdown table, one row per run, every axis from the table above as a
column plus avg total time, avg tokens/sec, tool-call accuracy, and answer
accuracy. Copy straight into a doc or PR description.

For (e) specifically: run `examples/llama_cpp.json` unmodified on the Pi,
then `examples/jetson_llama_cpp_cuda.json` (same model, same quant, only
`device` and `cuda` differ) on the Jetson, and diff those two rows.

## Honest limitations

- **Sequential, single-flight only.** One case runs to completion before the
  next starts; there is no concurrent-user simulation. That is a different,
  larger benchmark than this one.
- **`llama_cpp`/`litert_lm` do not control the server.** If `mtp`/`thinking`
  in the config do not match how that server was actually started, the
  result is silently mislabeled — check the server's own startup flags, not
  just this config, before trusting those two columns.
- **Tool-call detection for `llama_cpp`/`litert_lm`** reads
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
