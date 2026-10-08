# Results so far — Gemma 4 E2B/E4B on Pi 5, Jetson Orin Nano and iPhone

Three devices, one task set. **Raspberry Pi 5** (`MITLAB-EDGE`, 8 GB, 4× Cortex-A76,
no GPU, governor `ondemand`, active cooler, no thermal throttling observed:
`throttled=0x0` throughout), **Jetson Orin Nano** (`MITLAB-JETSON`, CUDA, 15 W
mode) and, since 2026-10-02, an **iPhone 15 Pro** (MLX, on-device app). The boards
use Unsloth Q4_K_XL **QAT** GGUFs unless a row says otherwise. The iPhone uses MLX
4-bit builds of the same QAT models (§7.3). Sections 1–6 are Pi-only, from
before the Jetson joined. Raw run files: `benchmark/results/` (own suite),
`findings/stdbench/` (lm-eval) and `findings/phone/` (iPhone uploads).

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
   (`findings/audits/e_classifier_on_bfcl.json`), with the 52 hits hand-audited.

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

## 7.3 The iPhone arm, MLX (2026-10-02 – 05)

The baseline task on a phone: the same s1/s2/s3 questions with byte-identical
5-shot prompts, greedy, thinking off and a 2,048-token answer cap, run on-device
by the GemmaBench app (`benchmark/apps/ios`) on an **iPhone 15 Pro** (A17 Pro,
8 GB, iOS 26.6). The phone has no ssh, so the app uploads each run to the
dashboard, which serves it as a third box. All ten uploads are archived in
`findings/phone/`, with a per-run table. That includes a superseded complete
E2B s1 run (also 51/100) and three runs stopped on the phone, kept as their
last live snapshot. The numbers below use the current run per cell.

**Not the same weights as the boards.** The iPhone runs MLX, not llama.cpp,
with MLX 4-bit builds of the same QAT models: E2B `gemma-4-E2B-it-qat-4bit`,
E4B `mlx-community/unsloth-gemma-4-E4B-it-qat-oQ4`. The boards use the Q4_K_XL
GGUFs. So the prompts and questions are the same, but the engine and the
quantisation both differ. This is a cross-platform comparison, not a
device-only one like §7.1.

| | iPhone (s1/s2/s3) | vs Pi 5 | vs Jetson |
|---|---|---|---|
| E2B | **51.0%** (51/47/55) | −0.7 · 130 / 122 / Pi 25 / iPhone 23 · p = **0.89** | −1.7 · 133 / 122 / Orin 25 / iPhone 20 · p = **0.55** |
| E4B | **66.0%** (65/64/69) | +0.3 · 180 / 85 / Pi 17 / iPhone 18 · p = **1.00** | ±0.0 · 181 / 85 / Orin 17 / iPhone 17 · p = **1.00** |
| pooled n=600 | 58.5% | −0.2 · 310 / 207 / 42 / 41 · p = **1.00** | −0.8 · 314 / 207 / 42 / 37 · p = **0.65** |

Each cell: Δ (iPhone − board), then both right / both wrong / board only /
iPhone only, then exact McNemar, paired over the same question ids. The
per-question data is what `/compare` reads (`run_detail.py --paired` on the
boards, the uploads for the iPhone). As a check, the same code reproduces §7.1's
Pi-vs-Jetson cells exactly (136 / 123 / 19 / 22, p = 0.76).

**The phone is as accurate as either board on both models.** It disagrees with
a board on about as many questions as the boards disagree with each other: 48
and 45 on E2B against 41 Pi-vs-Jetson, and 35 and 34 on E4B against 25. Those
disagreements cancel out. Just as between the two boards, E4B is the more
stable model across backends.

Device cost is **not comparable to §7** and is only indicative:

- **Speed.** Decode was ~14 tok/s on E2B and ~9 tok/s on E4B. That puts the
  phone between the Pi and the Jetson, but it is the *throttled* speed: iOS
  thermal state reached 3 (critical) on five of the six current runs, and the
  phone spent 69–78 min of each E2B run and 124–137 min of each E4B run at
  state ≥ 2 (serious). A run took 84–90 min (E2B) and 136–143 min (E4B).
