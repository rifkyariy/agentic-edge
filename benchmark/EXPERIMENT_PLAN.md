# Experiment plan — Agentic Edge, paper 1

The protocol: what runs, on what, in what order, and what each table is meant
to prove. Written to be followed next to the hardware, and revised as results
came in — §7 records what changed and why, because several original
expectations turned out to be wrong.

**Scope of paper 1: text and reasoning parameters only.** Voice into Gemma's
multimodal path is paper 2; no audio result belongs in this one.

---

## 1. What is being compared

**Models (fixed).** Gemma 4 **E2B** and **E4B**, Unsloth Q4_K_XL QAT GGUFs.
No other model family.

**Devices.** Two sizes of small, chosen so the device itself is the variable:

| device | why it is in the study |
|---|---|
| **Raspberry Pi 5**, 8GB, 4× Cortex-A76 | the floor: CPU and RAM only, no GPU. The point is to give the smallest board a fair run. |
| **Nvidia Jetson Orin Nano** | the same workload with **CUDA**. Record the `nvpmodel` power mode: a 15W run and a 25W run are not the same experiment. |

**Architectures.** Two standard native runtimes as baselines, plus the
architecture this project proposes:

| cond | architecture | tools |
|---|---|---|
| A | **little-gemma** (github.com/cortexist/little-gemma) | none |
| B | **llama.cpp** bare | none |
| D | llama.cpp + **naive function calling** (`tool_choice: auto`) | yes, model decides alone |
| E | **proposed orchestrator**: classify → pin one schema → execute the tool itself if the model does not | yes, inherent |

Condition C (LiteRT-LM) was dropped on 2026-09-20; its runs stay in `results/`
unreported and its runtime is no longer installed.

**Inference-time methods**, switchable conditions rather than fixed settings:
**MTP** (speculative decoding), **thinking/reasoning** on or off, and
**concise prompt parameters**.

---

## 2. Capability areas

The paper claims three. They are reported separately, never as one score.

| area | benchmark | status |
|---|---|---|
| **a. General knowledge and reasoning** | **MMLU-Pro** (headline), GSM8K (appendix) | Pi done, Jetson pending |
| **b. Instruction following + tool calling** | own 10-case suite; IFEval and BFCL installed but not run | partial |
| **c. Safety and security** | not chosen yet — candidates: XSTest, SimpleSafetyTests; AgentDojo for tool-injection | not started |

---

## 3. Statistical design

**The uncertainty that matters is which questions were drawn, not run-to-run
noise.** Decoding is greedy, so there is no sampling seed to vary; repeating an
identical question set measures only implementation nondeterminism (~1 point
here, from llama.cpp not being bit-identical across server restarts).

| source | size | addressed by |
|---|---|---|
| question sampling, n=100 | **±9.7 pts** (95%) | three disjoint subsets, pooled to n=300 → **±5.6** |
| system nondeterminism | ~1 pt | one subset run twice |
| decoding seed | none at temperature 0 | n/a unless sampling is enabled |

**Subsets.** `mmlupro_subset.py --seed S --tag sN --exclude ...` draws a
stratified sample proportional over all 14 MMLU-Pro subjects (largest
remainder, minimum one per subject) and refuses to reuse questions from an
excluded subset. s1/s2/s3 use seeds 20260918/19/20 and are disjoint, so they
pool cleanly. Question ids are committed in `findings/stdbench/`.

**Reporting rules**, fixed before the runs:
1. Every run performed is reported, including failed and superseded ones.
2. Per-subset scores are shown individually as well as pooled.
3. Latency is warm median with cold stated separately, never a mean across
   repeats — turn 1 is ~1.7-2.2× slower from system-prompt prefill caching.
4. Every `n/a` cell carries a one-line reason.
5. A metric change means rescoring **every** run with it, not mixing rules.

