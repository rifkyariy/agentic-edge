# Experiment matrix — every condition, done and proposed

Fixed on every row: MMLU-Pro, three disjoint 100-question subsets (`s1`/`s2`/`s3`),
5-shot CoT prompt, greedy, `max_gen_toks` 2048, `-c 8192`, `--cache-ram 0`,
identical Q4_K_XL QAT weights. One run = one board × one model × one subset =
100 questions. A condition is complete at **6 runs per board** (2 models × 3
subsets, n=300 per model).

## Status

| | condition | engine | thinking | Pi 5 | Jetson | runs left |
|---|---|---|---|---|---|---|
| **S1** | baseline | llama.cpp | off | ✅ 6/6 | ✅ 6/6 | — |
| **S2** | thinking-on | llama.cpp | on | ✅ 6/6 | ✅ 6/6 | — |
| **S3** | engine swap | little-gemma | off | ⬜ 0/6 | ✅ 6/6 | 6 (Pi, not worth it) |
| **S3t** | little-gemma + thinking | little-gemma | on | ⬜ 0/6 | ✅ 6/6 | — |
| **S4** | letter-only | either | off | ⬜ 0/6 | ⬜ 0/6 | 12 |
| **S5** | cascade | llama.cpp¹ | gated | ⬜ 0/6 | ⬜ 0/6 | 12 |
| **S6** | encoder router | + ModernBERT | gated | ⬜ conditional | ⬜ conditional | 12 |
| **S7** | precision control | llama.cpp Q5_K_M | off | ⬜ 0/3 | ⬜ 0/3 | 6 (E4B only) |

¹ S5 needs logits at the final position, which neither engine exposes today, so
it costs an engine patch either way. It has to be **llama.cpp**: S5 is
prefill-bound, and little-gemma's CPU prefill is 41–43× slower (0.84 tok/s on
E4B), which on the Pi makes a prefill-only tier cost as much as the full-CoT
baseline it replaces. little-gemma stays as S3 on the Jetson, where it is CUDA
and competitive. See the proposal §3b.

## Results so far

| board | condition | model | n | pooled | min/run | vs S1 |
|---|---|---|---|---|---|---|
| Pi 5 | S1 baseline | E2B | 300 | **51.7%** | 183 | — |
| Pi 5 | S2 thinking-on | E2B | 300 | 50.0% | 227 | **−1.7 pts, +24% time** |
| Pi 5 | S1 baseline | E4B | 300 | **65.7%** | 368 | — |
| Pi 5 | S2 thinking-on | E4B | 300 | 66.3% | 442 | +0.6 pts, +20% time |
| Jetson | S1 baseline | E2B | 300 | **52.7%** | 50 | — |
| Jetson | S2 thinking-on | E2B | 300 | 49.7% | 63 | **−3.0 pts, +26% time** |
| Jetson | S3 little-gemma | E2B | 300 | 53.0% | 45 | +0.3 pts, −10% time |
| Jetson | S1 baseline | E4B | 300 | **66.0%** | 100 | — |
| Jetson | S2 thinking-on | E4B | 300 | 66.7% | 125 | +0.7 pts, +25% time |
| Jetson | S3 little-gemma | E4B | 300 | 65.3% | 83 | −0.7 pts, −17% time |
| Jetson | S3t lg + thinking | E2B | 300 | 49.3% | 56 | **−3.7 pts, +25% time** |
| Jetson | S3t lg + thinking | E4B | 300 | 63.7% | 102 | **−1.6 pts, +23% time** |

**Two results already in hand, and both point the same way as the proposal.**

*Thinking-on does not pay, and it now fails on two engines independently.*
llama.cpp: E2B −1.7 (Pi) and −3.0 (Orin), E4B +0.6 and +0.7, all for 20–26%
more time. little-gemma, same board and subsets: **E2B −3.7, E4B −1.6**, for
23–25% more time. Six model-engine-board combinations, not one of them
positive beyond noise. Extra reasoning tokens are not where the headroom is on
this benchmark — the premise S4/S5 rest on, now replicated rather than
assumed.

