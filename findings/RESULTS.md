# Results so far — Pi 5, Gemma 4 E2B/E4B

Everything measured on `MITLAB-EDGE` (Raspberry Pi 5, 8GB, 4× Cortex-A76, no GPU,
governor `ondemand`, active cooler, no thermal throttling observed:
`throttled=0x0` throughout). Models are Unsloth Q4_K_XL **QAT** GGUFs unless a
row says otherwise. Raw run files: `benchmark/results/` (own suite) and
`findings/stdbench/` (lm-eval).

Paper 1 scope is **text + reasoning parameters only** — no voice, no multimodal.

---

## 1. Standard benchmarks (lm-evaluation-harness)

### MMLU-Pro — 100-question stratified subset

| Model | Pi 5, Q4_K_XL | Google's published figure | Δ | Runtime |
|---|---|---|---|---|
| E2B | **56.0% ± 5.0** | 60.0% | −4.0 | 169 min |
| E4B | **64.0% ± 5.0** | 69.4% | −5.4 | 359 min |

Protocol: lm-eval `mmlu_pro`, 5-shot CoT, greedy, `max_gen_toks` 2048, extraction
`answer is (X)`. Subset: proportional stratification over all 14 subjects, seed
20260918, question ids in `findings/stdbench/mmlupro_subset100_ids.json`.
Server: llama.cpp, `-c 8192` (the longest prompt is 2362 tokens, so the
deployed 4096 would truncate), `--cache-ram 0`, and
**`-rea off --reasoning-budget -1`** — the baseline, thinking-off serving
config. `-rea` is `--reasoning-format`, not a reasoning switch: without it
llama.cpp splits Gemma's thinking into `reasoning_content`, which lm-eval never
reads. Both boards must carry it; see §8.1.

**This is a consistency check, not a controlled comparison.** The Gemma 4 model
card states neither precision, shot count nor thinking mode, so the Δ column
mixes four differences (4-bit QAT vs unstated precision; 100 questions vs
12 032; our protocol vs theirs; thinking off vs unstated). A real quantization
measurement needs the same harness at a higher precision — Q8_0 is on the box
for exactly that.

Format losses, counted separately because they are not reasoning failures:

| | E2B | E4B |
|---|---|---|
| No `answer is (X)` line → scored 0 | 7/100 | 10/100 |
| Hit the 2048-token cap | 6/100 | 10/100 |
| Median answer length | 1792 chars | 1919 chars |

### GSM8K — tinyGSM8k, 100 items (IRT estimate of full GSM8K)

| Model | Output cap | flexible-extract | strict-match | Raw flex | Truncated at cap |
|---|---|---|---|---|---|
| E2B | 256 (lm-eval default) | 65.3% | 46.5% | 67/100 | **24/100** |
| E2B | **1024** | **80.2%** | 50.8% | 81/100 | 0 (longest 798) |
| E4B | 256 (lm-eval default) | 72.6% | 69.5% | 75/100 | **15/100** |

**lm-eval's default 256-token cap understates Gemma 4 by ~15 points.** Raising
the cap flipped 15 questions from wrong to right, all of them answers previously
cut off mid-solution; 1 flipped the other way (llama.cpp is not bit-identical
across server restarts — worth reporting as run-to-run variance). 1024 is the
generation length Meta specifies for GSM8K.