- **Energy.** 6.4–7.0 Wh per E2B run and 10.8–11.4 Wh per E4B run, ~4.5–4.9 W
  mean, 0.35 and 0.59 J/token. These are **whole-phone battery estimates**
  (battery % × capacity, in 1 % steps, screen included). They are not board DC
  draw, so they must not be set against the PMIC / INA3221 figures as equals.
- iOS gives apps no SoC temperature, power rail or GPU utilisation readings.
  Each `n/a` carries its reason in the file's `na_reasons`.

## 7.4 S3 — little-gemma on the Jetson (2026-09-25 – 27)

The baseline task through a second engine: **little-gemma** (pinned upstream
`aee759d`, patched for `-raw` prompts, whole-prompt tokenisation and a 2,048
answer cap; AGENTS.md §5). It runs the same GGUFs, subsets, prompts and caps,
with thinking off (`--thinking off`, engine `-think -1`) and on (`--thinking
on`, `-think 320`, the §7.2 budget). Jetson only: on the Pi's CPU little-gemma
decodes ~6× slower and prefills 41–43× slower than llama.cpp. That would put
the six Pi runs at ~110 h, so they were not run
(`docs/experiment-matrix.md`). All 12 runs passed the serving-flag
fingerprint (`lg-baseline` / `lg-thinking-on`).

| Jetson | llama.cpp (S1 / S2) | little-gemma (S3 / S3t) | Δ | both / neither / llama.cpp only / lg only | McNemar |
|---|---|---|---|---|---|
| E2B, off | 52.7% | **53.0%** (54/51/54) | +0.3 | 145 / 128 / 13 / 14 | p = 1.00 |
| E4B, off | 66.0% | **65.3%** (64/67/65) | −0.7 | 183 / 89 / 15 / 13 | p = 0.85 |
| E2B, thinking on | 49.7% | **49.3%** (48/49/51) | −0.4 | 125 / 128 / 24 / 23 | p = 1.00 |
| E4B, thinking on | 66.7% | **63.7%** (62/63/66) | −3.0 | 176 / 85 / 24 / 15 | p = 0.20 |

**The engine is not a confound.** little-gemma matches llama.cpp within noise
in all four cells. The two engines agree on the answer letter for 77% (E2B) and
83% (E4B) of questions with thinking off. That is about the same agreement as
between the two boards in §7.1, so swapping the engine moves individual answers
about as much as swapping the hardware does.

**Thinking on fails again, on a second engine.** S3t against S3: E2B −3.7
points (126 / 119 / S3 only 33 / S3t only 22, p = 0.18), E4B −1.6 (177 / 90 /
19 / 14, p = 0.49). Unextractable answers rise the same way as in §7.2: E2B
17 → 39, E4B 18 → 32. That makes six model × engine × board combinations
(§7.2 and here), and none is positive beyond noise.

Device cost, pooled over s1/s2/s3:

| Jetson | energy | wall time | decode tok/s | prefill tok/s | mean W | J / gen. token |
|---|---|---|---|---|---|---|
| E2B llama.cpp (S1) | 25.6 Wh | 155 min | 23.0 | 477 | 10.1 | 0.46 |
| E2B little-gemma (S3) | **24.5 Wh** (−4%) | **141 min** (−9%) | 25.6 | 1,690 | 10.6 | 0.45 |
| E4B llama.cpp (S1) | 54.5 Wh | 313 min | 11.6 | 275 | 10.5 | 0.96 |
| E4B little-gemma (S3) | **47.6 Wh** (−13%) | **260 min** (−17%) | 15.1 | 352 | 11.1 | 0.84 |
| E2B little-gemma, thinking (S3t) | 30.5 Wh (+24% vs S3) | 174 min (+23%) | 25.6 | 1,689 | 10.7 | 0.44 |
| E4B little-gemma, thinking (S3t) | 58.7 Wh (+23% vs S3) | 316 min (+22%) | 15.1 | 366 | 11.3 | 0.82 |

little-gemma draws ~0.5 W more but finishes sooner, so it is the cheaper engine
on the Jetson, by more on E4B. It still prefills the whole prompt on every
request: 144k prompt tokens per E4B subset against llama.cpp's 38k. The
Jetson's prefill speed makes that cheap. One caveat on E4B: the S3 s3 run made
**105 requests for 100 questions**, because lm-eval retried 5. That adds about
3.6k tokens and a few minutes to the S3 E4B totals. The scores are unaffected,
since each question is scored once. No throttling was recorded; maximum
temperature was 60.9 °C.

