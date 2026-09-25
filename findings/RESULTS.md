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
config. `-rea` is `--reasoning`, the thinking switch itself — `off` means the
model does not reason, so this is a genuine no-chain-of-thought baseline.
`--reasoning-format` is the separate flag that places any thoughts, and its
default `auto` hides them in `reasoning_content`, which lm-eval never reads.
Both boards must carry both; see §7.1 and AGENTS.md §5.

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

## 7.1 The Jetson's missing `-rea` (2026-09-21)

Recorded here because it invalidated runs, and every run gets reported.

The Jetson's `std_mmlupro_jetson.sh` launched llama-server **without**
`-rea off --reasoning-budget -1`, which the Pi carries via va-llm's
`runtime.env`. `-rea` is `--reasoning`, the thinking switch: unset it defaults
to `auto`, Gemma's template turns thinking **on**, and the separate
`--reasoning-format` — also `auto` — then files those thoughts under
`reasoning_content`. So the Jetson was reasoning when the Pi was not, *and*
discarding the result. Two differences at once, not one. The lm-eval invocation was identical on both boards; only the
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

**Its size was badly misjudged from one subset.** E2B s2, the first subset
re-run, moved 48.0% -> 47.0% and was read as "worth roughly zero points". With
all six runs redone on 2026-09-22 the pooled effect is the opposite:

| | defective | corrected | Δ |
|---|---|---|---|
| Jetson E2B, n=300 | 48.3% | **52.7%** | +4.4 |
| Jetson E4B, n=300 | 60.0% | **66.0%** | +6.0 |

s2 was the single subset where correcting it did not help. Judging the fix on
that one run inverted the conclusion — the reason the protocol pools three
subsets rather than trusting one.

What the defect changes is what a run is usable for:

| class | effect | usable? |
|---|---|---|
| rates — decode tok/s, J/token, tok/s/W, W, GPU% | all within 1% (22.88→23.00 tok/s, 0.46→0.46 J/token) | **yes** |
| per-run totals — generated tokens, Wh, minutes | −36% (116,679→74,149 tokens); the empty responses drove lm-eval retries | no |
| accuracy | mechanism broken regardless of size of effect | no |

### Matched-config comparison, both boards complete (n=300 per model)

| | Pi 5 | Jetson | Δ | both right | both wrong | Pi only | Orin only | McNemar |
|---|---|---|---|---|---|---|---|---|
| E2B | 51.7% (56/51/48) | **52.7%** (56/47/55) | +1.0 | 136 | 123 | 19 | 22 | p = **0.76** |
| E4B | 65.7% (64/66/67) | **66.0%** (67/66/65) | +0.3 | 185 | 90 | 12 | 13 | p = **1.00** |
| pooled n=600 | | | +0.6 | 321 | 213 | 31 | 35 | p = **0.71** |

**Neither board is detectably more accurate.** The original reading — that the
Pi led by 2-5 points — was an artefact of the defect, and the residual leads
here are noise in the other direction. Counted independently from lm-eval's
samples files and from `run_detail.py`, these four cells agree exactly.

The boards pick the *same answer letter* on only about **79%** of the 600
questions — roughly 72% on E2B against 86% on E4B. (The exact count moves by a
few questions depending on whether the first or last `answer is (X)` in a
response is taken, so treat the rate as ±1 point; the correctness figures above
do not have that ambiguity.) Same weights, same prompts, greedy decoding, so
this is CPU versus CUDA arithmetic tipping near-ties to different tokens, and it
is accuracy-neutral: of the questions they answer differently, the Pi wins 31
and the Orin 35. The larger model is markedly more stable across the two
backends. That, not the score gap, is the finding worth carrying into the
manuscript.

Defective runs are archived under `stdbench/failed/` and
`measured/failed/` with a `-reasoningfmt-` suffix.

## 7.2 MMLU-Pro with thinking on (2026-09-23 – 24)

The thinking-on condition: the baseline task unchanged (same s1/s2/s3, 5-shot
CoT, greedy, `max_gen_toks` 2048, `-c 8192`, `--cache-ram 0`), served with
**`-rea on --reasoning-budget 320 --reasoning-format none`** so the thoughts
come back inline in `content`, where lm-eval reads them. All 12 runs (2 boards
× 2 models × 3 subsets) have telemetry. Every run's live `llama-server` command
line was captured once it was serving and matched `baselines.json`
(`mmlupro-thinking-on`) on every key, on both boards. Only the model path and
the Jetson's `-ngl 99` differ.

Every run is listed here. On the Jetson, E4B s2 and s3 were first queued on
2026-09-23 and **blocked** by the memory precheck: it wanted ~5,400 MB free and
the board had ~5,255 MB. That was a false positive. E4B s1 thinking-on had
already completed from 5,238 MB, with a minimum of 354 MB left. Both were
resubmitted on 2026-09-24 with the precheck overridden, and those runs are the
ones reported. Jetson E4B s1 was launched by hand, outside the queue. Its
`server_args_after` shows the same flags as the queued runs.