Strict-match stays low on E2B because it ends with `Answer: $70.00` rather than
`#### 70`: 6 answers were right but rejected on format. E4B complies far better
(73 raw strict vs E2B's 48).

---

## 2. Own suite — architectures (10 cases × 4 repeats, warm median)

| Cond | Architecture | Tool selection | Live-data answers | Static | Warm | Cold |
|---|---|---|---|---|---|---|
| A-cpu | little-gemma, E2B | 0/12 | 12 not attempted | 4/4 | 43.5s | 43.7s |
| A-cpu | little-gemma, E4B | 0/12 | 12 not attempted | 4/4 | 92.5s | 92.5s |
| B | llama.cpp bare, E2B | 0/24 | 24 not attempted | 8/8 | 6.4s | 6.6s |
| B | llama.cpp bare, E4B | 0/24 | 24 not attempted | 8/8 | 12.4s | 12.8s |
| D | llama.cpp + naive FC, E2B | **24/24** | call only, never answers | 4/8 | 2.5s | 3.0s |
| D | llama.cpp + naive FC, E4B | **24/24** | call only, never answers | 8/8 | 5.1s | 6.0s |
| E | proposed orchestrator, E2B | 20/24 | 12 correct, 8 not attempted, 4 incorrect | 4/8 | 26.2s | 33.6s |
| E | proposed orchestrator, E4B | **24/24** | **24 correct** | 7/8 | 60.2s | 66.4s |

Condition C (LiteRT-LM) was run and then **dropped from the study**; its files
remain in `benchmark/results/` unreported.

### Findings that contradict the original plan

1. **Gemma 4 does not fabricate — it refuses.** The protocol expected ~100%
   fabrication from tool-less engines. Across all 62 distinct live-data answers,
   no bare engine ever invented a fact; every answer declined or asked for
   context. The metric was reframed to SimpleQA-style correct / incorrect /
   not-attempted grading (`benchmark/live_audit.json`, every answer hand-audited).
2. **Naive function calling already selects tools perfectly** on single-turn
   prompts (24/24 on both models), so the orchestrator's pinning does not beat it
   on selection. What D cannot do is *answer*: it emits a call and stops. The
   defensible claim is end-to-end grounded answering, not selection accuracy.
3. **The orchestrator over-triggers.** Its intent regex routes **15.7% of static
   questions** (35/223) into a pointless lookup — "How many kilograms are in a
   pound?" → `currency_rate`, "Who won the World Cup 2022?" → `match_result`.
   Measured by replaying BFCL's irrelevance prompts through `classify()`
   (`findings/e_classifier_on_bfcl.json`), with the 52 hits hand-audited.

### Known failure modes (all from logs, all reproducible)

- **Currency fallback needs ISO codes.** `fallback_args` parses `TWD to IDR` but
  not "Taiwan dollars to Indonesian rupiah", so it returns None and no lookup
  happens — E/E2B answered "I will search for it now" four times, with no search.
- **Promise-to-search escapes the filter** when it lands in the final flushed
  clause rather than a mid-stream one.
- **E-think/E2B inverted a tool result**: the tool returned Elche 2–3 Real
  Madrid; the answer said Real Madrid *lost*.

---

## 3. MTP and thinking (5 cases × 4 repeats, warm median)

| Model | Cond | Off | MTP on | Speed-up |
|---|---|---|---|---|
| E2B | B | 3.60s | 2.33s | **1.54×** |
| E4B | B | 8.30s | 4.91s | **1.69×** |
| E2B | B-think | 28.28s | 13.68s | **2.07×** |
| E4B | B-think | 63.18s | 29.40s | **2.15×** |
| E2B | E | 29.51s | 23.68s | 1.25× |
| E4B | E | 54.17s | 40.68s | 1.33× |

**MTP is faster on this CPU, and output is byte-identical** with it on and off
(verified per case, both models). This contradicts the project's earlier note
that speculative decoding loses on Pi-class CPUs — that finding came from
little-gemma's and LiteRT's implementations, not llama.cpp's `draft-mtp`.
Because output is identical, MTP needs no accuracy re-runs; it is a latency
result only.

Thinking costs 3–8× latency. On these cases it rescued E/E2B's arithmetic
(4/8 → 8/8) but did not change the bare-model static score, which was already
8/8.

---

## 4. Quantization sweep (E4B, llama.cpp, 4 cases × 4 repeats)

| Quant | File size | Warm | Static |
|---|---|---|---|
| Q4_K_M | 4.64 GiB | 5.57s | 4/8 |
| **Q4_K_XL (QAT)** | 3.93 GiB | 5.19s | **8/8** |
| Q5_K_M | 5.11 GiB | 8.86s | 8/8 |
| Q8_0 | 7.63 GiB | 12.62s | 7/8 |

The QAT build is both the smallest and the fastest here, and the only 4-bit one
that answers the arithmetic case correctly (Q4_K_M says 31, not 29). Q8_0
required `--cache-ram 0`: llama.cpp's default 8192 MiB host prompt cache exceeds
the Pi's RAM, and the first attempt was OOM-killed at question 48.

---

## 5. Harness corrections made during the study

Recorded because they invalidate any earlier numbers taken from this harness:

1. **The model key was only a label.** Conditions B/D/E ran whatever `va-llm`
   happened to have loaded; `run_benchmark.py` now verifies via `/props` and
   switches the model, or refuses to run.
2. **Condition E kept 6 turns of history** while B and D are single-turn, so
   repeats could copy earlier answers. E now runs single-turn
   (`VA_HISTORY_TURNS=0`), which also required fixing `history[-0:]` returning
   the whole list.
3. **little-gemma timings were never captured** — client mode prints none; they
   are parsed from the server log instead.
4. **Runaway generations blocked the queue**: little-gemma has no max-token flag,
   so a timeout now kills and respawns the server and keeps the partial answer.
5. **Scoring**: numeric answers are graded on the first committed number
   (spelled or digits), a promise to search is not a fabrication, and the
   arithmetic case is hand-graded (`benchmark/hand_grades.json`).

---

## 6. Statistical design and what is being re-run

Decoding is greedy, so repeating an identical question set measures only
implementation nondeterminism (~1 point: llama.cpp is not bit-identical across
server restarts, observed as 1 of 100 GSM8K answers flipping). The uncertainty
that matters is which questions were drawn: **±9.7 points at n=100**.

The study therefore uses **three disjoint stratified subsets** — s1/s2/s3,
seeds 20260918/19/20, 100 questions each, verified non-overlapping, pooling to
**n=300 (±5.6)**. Each is reported individually as well as pooled; none is
dropped. The variance repeat needs no extra run: the telemetry rerun of s1 on
E2B repeats the 18 September run question for question.

Method basis: Miller 2024 (arXiv:2411.00640), Madaan et al. 2024
(arXiv:2406.10229), Dodge et al. 2019 (arXiv:1909.03004), Biderman et al. 2024
(arXiv:2405.14782).

Runs queued on the Pi as of 2026-09-20: s1 with telemetry (E2B, E4B), then
s2 and s3 for both models, each wrapped in 1 Hz device telemetry.

## 7. Device cost

Every accuracy run is now wrapped in `run_measured.sh`, which records at 1 Hz:
per-core CPU and MHz, SoC temperature, throttle flags, memory, swap, disk I/O,
the server's RSS and CPU, and board power from the PMIC's per-rail V×I, with an
idle baseline before and after. `summarize_run.py` turns that into energy per
generated token, tok/s/W and thermal summaries.

First measurements (E4B, short workload): **2.34 W idle, 6.86 W working,
7.70 W peak, 1.55 J per generated token** (1.02 J above idle), **0.64
tok/s/W**, no throttling at 2400 MHz.

Power is board DC draw summed over the PMIC rails; it excludes power-supply
conversion loss, so it is consistent between runs but is not wall power. State
that whenever the number is quoted, and use the same method on the Jetson (its
INA3221 rails, not `vcgencmd`) for the comparison to hold.

## 7.1 The Jetson's reasoning-format defect (2026-09-21)

Recorded here because it invalidated runs, and every run gets reported.

The Jetson's `std_mmlupro_jetson.sh` launched llama-server **without**
`-rea off --reasoning-budget -1`, which the Pi carries via va-llm's
`runtime.env`. The lm-eval invocation was identical on both boards; only the
server differed. Measured on one board, one model, one flag apart:

| | `content` | `reasoning_content` |
|---|---|---|
| default | 263 chars | 1,046 chars |
| `-rea off` | 688 chars | 0 |

lm-eval reads `content` alone, so the Jetson scored a fraction of each answer.
On E2B s2, the same 100 questions on both boards:

| | median chars | empty answers | no answer letter | score |
|---|---|---|---|---|
| Pi 5 | 1,880 | 0 | 6 | 51.0% |
| Jetson, defective | 993 | 11 | 23 | 48.0% |
| Jetson, corrected | 2,028 | 0 | 8 | **47.0%** |

**The defect did not cause the score gap.** Correcting it moved accuracy by one
point, downward. What it did change is what the runs are usable for:

| class | effect | usable? |
|---|---|---|
| rates — decode tok/s, J/token, tok/s/W, W, GPU% | all within 1% (22.88→23.00 tok/s, 0.46→0.46 J/token) | **yes** |
| per-run totals — generated tokens, Wh, minutes | −36% (116,679→74,149 tokens); the empty responses drove lm-eval retries | no |
| accuracy | mechanism broken regardless of size of effect | no |

On the matched-config comparison, a paired test over the same 100 questions
gives 44 correct on both, 46 wrong on both, 7 Pi-only, 3 Jetson-only — ten
discordant pairs, **McNemar exact p = 0.34**. No detectable accuracy
difference between the boards.

The boards agree on the *answer letter* for only **70 of 100** questions while
scoring within noise of each other. Same weights, same prompts, greedy
decoding, so this is CPU versus CUDA arithmetic tipping near-ties to different
tokens — and it is accuracy-neutral. That, not the score gap, is the finding.

Defective runs are archived under `stdbench/failed/` and
`measured/failed/` with a `-reasoningfmt-` suffix.

## 8. Capability coverage

Paper 1 claims three capability areas. Only one is covered so far.

| Capability | Benchmark | Pi 5 | Jetson |
|---|---|---|---|
| a. General knowledge / reasoning | MMLU-Pro, GSM8K | done, both models | not started |
| b. Instruction following + tool calling | own 10-case suite + classifier audit; **no standard benchmark run** | partial | not started |
| c. Safety / security | none chosen | — | — |

MMLU-Pro does not touch tool calling, so (b) currently rests on the custom
suite. IFEval (541 prompts, rule-graded) and BFCL (AST-graded, with an
`irrelevance` split that maps onto the over-triggering finding) are installed on
the box and deliberately **kept** for that reason — BFCL can score condition D
directly; condition E needs its prompts replayed through the classifier, as in
§2.3, because the orchestrator executes tools rather than returning them.

## 9. Machine state (2026-09-20)

`MITLAB-EDGE` after cleanup: 38GB used of 117GB, 75GB free.

Installed and needed: llama.cpp, little-gemma, the voice-agent stack (six `va-*`
units, all active), `~/Research/eval-venv` (lm-eval), `~/Research/bfcl-venv`
(kept for (b) above), Gemma 4 GGUFs — E2B/E4B Q4_K_XL QAT, E4B Q4_K_M, Q5_K_M,
Q8_0, and both MTP heads.

Deleted, 21GB: `~/.litert-lm` and `~/litert-venv` (condition C dropped),
`~/.cache/pip`, an unrelated Qwen3-4B GGUF. The raw Sep-14 engine comparison
scratch files were archived to `findings/early-engine-benchmarks/` first.

## 10. Status

Done: MMLU-Pro both models · tinyGSM8k E2B (256/1024) and E4B (256) · Tier 1–3
own suite · MTP × thinking · quant sweep · live-answer audit · classifier audit.

In progress: MMLU-Pro s1 with telemetry (E2B, E4B), then s2 and s3 for both
models — six measured runs, roughly a day of Pi time.

Not done, in rough priority order: **Jetson Orin Nano, all of it** (the CUDA
axis is core to the design, not optional) · capability (b) standard benchmark,
IFEval and BFCL installed but unrun · capability (c) safety and security, no
benchmark chosen · MMLU-Pro thinking-on rows (E2B ~6–8h, E4B ~12–15h) ·
quantization control, Q8_0 through the same harness (~7h).

**No further GSM8K runs.** Its results stay as the methodological appendix on
generation caps (§1).