These are measurements of two engines other people wrote. They set the bar
that §7.6 must clear. They are not a contribution (`findings/analyses/iso-accuracy.md`).

## 7.5 S8 — llama.cpp with a TurboQuant KV cache (2026-09-29 – 10-03)

The S1/S2 task unchanged, served by the TurboQuant fork of llama.cpp
(`TheTom/llama-cpp-turboquant` @ `bcb85fc`, built beside each board's pinned
llama.cpp, never over it) with **`-ctk turbo3 -ctv turbo3`**. The fork upgrades
K to `q8_0` itself for Gemma 4's 8:1 GQA, and that default is kept, so the
effective cache is **K = q8_0, V = turbo3**. Both boards, both thinking modes,
24 runs. Every run's captured command line matched `tq-baseline` /
`tq-thinking-on`.

Scores s1/s2/s3, and each S8 cell against the matching llama.cpp cell on the
same board and questions:

| | Pi 5 | vs S1/S2 | Jetson | vs S1/S2 |
|---|---|---|---|---|
| E2B, off | 52.7% (58/50/50) | +1.0 · 18 / 21 · p = 0.75 | 52.0% (58/49/49) | −0.7 · 20 / 18 · p = 0.87 |
| E4B, off | 62.3% (61/61/65) | **−3.4** · 25 / 15 · p = 0.15 | 63.3% (65/61/64) | **−2.7** · 26 / 18 · p = 0.29 |
| E2B, thinking on | 51.3% (53/49/52) | +1.3 · 28 / 32 · p = 0.70 | 49.7% (52/46/51) | ±0.0 · 30 / 30 · p = 1.00 |
| E4B, thinking on | 61.3% (61/62/61) | **−5.0** · 29 / 14 · p = **0.03** | 61.3% (66/58/60) | **−5.4** · 34 / 18 · p = **0.04** |

The middle pair in each cell is llama.cpp-only / TurboQuant-only correct.

**On E4B the compressed cache costs accuracy.** All four E4B cells lose points.
The losses are significant with thinking on, on both boards. Pooled over both
boards and both thinking modes, plain llama.cpp alone gets 114 questions right
and TurboQuant alone 65 (p = 0.0003). Thinking off alone, pooled over both
boards: 51 against 33 (p = 0.06). E2B shows nothing: 96 against 101 over the
same four cells (p = 0.78). The likely reason is that the thinking-on responses
are longer, so the V cache error accumulates over more positions, but this data
cannot show that. The loss repeats across both boards, so it is not
backend-specific: Pi vs Jetson under S8 stays tied (E2B p = 0.86, E4B p =
0.75; thinking on, p = 0.59 and 1.00).

**It is also slower and costlier on both boards**, pooled over s1/s2/s3:

| | energy | wall time | decode tok/s | prefill tok/s | J / gen. token |
|---|---|---|---|---|---|
| Pi E2B, S1 → S8 | 64.2 → 93.4 Wh (+45%) | 552 → 850 min (+54%) | 6.80 → 4.92 | 36.9 → 14.9 | 1.15 → 1.69 |
| Pi E4B, S1 → S8 | 125.5 → 215.8 Wh (+72%) | 1111 → 1988 min (+79%) | 3.37 → 2.19 | 21.3 → 6.4 | 2.20 → 3.75 |
| Jetson E2B, S1 → S8 | 25.6 → 31.4 Wh (+23%) | 155 → 202 min (+30%) | 23.0 → 16.8 | 477 → 438 | 0.46 → 0.59 |
| Jetson E4B, S1 → S8 | 54.5 → 65.7 Wh (+21%) | 313 → 404 min (+29%) | 11.6 → 9.0 | 275 → 209 | 0.96 → 1.15 |

The thinking-on rows add 18–32% on top of that: Pi 113.6 / 254.5 Wh,
Jetson 41.3 / 81.8 Wh, for E2B / E4B.

Two other observations:

- **Memory is the one gain.** The Jetson's peak memory in use fell from 4,841 to
  3,323 MB on E2B and from 6,961 to 4,428 MB on E4B (s1). That frees about
  2.5 GB on a 7.5 GB board. On the Pi, E2B peaked about 0.2 GB lower.