Basis: Miller 2024 ([arXiv:2411.00640](https://arxiv.org/abs/2411.00640)) for
treating questions as a sample and reporting standard errors; Madaan et al.
2024 ([arXiv:2406.10229](https://arxiv.org/abs/2406.10229)) for quantifying
benchmark variance before calling a difference meaningful; Dodge et al. 2019
([arXiv:1909.03004](https://arxiv.org/abs/1909.03004)) for reporting all runs
rather than the best; Biderman et al. 2024
([arXiv:2405.14782](https://arxiv.org/abs/2405.14782)) for publishing exact
configurations and per-question outputs.

---

## 4. Measurement protocol

### 4.1 Accuracy — `std_mmlupro.sh`

lm-evaluation-harness `mmlu_pro`, unmodified: 5-shot chain of thought, greedy,
`max_gen_toks` 2048, extraction `answer is (X)`. Only the question set is
restricted, via `--samples`.

Three serving settings, all load-bearing, and the first two restored afterwards:

- **`-c 8192`** — the longest subset prompt is 2,427 tokens against a
  2,048-token answer budget, so the deployed 4,096 context would truncate.
- **`--cache-ram 0`** — llama.cpp's default host prompt cache is 8192 MiB,
  more than the Pi has. With 100 distinct prompts it fills and the server is
  OOM-killed; this happened at question 48 of the first E4B GSM8K attempt.
- **`-rea off --reasoning-budget -1`** — `-rea` is `--reasoning-format`, not a
  reasoning toggle. Gemma reasons either way; the flag decides only whether
  that text returns inline in `content` or split into `reasoning_content`.
  lm-eval reads `content` alone. The Jetson served without it until
  2026-09-22, which halved its median response (993 characters against the
  Pi's 1,880), returned 11 of 100 answers completely empty, and left 23 of 100
  with no extractable letter against the Pi's 6. Those runs are archived under
  `stdbench/failed/`. **This is the baseline, thinking-off row** — the
  reasoning-on condition is `THINKING=on` with budget 320, which is a
  different experiment.

  Correcting it moved accuracy by one point (48.0% -> 47.0% on E2B s2) and
  left every rate metric within 1% — decode tok/s 22.88 -> 23.00, J/token 0.46
  -> 0.46, mean watts unchanged. Per-run totals fell ~36% (116,679 -> 74,149
  generated tokens), since the empty responses were driving lm-eval retries.
  So the bug invalidates accuracy and per-run totals, not the rates.

### 4.2 Efficiency — `run_measured.sh`

Every accuracy run is wrapped so the device cost is measured at the same time:

- `telemetry.py` samples at 1 Hz: per-core CPU and MHz, SoC temperature,
  throttle flags, memory, swap, disk I/O, the server's RSS and CPU, and board
  power from the PMIC's per-rail V×I.
- `parse_llama_log.py` extracts per-request prompt and generation tokens and
  timings from llama-server's journal, timestamped so each telemetry sample is
  attributable to prefill, decode or idle.
- An idle baseline is recorded before and after the workload, so energy can be
  reported above idle as well as raw.
- `summarize_run.py` writes J per generated token, tok/s/W, idle vs working
  watts, peak temperature and throttle counts.

**Power caveat to state in the paper:** PMIC rails give the board's DC draw and
exclude PSU conversion loss. It is consistent between runs, which is what the
Pi-vs-Jetson efficiency comparison needs, but it is not wall power.

### 4.3 Own suite — `pi5_run.sh`

Tiers 1-3 for the architecture comparison, MTP × thinking, and the quant sweep.
Condition E runs single-turn (`VA_HISTORY_TURNS=0`) like B and D, since with
history on, repeat *n* can copy repeat *n-1*'s answer instead of calling a tool.

---

## 5. Run order

Per device, accuracy and telemetry together:

1. MMLU-Pro s1, E2B and E4B
2. MMLU-Pro s2 and s3, E2B and E4B → pooled n=300
3. Own suite tiers 1-2 (architectures, MTP × thinking)
4. Thinking-on rows, if the budget allows (3-8× latency)

Pi first to completion, then Jetson with the identical subsets and scripts. A
Pi-only study still supports the capability-(a) results; the Jetson adds the
CUDA axis, of which the sharpest cell is little-gemma, whose design premise is
CUDA and which the Pi never gave a GPU to justify itself on.

---

## 6. What each table proves

| table | grouping | supports |
|---|---|---|
| **T1** architecture comparison | condition × device × model | what the orchestration layer buys, and where it does not |
| **T2** MTP × thinking | device × model × toggle | which inference-time methods pay, and whether CUDA changes the answer |
| **T3** quantization sweep | quant | robustness of the headline |
| **T4** classifier behaviour | category, condition E | the intent classifier works, and how often it over-triggers |
| **T5** standard benchmarks | model × subset × device | MMLU-Pro against the vendor's published figures |
| **T6** efficiency | device × model | J/token, tok/s/W, idle vs working power |

---

## 7. Revisions forced by results

Recorded because they contradict the plan as first written, and because a
reader is entitled to know which findings were expected and which were not.

1. **"Bare engines will fabricate ~100% of the time" was wrong.** Across all 62
   distinct live-data answers, no bare engine invented a fact; every one
   declined or asked for context. The metric was reframed to SimpleQA-style
   correct / incorrect / not-attempted grading, hand-audited.
2. **Naive function calling already selects tools perfectly** on single-turn
   prompts (24/24, both models), so the orchestrator cannot claim better
   selection. What D never does is *answer*: it emits a call and stops. The
   defensible claim is end-to-end grounded answering.
3. **MTP is faster on this CPU**, 1.25-2.15× with byte-identical output,
   contradicting the project's earlier note that speculative decoding loses on
   Pi-class CPUs. That finding came from other engines' implementations, not
   llama.cpp's `draft-mtp`. Because output is identical, MTP needs no accuracy
   re-runs; it is a latency and energy result.
4. **Benchmark defaults understate these models.** lm-eval's default 256-token
   generation cap truncated 24% of E2B's GSM8K answers mid-solution; raising it
   to 1,024 (Meta's setting for GSM8K) moved the score 65.3% → 80.2%.
5. **The orchestrator over-triggers**, sending 15.7% of static questions into a
   pointless lookup.
6. **Conditions dropped:** LiteRT-LM entirely; IFEval and BFCL deferred, which
   leaves capability (b) without a standard benchmark — a known gap, not an
   oversight.

---

## 8. Risks

| risk | mitigation |
|---|---|
| External API rate limits polluting latency (tool cases) | report model time with tool I/O subtracted; space runs |
| Thermal throttling over multi-hour runs | telemetry records temperature and throttle flags per second; a throttled run is not comparable |
| Memory exhaustion on 8GB | `--cache-ram 0`, and RSS is sampled throughout |
| Jetson setup is a day of work and may slip | sequence Pi-complete first so a partial study is still publishable |
| Small n per subject in MMLU-Pro (3-11) | report subject rows as indicative only; the pooled figure is the claim |