*The engine is not the variable either.* little-gemma lands within 0.5 points
of llama.cpp on both models while running slightly faster. That validates it as
a fair swap, and means S5 can be built on it without confounding the result.

## Cost of the remaining work

Letter-only floors are prefill + ~4 generated tokens, from each board's own
measured medians. Treat them as floors: a single measured question on the
Jetson took 11.0 s against a 0.6 s floor, so per-request overhead dominates
once generation stops being the cost.

| condition | Pi 5 | Jetson | total device-time |
|---|---|---|---|
| S3 finish Jetson (1 run) | — | ~1.4 h | **1.4 h** |
| S3 on the Pi (6 runs) | ~110 h ⚠️ | — | **~110 h** |
| S4 letter-only (12 runs) | ~2.6 h | ~0.3 h | **~3 h** |
| S5 cascade (12 runs) | 3–18 h² | 0.4–2.5 h² | **4–20 h** |
| S6 router (12 runs) | as S5 + encoder | as S5 | **~as S5** |

² depends entirely on the escalation rate: at τ routing 70% to Tier 0 it is
≈0.7×S4 + 0.3×S1; the τ sweep is the experiment, not a fixed number.

⚠️ **S3 on the Pi is the expensive one and should not run.** little-gemma on Pi
CPU is ~6× slower at decode *and* 41–43× slower at prefill
(`gemma4-pi5-benchmarks.md`), so E4B would be ~37 h *per subset*. The engine
comparison is already answered on the Jetson; repeating it on the Pi costs
~110 h to confirm what the early engine benchmarks showed in September.

## Order I would run them

1. **S4 letter-only, Jetson first** (~0.3 h). Cheapest possible falsification of
   the whole proposal. If accuracy collapses against S1, S5 and S6 die here.
2. **S4 on the Pi** (~2.6 h) — only if the Jetson holds up.
3. **Finish S3 `lg-e4b-s3`** (~1.4 h) to close that condition at n=300.
4. **S5** only if S4 holds accuracy within a few points, since it is the only
   step needing an engine patch.
5. **S6** only if S5's gate proves badly calibrated.

S3-on-Pi sits outside this order deliberately: it is 110 h to answer a question
the Jetson has already answered.

## S7 — the precision control, and why it is Q5_K_M not Q8_0

`findings/RESULTS.md` plans this as **Q8_0**, and that will not work as a
two-board control:

| model | size | Pi 5 (8,062 MB, mmapped) | Jetson (7,485 MB, CUDA-pinned) |
|---|---|---|---|
| E4B Q4_K_XL (current) | 3.93 GiB | ok — measured peak 4,162 MB | ok — measured peak 6,874 MB |
| **E4B Q5_K_M** | **5.11 GiB** | **ok** | **ok** |
| E4B Q8_0 | 7.63 GiB | thrashes — 7,813 MB of weights alone | **will not fit** |

`-ngl 99` pins the Jetson's allocation, so 7,813 MB into 7,485 MB is not a
tight fit, it is impossible. On the Pi the weights are evictable page cache, so
Q8_0 would *run* but page-fault-bound, which makes its device-cost numbers
meaningless — and device cost is half of what we measure.

**Q5_K_M is the highest precision runnable on both boards**, so it is the
control. It is already on the Pi; the Jetson needs a copy. E4B only — no
higher-precision E2B GGUF exists on either board, which matters because E2B is
the model with the larger gap to close.

## What each row would add to the paper

| condition | the claim it supports |
|---|---|
| S1 | the device comparison itself — tied on accuracy, 3.4× and 2.4× apart on speed and energy |
| S2 | more reasoning tokens do not buy accuracy here (already established, negative result, keep it) |
| S3 | the engine is not a confound; llama.cpp and little-gemma agree within noise |
| S4 | how much of the decode budget is actually load-bearing for accuracy |
| S5 | accuracy per joule under a gate — the contribution |
| S6 | whether a small encoder routes better than the model's own margin |
| S7 | whether the gap to Google's published figures is quantization or protocol — without it, every accuracy claim is chasing an unknown residual |