- **The fork prefills more.** It processed ~36% more prompt tokens per subset
  (51.9k against 38.1k on Pi E2B s1), which suggests it reuses less of each
  slot's cached prefix. That adds to its prefill deficit, on top of the
  slower cache arithmetic.

At an 8,192-token context, neither board is short of KV memory with the
uncompressed cache. For this workload, S8 trades accuracy (E4B) and 20-80% more
energy for memory the boards did not need. It would only pay off at contexts
long enough for the KV cache to dominate memory, and this task never reaches
those.

## 7.6 S9 — the proposed engine (2026-10-04 – 08)

S9 is little-gemma plus this project's `ae.patch` (`benchmark/little_gemma/`).
It adds two switches, each designed to change speed only:

- **`-ngram -block 3`**: prompt-lookup drafts, checked by greedy verification
  three tokens at a time.
- **`-reuse`**: KV snapshots of the shared few-shot prefix, restored across
  requests instead of prefilled again.

No MTP head is used, since neither baseline ran speculative decoding. The task is
S3's (thinking off), on the Jetson. Variants: `full` = both switches,
`ngram`, `reuse`, `base` = neither.

**The gate, before any full run** (`ae_gate.py`, 2026-10-04). Each switch set
replays 28 already-answered S3 questions (2 per category) and must return every
reply byte-for-byte. Eleven sweeps all passed, 28/28:

| flags | E2B request time | E4B request time |
|---|---|---|
| none | 576 s, 577 s (rerun) | 1,246 s |
| `-reuse -ngram -block 2` | 502 s, 502 s (rerun) | 1,034 s |
| `-reuse -ngram -block 3` | **497 s**, 489 s (rerun) | **1,018 s** |
| `-reuse -ngram -block 4` | 516 s | 1,031 s |

Block 3 was fastest on both models and is the setting used. The first E2B
`none` and `block 2` sweeps show as *failed* in the queue only because
`ae_gate.py` did not yet write its `.done` marker. Their logs record 28/28, and
their reruns (`-r2`) reproduce them to the second.

**Accuracy: identical to S3 by construction, and verified.** Across all 12 full
runs (`full` and `ngram`, both models, s1/s2/s3), **every one of the 1,200
replies is byte-identical to S3's**. So the scores are S3's exactly: E2B 53.0%
(54/51/54), E4B 65.3% (64/67/65). They are tied with llama.cpp as in §7.4.

**Cost, pooled over s1/s2/s3:**

| Jetson | energy | wall time | J / gen. token | vs S3 | vs llama.cpp S1 |
|---|---|---|---|---|---|
| E2B S3 little-gemma | 24.5 Wh | 141 min | 0.45 | — | −4% Wh, −9% time |
| E2B S9 `ngram` | 20.8 Wh | 124 min | 0.38 | −15% Wh, −12% time | −19% Wh, −20% time |
| E2B S9 `full` | **20.3 Wh** | **121 min** | **0.37** | **−17% Wh, −14% time** | **−21% Wh, −22% time** |
| E4B S3 little-gemma | 47.6 Wh | 260 min | 0.84 | — | −13% Wh, −17% time |
| E4B S9 `ngram` | 38.8 Wh | 214 min | 0.70 | −18% Wh, −18% time | −29% Wh, −32% time |
| E4B S9 `full` | **37.7 Wh** | **208 min** | **0.68** | **−21% Wh, −20% time** | **−31% Wh, −34% time** |

Mean power is unchanged (10.3–11.0 W), so the whole saving is time. Per 100
questions, S9 `full` costs **6.8 Wh on E2B and 12.6 Wh on E4B**, against
the 8.2 and 15.9 Wh bar `iso-accuracy.md` set from S3. The E4B S3 totals
include s3's 5 retried requests (§7.4). Over s1 + s2 alone, which had none,
`full` still takes 18% less time than S3 (139 against 169 min).

**Almost all of the gain is `-ngram`.** `-reuse` cut the prompt tokens
processed per E4B subset from 144k to 38k, but saved only ~1–3% more time. The
Jetson prefills at hundreds to ~1,700 tok/s, so prefill was never the
bottleneck. The `-reuse` snapshot costs 39 MiB, and peak memory was otherwise
unchanged (E4B s1: 5,804 MB `full` against 5,924 MB S3).

