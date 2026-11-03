# Beyond MMLU-Pro: CoPR on agent-shaped prompts (2026-10-08)

Gemma 4 E2B, Jetson Orin Nano at 15 W (clocks locked, RESULTS §7.7; all four
Jetson runs share that state). Prompts: `agent_prompts.py`.

- `prompts_bfcl.jsonl`: BFCL v4 `simple_python` + `multiple`, first 100 of
  each, BFCL's own prompt-mode system prompt; `reference` = the first
  acceptable ground-truth value in `[func(arg=value)]` form.
- `prompts_ifeval.jsonl`: google/IFEval, first 100 prompts, as lm-eval sends
  them (one user turn, max 1,280 tokens).

Runs (`bench_prompts.py`, queue kind `raw`): `agentic-llama-e2b-bfcl`
(20:20–20:28), `agentic-llama-e2b-ifeval` (20:28–20:56), `agentic-lg-e2b-bfcl`
(20:56–21:01), `agentic-ae-e2b-bfcl` (21:01–21:06, `-reuse -ngram -block 3`).
Each directory keeps the replies (lm-eval sample format) and per-request
timings. Replays (`replay_dirs.py`, on the Pi): `replay/`.

## Acceptance (replayed, width 3)

| replies | tokens / decode step | lookup match | accepted / drafted step |
|---|---|---|---|
| MMLU-Pro CoT, E2B (paper, Table VII) | 1.41 | 47% | 0.87 |
| BFCL reference answers (A) | 1.22 | 31% | 0.72 |
| BFCL, Gemma's own replies (B) | 1.24 | 32% | 0.75 |
| IFEval, Gemma's own replies (D) | 1.10 | 16% | 0.60 |

## BFCL, measured (C)

| | llama.cpp | little-gemma | CoPR |
|---|---|---|---|
| replies identical to little-gemma | 189 / 200 | ref. | **200 / 200** |
| prompt / reply tokens per request | 468 + 131 cached / 24 | 599 / 24 | 599 / 24 |
| prefill share of model time | 46% | 30% | 33% |
| decode tok/s | 25.8 | 28.8 | **32.3** (+12%) |
| wall per request | 1.74 s | 1.20 s | **1.13 s** (−6%) |
| lookup accepted / drafted step (live) | – | – | 0.749 (replay 0.748) |
| prefix restores | (llama.cpp reuses the ~131-token header) | – | **0** |

CoPR's `-reuse` never restored on BFCL: it snapshots up to the start of a
prompt's final user turn, and in BFCL that span already holds the question's own
function schemas, so consecutive prompts never share it. llama.cpp's slot cache
reuses the longest common prefix, the ~131-token BFCL header.
