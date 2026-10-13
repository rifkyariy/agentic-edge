# Protocol — as it was run

How every measurement in this repository was taken, and the corrections that
results forced along the way. The manuscript (*Never Compute Twice:
Exact-Output Speedups for Gemma 4 on Edge Devices*) uses the MMLU-Pro part of
this protocol; its Table II is §2 and §3 below. The step-by-step commands are
in the [README](../README.md#reproducing-the-paper). Which experiments ran is
in [`experiments.md`](experiments.md).

---

## 1. What is compared

**Models (fixed).** Gemma 4 **E2B** and **E4B**, the Unsloth QAT
`UD-Q4_K_XL` GGUFs, the same file on every board and engine:

| file | bytes | sha256 |
|---|---|---|
| `gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf` | 2,620,370,976 | `e531007218dfab990486a5de7676a6932d6ea8dea233d1f698d7c21cf8a16889` |
| `gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf` | 4,215,695,776 | `df0fd4ee07072c607c29a0a1cb4f98918426cca12f45a2776bdd6ee6d09a4de3` |

The iPhone runs MLX 4-bit builds of the same QAT checkpoints instead
(`gemma-4-E2B-it-qat-4bit`, `mlx-community/unsloth-gemma-4-E4B-it-qat-oQ4`):
same prompts and questions, different quantisation and kernels.

**Devices.**

| device | role | software |
|---|---|---|
| **Jetson Orin Nano 8 GB**, 15 W mode (`nvpmodel` 0) | the engine comparison — every row of Tables I and III–VI | JetPack R39.2.1, CUDA 13.2, kernel 6.8.12-tegra, Python 3.12.3 |
| **Raspberry Pi 5**, 8 GB, 4× Cortex-A76, no GPU | deployment context (Table VIII); the own suite | Debian 13, llama.cpp CPU, NEON |
| **iPhone 15 Pro**, A17 Pro, 8 GB, iOS 26.6 | deployment context (Table VIII) | MLX via the GemmaBench app |

**Engines.**

| engine | build | how it serves |
|---|---|---|
| **llama.cpp** | Jetson `a894dae` (CUDA, `-ngl 99`, sm_87); Pi `661643e` (CPU) | `llama-server`, OpenAI-compatible HTTP |
| **little-gemma** | `cortexist/little-gemma` @ `aee759d` + `agentic-edge.patch`, target `run-cuda-i8` | no HTTP: `lg_openai_shim.py` renders Gemma 4's chat template (byte-identical to llama-server's, `tests/test_lg_shim.py`) and drives the engine over its socket |
| **CoPR** (S9 in the logs) | the same pin + `agentic-edge.patch` + `ae.patch`, its own tree | as little-gemma, with `-reuse -ngram -block 3` |

`agentic-edge.patch` changes no kernel, sampling or tokenizer code: it adds
`-raw` prompts, tokenises the whole prompt in one piece, and raises the answer
budget (`SERVE_GEN`) from 1,024 to 2,048. `ae.patch` adds three switches, all
off by default: `-ngram` (prompt-lookup drafts through the existing batched
verify), `-reuse` (shared-prefix KV snapshots, exact for the sliding-window
rings) and `-block N` (verify width). Gemma's MTP draft head is not used by
any run, baseline or CoPR.

---

## 2. Task

lm-evaluation-harness **0.4.13**, task `mmlu_pro`, unmodified: 5-shot chain of
thought, greedy, extraction of the first `answer is (X)`. Only the question
set is restricted (`--samples`).

| setting | value | why |
|---|---|---|
| answer cap | `max_gen_toks` 2,048 | lm-eval's default 256 truncates chain of thought mid-solution (it understated E2B on GSM8K by ~15 points) |
| context | `-c 8192` | the longest subset prompt is 2,427 tokens; with a 2,048 answer budget the deployed 4,096 truncates |
| host prompt cache | `--cache-ram 0` | llama.cpp's default 8,192 MiB is more than either board has; 100 distinct prompts get the server OOM-killed |
| thinking | `-rea off --reasoning-budget -1` | `-rea` is `--reasoning`, **the thinking switch itself**; `off` is a genuine no-chain-of-thought-channel condition. `--reasoning-format` is a different flag that only decides where thoughts go |

For little-gemma and CoPR the same settings map onto the shim and engine:
`-rea off` → shim `--thinking off` (no `<|think|>` turn), budget `-1` →
engine `-think -1`, context and answer cap compiled in (`SERVE_SEQ` 8,192,
`SERVE_GEN` 2,048). Prompt token counts match llama.cpp's exactly (1,097 =
1,097 on the first prompt, verified 2026-09-25).

---

## 3. Statistical design

**The uncertainty that matters is which questions were drawn.** Decoding is
greedy, so repeating a question set measures only implementation
nondeterminism.

| source | size | addressed by |
|---|---|---|
| question sampling, n=100 | ±9.7 points (95%) | three disjoint subsets pooled to n=300 → **±5.6** |
| system nondeterminism | ~1 point | repeat runs (CoPR E2B s1 repeated three days later: 100/100 identical) |
| decoding seed | none at greedy | — |