**`reuse` alone (2026-10-07 – 08).** The first six `reuse` jobs never started.
The queue's fingerprint check gave up after 420 s with "no llama-server
appeared", and each run's `server.log` shows why: `lg_openai_shim.py` exited at
once with *argument --engine-flags: expected one argument*. With
`VARIANT=reuse` the value is the single token `-reuse`, and argparse treats a
leading-dash value as an option unless it contains a space. `-ngram -block 3`
contains one, which is why the other variants ran. The run script now passes
`--engine-flags=-reuse`, and all six reruns completed and passed the
fingerprint. The six original jobs still sit blocked in the queue.

All 600 replies are byte-identical to S3's and to `full`'s, so the scores are
again S3's. Cost, pooled over s1/s2/s3:

| Jetson | energy | wall time | J / gen. token | prompt tokens / subset | vs S3 |
|---|---|---|---|---|---|
| E2B S9 `reuse` | 25.5 Wh | 136 min | 0.46 | 38k (S3: 144k) | +4% Wh, −4% time |
| E4B S9 `reuse` | 47.6 Wh | 238 min | 0.85 | 38k (S3: 144k) | ±0% Wh, −8% time |

**Read the time column, not the energy column.** These runs were made after
the Jetson's clocks were locked (§7.7), which adds 5–9% energy at unchanged
speed. S3 ran before the lock. So the +4% / ±0% energy does not show that
`-reuse` costs energy; on equal clocks it would most likely be a small saving.
The time saving is real. It comes from prefill: E2B s1 spent 29 s prefilling
against S3's 86 s. It is small next to `-ngram`'s, as `full` against `ngram`
already showed.

**`base`** (neither switch) is still not queued. The gate's no-switch sweeps
(28/28 on both models) are its only evidence so far.

**Repeatability.** `full` was rerun on E2B s1 on 2026-10-07 (`-r2`), three days
after the first run and under the locked clocks. All 100 replies are
byte-identical to the first run's.

## 7.7 The Jetson's clocks were locked between 2026-10-05 and 10-07

Every Jetson run up to 2026-10-05 ~10:00 ran with the clocks scaling freely:
CPU averaging 830–910 MHz, GPU averaging 580–605 MHz, idle draw 4.5–4.6 W.
Every run from 2026-10-07 19:30 on runs with them pinned: CPU at 1,497 MHz
(`scaling_min_freq` = `scaling_max_freq`), GPU at 612 MHz (devfreq min = max),
idle 4.9–5.0 W. That is the signature of `jetson_clocks`. `nvpmodel` mode 0 is
unchanged since the 2026-10-04 boot, and the clocks are still locked as of
2026-10-08. The journal does not say who or what locked them.

Two pairs of runs measure what the lock does. Each pair produced byte-identical
replies, so only the clocks differ:

| E2B s1 | before | after | Δ energy | Δ time |
|---|---|---|---|---|
| llama.cpp S1 → S10 `n3m2` (which never drafted, §7.8) | 7.65 Wh, 46.5 min | 8.06 Wh, 45.6 min | +5% | −2% |
| S9 `full` → `full-r2` | 6.66 Wh, 39.7 min | 7.29 Wh, 40.9 min | +9% | +3% |

**So locked clocks cost 5–9% more energy and leave speed within ±3%.** The work
is GPU-bound, and the GPU was already near 612 MHz. Wall-time comparisons across
the change are therefore usable. Energy comparisons across it are not. This
affects §7.6's `reuse` rows and all of §7.8. Every earlier result is untouched.

## 7.8 S10 — llama.cpp's own n-gram speculation (2026-10-07 – 08)

S10 is the fair baseline for S9. It is stock llama.cpp (Jetson build `a894dae`)
with its own prompt-lookup drafting, `--spec-type ngram-simple`, on the S1 task
unchanged (thinking off, same flags otherwise). It asks how much of S9's gain
llama.cpp would get from switching on what it already ships. Three settings:

- **`n3m3`**: 3-token lookup, 3-token drafts (`--spec-ngram-simple-size-n 3
  --spec-ngram-simple-size-m 3 --spec-draft-n-max 3`), the closest match to S9's
  `-ngram -block 3`. The full grid: both models, s1/s2/s3.
- **`default`**: llama.cpp's own settings (12-token lookup, 48-token drafts).
  E2B s1 only, as a pilot.
