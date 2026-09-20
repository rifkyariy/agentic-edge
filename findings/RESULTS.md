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
deployed 4096 would truncate), `--cache-ram 0`.

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

## 6. Status

Done: MMLU-Pro both models · tinyGSM8k E2B (256/1024) and E4B (256) · Tier 1–3
own suite · MTP × thinking · quant sweep · live-answer audit · classifier audit.

Not done: MMLU-Pro thinking-on rows · MMLU-Pro repeat for run-to-run variance ·
quantization control (Q8_0 through the same harness) · tinyGSM8k E4B at 1024 ·
everything on the Jetson Orin Nano · safety and security capability (no
benchmark chosen) · standard benchmark for instruction following / tool calling
(IFEval and BFCL installed but dropped).