**Subsets.** `mmlupro_subset.py --seed S --tag sN --exclude …` draws a sample
stratified over all 14 subjects (largest remainder, at least one per subject)
and refuses to reuse an excluded subset's questions. `s1`/`s2`/`s3` use seeds
20260918/19/20 and are disjoint. Their ids are committed in
`findings/stdbench/mmlupro_subset100_s{1,2,3}_ids.json`.

**Quality standard for CoPR: byte identity.** Every CoPR reply is compared
with little-gemma's reply to the same question (`ae_gate.py --diff`). That test
is meaningful because two engines on the same weights rarely agree: llama.cpp
and little-gemma return identical text on 12 of 100 s1 questions.

**Paired accuracy tests** use the exact two-sided McNemar test over the same
question ids.

**Reporting rules**, fixed before the runs:

1. Every run is reported, including failed and superseded ones.
2. Per-subset scores are shown as well as pooled ones.
3. Rates are pooled ratios (Σ tokens / Σ time), never a mean of per-run rates.
4. Every `n/a` carries a written reason.
5. A metric change means rescoring every run with it.

Basis: Miller 2024 ([arXiv:2411.00640](https://arxiv.org/abs/2411.00640)),
Madaan et al. 2024 ([arXiv:2406.10229](https://arxiv.org/abs/2406.10229)),
Dodge et al. 2019 ([arXiv:1909.03004](https://arxiv.org/abs/1909.03004)),
Biderman et al. 2024 ([arXiv:2405.14782](https://arxiv.org/abs/2405.14782)).

---

## 4. Measurement

Every accuracy run is wrapped by `run_measured.sh`, so device cost comes from
the same run:

- `telemetry.py` samples at 1 Hz: per-core CPU load and frequency, GPU load and
  frequency, temperature, throttle flags, memory, swap, disk I/O, the server
  process's RSS and CPU, and **board DC power** — INA3221 `VDD_IN` on the
  Jetson, the PMIC's per-rail V×I on the Pi. It excludes power-supply loss and
  is not wall power.
- A 30 s idle baseline is recorded before and after, so energy is reported
  total and above idle.
- `parse_llama_log.py` extracts per-request prompt and generated tokens and
  timings (llama-server's log, or the shim's for little-gemma and CoPR).
- `summarize_run.py` writes `summary.json`: energy as the trapezoidal integral
  over the working window, J per generated token, decode and prefill rates,
  thermals, utilisation.

The working window includes model load and the gaps between requests.
Integrating over the request windows alone changes J/token by only 1–2% for
every engine (`paper_tables.py` recomputes both).

**Serving-flag fingerprint.** A queued run captures the server's real command
line once it is serving and diffs it against `baselines.json`
(`<results root>/queue/jobs/<id>/fingerprint.json`). A mismatch fails the run.
`meta.json`'s `server_args` is sampled before the run's own server starts and
must not be trusted; `server_args_after` is the honest field (AGENTS.md §4.10).

**Clock caps.** The queue refuses to start a Jetson run unless the kernel
enforces the caps the active `nvpmodel` mode declares (GPU 612 MHz, CPU
1,497.6 MHz in 15 W mode). Added after the 2026-10-04 boot, when
`nvpmodel.service` failed silently: `nvpmodel -q` still said 15 W while the GPU
ran at 1,020 MHz, and plain decode came out ~1.6× faster.

---

## 5. The own suite (not in the manuscript)

`run_benchmark.py` / `pi5_run.sh` run a fixed 10-case suite against five
architectures on the Pi (A little-gemma, B llama.cpp, C LiteRT-LM, D llama.cpp
with naive tool calling, E the voice agent's orchestrator), plus MTP × thinking
and an E4B quantisation sweep. Condition E runs single-turn
(`VA_HISTORY_TURNS=0`). Results: RESULTS §2–§4.

---

## 6. Corrections forced by results

Recorded because each contradicted the plan as first written.

1. **Bare engines did not fabricate.** Across 62 live-data answers, none
   invented a fact; the metric became SimpleQA-style correct / incorrect /
   not attempted.
2. **Naive function calling already selected tools perfectly** (24/24) on
   single-turn prompts; what it never did was answer.
3. **MTP was faster on the Pi's CPU**, 1.25–2.15× with byte-identical output.
4. **Benchmark defaults understated the models**: the 256-token cap truncated
   24% of E2B's GSM8K answers; at 1,024 the score moved 65.3% → 80.2%.
5. **The orchestrator over-triggered** on 15.7% of static questions.
6. **The Jetson served without `-rea`** until 2026-09-22. It fell back to
   `auto`, Gemma's template turned thinking on, and the thoughts landed in
   `reasoning_content`, which lm-eval never reads: median reply 993 characters
   against the Pi's 1,880, 11 of 100 empty. Those runs are archived as failed
   and every Jetson run was redone (RESULTS §7.1).
7. **A silent power-mode failure** (2026-10-04) — see the clock caps above.
8. **The first six `-reuse` runs died at startup**: the run script passed
   `-reuse` as its own argument and the shim's parser read it as an option.
   Archived in `findings/runs/jetson/failed/`, rerun after the fix.
9. **The Jetson's clocks were pinned** from 2026-10-07 19:30 (`jetson_clocks`
   signature, RESULTS §7.7): +5–9% energy, speed within ±3%. Compare time, not
   energy, across that date.
10. **LiteRT-LM (condition C) was dropped** on 2026-09-20; its runs stay in
    `benchmark/results/`.