- **`n3m2`**: as `n3m3` but 2-token drafts. E2B s1 only. **It never drafted.**
  Its `server.log` has no draft-acceptance line for any of the 100 requests,
  so it is really a plain S1 rerun. The cause was not investigated. Its use
  here is as the same-day, locked-clock S1 control (§7.7).

All 8 runs passed the `ngram-baseline` fingerprint.

**Accuracy: tied with S1, but not the same answers.**

| Jetson | S1 | S10 `n3m3` | Δ | both / neither / S1 only / S10 only | McNemar | same text | same letter |
|---|---|---|---|---|---|---|---|
| E2B | 52.7% | **53.3%** (56/51/53) | +0.6 | 143 / 125 / 15 / 17 | p = 0.86 | 29 / 300 | 76% |
| E4B | 66.0% | **65.0%** (62/66/67) | −1.0 | 184 / 91 / 14 / 11 | p = 0.69 | 20 / 300 | 85% |
| E2B s1, `default` | 56% | 53% | −3 | 5 / 2 only | p = 0.45 | 9 / 100 | 85% |

Greedy verification should in theory reproduce S1's text exactly. It does not:
only 7–10% of `n3m3` replies match S1 byte for byte. The answer letter changes
about as often as between the Pi and the Jetson (§7.1). The likely cause is
that verifying several tokens in one batch takes different CUDA kernels from
single-token decode. The logits then differ in the last bits, and greedy flips
at near-ties. This was not verified. S9 is different: the gate and all 1,900
full-run replies show its speculation is byte-exact against its own baseline
(§7.6). For the paper: **S10 is accuracy-neutral but not lossless; S9 is
lossless.**

**Drafting.** `n3m3` accepted 46% of drafted tokens on E2B (53.7k of 117.5k)
and 44% on E4B (47.1k of 108.3k), about 1.36 and 1.29 tokens per decode step.
`default` drafted on 94 of 100 requests but accepted only 17% (5.5k of 32.8k).
Long 48-token drafts rarely survive on this task.

**Cost, pooled over s1/s2/s3**:

| Jetson | energy | wall time | decode tok/s | mean W | J / gen. token |
|---|---|---|---|---|---|
| E2B S1 | 25.6 Wh | 155 min | 23.0 | 10.1 | 0.46 |
| E2B S10 `n3m3` | 24.1 Wh (−6%) | 139 min (−10%) | 26.6 | 10.6 | 0.43 |
| E4B S1 | 54.5 Wh | 313 min | 11.6 | 10.5 | 0.96 |
| E4B S10 `n3m3` | 50.4 Wh (−7%) | 271 min (−13%) | 13.8 | 11.3 | 0.87 |

S1 here is the 2026-09-22 runs, made before the clock lock (§7.7). Two
consequences:

- The **time saving holds** within the lock's ±3%. Speculation raises decode
  speed by 16–19%.
- The **energy saving is understated** by about the lock's 5–9%. The only
  same-clock comparison is E2B s1: `n3m3` against the `n3m2` control is
  7.51 against 8.06 Wh (−7%) and 43.5 against 45.6 min (−5%). `default` gets
  −2% and −2%.

**Against S9.** n-gram drafting speeds up decode by about the same fraction in
both engines: llama.cpp 23.0 → 26.6 tok/s (+16%) on E2B and 11.6 → 13.8 (+19%)
on E4B; little-gemma 25.6 → 29.5 (+15%) and 15.1 → 17.8 (+18%). S9's larger
total gain is little-gemma's head start plus the same speculation, not better
speculation. Per 100 questions, S10 `n3m3` costs 8.0 Wh (E2B) and 16.8 Wh (E4B).
That is close to S3's 8.2 / 15.9 Wh bar and above S9 `full`'s 6.8 / 12.6. The
S10 figures carry the lock's surcharge, so on equal clocks it would be roughly
7.4 / 15.6 Wh. That still leaves S9 ahead by about 8% (E2B) and 19% (E4B).
That last estimate is not measured.

Memory: peak in use fell slightly, 4.52–4.58 GB against S1's 4.82–4.84 GB
(E2B) and 6.59–6.62 against 6.96–7.09 GB (E4B). Prompt tokens and prefill speed
match S1 (~38k per subset, ~480 / ~280 tok/s).

**Not run:** `default` and `n3m2` beyond the E2B s1 pilot; S10 on the Pi. The
Pi's llama.cpp (`661643e`) has the same `--spec-type ngram-simple`, but no Pi
entry exists for `mmlupro-ngram`.