| | Pi 5 base | Pi 5 think | Δ | Jetson base | Jetson think | Δ |
|---|---|---|---|---|---|---|
| E2B, n=300 | 51.7% | **50.0%** (48/50/52) | −1.7 | 52.7% | **49.7%** (49/51/49) | −3.0 |
| E4B, n=300 | 65.7% | **66.3%** (64/69/66) | +0.6 | 66.0% | **66.7%** (65/67/68) | +0.7 |

Paired over the same 300 questions:

| | both right | both wrong | first only | second only | McNemar |
|---|---|---|---|---|---|
| E2B Pi, base vs think | 121 | 116 | 34 | 29 | p = 0.61 |
| E2B Jetson, base vs think | 126 | 119 | 32 | 23 | p = 0.28 |
| E4B Pi, base vs think | 179 | 83 | 18 | 20 | p = 0.87 |
| E4B Jetson, base vs think | 182 | 84 | 16 | 18 | p = 0.86 |
| E2B think, Pi vs Jetson | 120 | 121 | 30 | 29 | p = 1.00 |
| E4B think, Pi vs Jetson | 188 | 89 | 11 | 12 | p = 1.00 |

**A 320-token thinking budget does not detectably change MMLU-Pro accuracy**
for either model on either board. E2B leans slightly worse and E4B slightly
better, but no difference comes close to significance. The two boards remain
tied with thinking on, as they are without it. They agree on the answer letter
for 69% (E2B) and 86% (E4B) of questions, the same pattern as the baseline in
§7.1: E4B is again markedly more stable across backends.

Why the budget likely adds so little: it binds on most questions. Thoughts run
a median ~1,250 characters, p90 ~1,520, max ~1,720. That is about what 320
tokens holds, on every board and model. The model then writes its usual 5-shot
chain of thought after the thought block. So thinking-on here means a capped
preamble in front of the same CoT, not a longer reasoning process. A larger
budget would be a different experiment, and this data does not predict it.

Format losses (n=300 each):

| | E2B base | E2B think | E4B base | E4B think |
|---|---|---|---|---|
| No `answer is (X)` → 0, Pi | 25 | **41** | 25 | 27 |
| No `answer is (X)` → 0, Jetson | 22 | **39** | 20 | 24 |
| Hit the 2048-token cap, Pi | 25 | 25 | 27 | 20 |
| Hit the 2048-token cap, Jetson | 20 | 30 | 21 | 19 |
| Thought never closed, both boards | — | 1 | — | 6 |
| No thought block at all, both boards | — | 2 | — | 0 |

E2B's extra unextractable answers (+16 / +17) roughly equal its accuracy loss.
Thinking costs E2B mostly by breaking the answer format, not by making it
reason worse. No response was left empty after its thought block.

Device cost, pooled over the three subsets:

| | generated tokens | energy | wall time | J / generated token |
|---|---|---|---|---|
| E2B Pi | 201.6k → 251.0k (+25%) | 64.2 → 79.8 Wh (+24%) | 552 → 685 min | 1.15 → 1.14 |
| E2B Jetson | 198.7k → 252.0k (+27%) | 25.6 → 32.6 Wh (+27%) | 155 → 196 min | 0.46 → 0.46 |
| E4B Pi | 205.0k → 249.4k (+22%) | 125.5 → 151.2 Wh (+20%) | 1111 → 1332 min | 2.20 → 2.18 |
| E4B Jetson | 203.2k → 254.0k (+25%) | 54.5 → 67.5 Wh (+24%) | 313 → 386 min | 0.96 → 0.96 |

Thinking is a pure volume cost: **+20-27% tokens, energy and time for no
measurable accuracy**. The rates do not move. Decode speed (Pi 6.6-6.9 / 3.3-3.4
tok/s, Jetson 22.8-22.9 / 11.6 tok/s), mean power (Pi ~7 W, Jetson ~10.1-10.6 W)
and J/token all match the baseline, so the per-token comparison between boards
in §7.1 carries over unchanged. Peak power rose ~1-1.5 W on the Jetson (to
12.6 W). No throttling was recorded on either board. Maximum SoC temperature
was 76.5 °C on the Pi (E4B s1) and 60.2 °C on the Jetson.

## 8. Capability coverage

Paper 1 claims three capability areas. Only one is covered so far.

| Capability | Benchmark | Pi 5 | Jetson |
|---|---|---|---|
| a. General knowledge / reasoning | MMLU-Pro (thinking off and on), GSM8K | done, both models | MMLU-Pro done, both models, thinking off and on |
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

## 10. Status (2026-09-26)

Done: MMLU-Pro both models · tinyGSM8k E2B (256/1024) and E4B (256) · Tier 1–3
own suite · MTP × thinking · quant sweep · live-answer audit · classifier audit ·
**MMLU-Pro s1/s2/s3 × E2B/E4B on both boards with telemetry, thinking off
(§7.1) and thinking on (§7.2)**, all 24 runs on matched serving flags.

In progress: little-gemma (S3) on the Jetson, thinking off, E2B s1 done and
s2/s3 queued. E4B and the thinking-on rows follow. Not reported here yet.

Not done, in rough priority order: capability (b) standard benchmark, IFEval
and BFCL installed but unrun · capability (c) safety and security, no benchmark
chosen · quantization control, Q8_0 through the same harness (~7h).

**No further GSM8K runs.** Its results stay as the methodological appendix on
generation caps (§1).