## 8. Capability coverage

Paper 1 claims three capability areas. Only one is covered so far.

| Capability | Benchmark | Pi 5 | Jetson | iPhone |
|---|---|---|---|---|
| a. General knowledge / reasoning | MMLU-Pro, GSM8K | MMLU-Pro done: llama.cpp (S1/S2), TurboQuant (S8), thinking off and on; GSM8K done | MMLU-Pro done: llama.cpp, little-gemma (S3), TurboQuant (S8), thinking off and on; the proposed engine (S9) and llama.cpp n-gram (S10) thinking off | MMLU-Pro done, thinking off |
| b. Instruction following + tool calling | own 10-case suite + classifier audit; **no standard benchmark run** | partial | not started | not started |
| c. Safety / security | none chosen | — | — | — |

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

## 10. Status (2026-10-08)

**Written up here:**
- MMLU-Pro both models · tinyGSM8k E2B (256/1024) and E4B (256) · Tier 1–3
  own suite · MTP × thinking · quant sweep · live-answer audit · classifier
  audit.
- **MMLU-Pro, s1/s2/s3 × E2B/E4B, every condition that has run:**
  - S1 and S2 on both boards (§7.1, §7.2).
  - The iPhone (§7.3).
  - S3 and S3t, little-gemma on the Jetson (§7.4).
  - S8 TurboQuant on both boards, thinking off and on (§7.5).
  - S9 `full`, `ngram` and `reuse`, the proposed engine (§7.6).
  - S10 `n3m3`, llama.cpp's own n-gram speculation, on the Jetson (§7.8).

All board runs passed the serving-flag fingerprint. Jetson runs from
2026-10-07 on ran with locked clocks (§7.7): compare their time, not their
energy, against earlier runs.

Headline, n = 300 per model:

| | E2B | E4B | cheapest Jetson Wh per 100 q (E2B / E4B) |
|---|---|---|---|
| baseline, Pi / Jetson / iPhone (MLX) | 51.7 / 52.7 / 51.0% | 65.7 / 66.0 / 66.0% | 8.5 / 18.2 |
| thinking on (320), vs the same engine off | −1.4 to −3.7 | −2.0 to +0.7 | +18–32% cost |
| little-gemma (S3) | 53.0% | 65.3% | 8.2 / 15.9 |
| TurboQuant KV (S8) | 52.7 / 52.0% | **62.3 / 63.3%** | 10.5 / 21.9 |
| proposed engine (S9 `full`) | 53.0% (= S3, byte-identical) | 65.3% (= S3) | **6.8 / 12.6** |
| llama.cpp n-gram (S10 `n3m3`) | 53.3% (not byte-identical to S1) | 65.0% | 8.0 / 16.8 (locked clocks, §7.7) |

**Open:**
- **The Jetson's clocks are still locked** (§7.7). Either restore them
  (`sudo jetson_clocks --restore` or a reboot; needs the password) before the
  next run, or accept the locked state and rerun the controls needed for
  same-clock energy: S1 E4B and S3 on both models.
- S9 `base` is not queued.
- Eight stale Jetson jobs still sit blocked: `mmlupro-e4b-s2-think` and
  `-s3-think` from 2026-09-23 (false-positive memory check; their cells were
  completed on 2026-09-24), and the six original `reuse` jobs, since rerun.
  All eight can be cancelled.
- The S9 and S10 code (`job_kinds.json` `mmlupro-ae` and `mmlupro-ngram`,
  `SPEC=` in `std_mmlupro_jetson.sh`, the queue and run scripts) is modified on
  the Jetson but not committed. `ae_gate.py` is committed (2026-10-04).
  `replay_lookup.py` exists only on the Pi, untracked.
- The S3/S8/S9/S10 per-question samples live on the boards. Unlike S1/S2's,
  they are not yet copied into `findings/stdbench/`.

**Not started**, in rough priority order: capability (b) standard benchmark
(IFEval and BFCL installed but unrun) · capability (c) safety and security (no
benchmark chosen) · precision control (S7: E4B Q5_K_M, the highest precision
both boards fit; `docs/experiment-matrix.md`).

**No further GSM8K runs.** Its results stay as the methodological appendix on
generation caps (§1).
