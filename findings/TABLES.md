# Results tables

Every result in this repository as tables, **generated from the committed data** by `python3 benchmark/results_tables.py`. Do not edit by hand: change the data or the script and regenerate. The write-up and interpretation are in [`RESULTS.md`](RESULTS.md); which experiments exist and where their data lives is in [`../docs/experiments.md`](../docs/experiments.md).

**Names.** CoPR is the paper's name for the proposed engine; run names call it `ae` (S9). `lg` is little-gemma (S3), `ngram-n3m3` is llama.cpp's n-gram drafting at width 4 (S10), an empty row name is plain llama.cpp (S1). Power is board DC draw (INA3221 on the Jetson, PMIC on the Pi), not wall power.

**Contents.** 1 · the manuscript's tables — 2 · reply identity between engines — 3 · accuracy by subset, paired tests, by subject — 4 · every Jetson run — 5 · Pi and iPhone runs — 6 · tinyGSM8k — 7 · own suite — 8 · data vs manuscript

## 1. The manuscript's tables, from the data

Rebuilt from `findings/runs/jetson/` by the functions `paper_tables.py` checks against the paper (203 values match; the two Table IV rounding errata are noted where they fall). Jetson Orin Nano 8 GB, 15 W, greedy, thinking off.

### Table I — baseline anatomy, E2B, n=300

| engine | generated tokens | decode tok/s | prompt tokens prefilled / q | share of time in prefill % | accuracy % |
|---|---:|---:|---:|---:|---:|
| llama.cpp | 198,706 | 23.00 | 381 | 2.7 | 52.7 |
| little-gemma | 197,977 | 25.58 | 1,444 | 3.2 | 53.0 |

### Table III — the engine comparison, n=300 per cell

**Gemma 4 E2B**

| engine | accuracy % (95% CI) | replies = little-gemma | decode tok/s | prompt tok / q | wall s / q | W generating | J / gen. token | J above idle |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| llama.cpp | 52.7 ± 5.6 | 32/300 | 23.00 | 381 | 31.0 | 10.26 | 0.465 | 0.258 |
| llama.cpp + n-gram (width 4) | 53.3 ± 5.6 | 29/300 to llama.cpp | 26.63 | 381 | 27.9 | 10.84 | 0.429 | 0.228 |
| little-gemma | 53.0 ± 5.6 | — | 25.58 | 1,444 | 28.3 | 10.86 | 0.446 | 0.254 |
| **CoPR** | 53.0 ± 5.6 | 300/300 | 29.52 | 385 | 24.1 | 10.58 | 0.370 | 0.207 |

**Gemma 4 E4B**

| engine | accuracy % (95% CI) | replies = little-gemma | decode tok/s | prompt tok / q | wall s / q | W generating | J / gen. token | J above idle |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| llama.cpp | 66.0 ± 5.4 | 28/300 | 11.62 | 381 | 62.6 | 10.77 | 0.965 | 0.552 |
| llama.cpp + n-gram (width 4) | 65.0 ± 5.4 | 20/300 to llama.cpp | 13.83 | 381 | 54.3 | 11.53 | 0.871 | 0.487 |
| little-gemma | 65.3 ± 5.4 | — | 15.05 | 1,446 | 51.9 | 11.62 | 0.838 | 0.490 |
| **CoPR** | 65.3 ± 5.4 | 300/300 | 17.67 | 385 | 41.6 | 11.39 | 0.676 | 0.396 |

### Table IV — llama.cpp's own n-gram drafting against CoPR, E2B, s1 (n=100)

| row | exact | acc % | decode tok/s | wall s/q | J / tok | above idle | idle W | run |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| llama.cpp, no drafting | — | 56 | 23.04 | 27.9 | 0.466 | 0.259 | 4.49 | 2026-09-22 00:22 |
| llama.cpp n-gram, width 3 (`n3m2`) — never drafted, see §8 | 100/100 | 56 | 23.80 | 27.4 | 0.491 | 0.266 | 4.96 | 2026-10-07 20:11 |
| llama.cpp n-gram, width 4 (`n3m3`) | 8/100 | 56 | 26.97 | 26.1 | 0.424 | 0.224 | 4.99 | 2026-10-07 20:56 |
| llama.cpp n-gram, stock settings | 9/100 | 53 | 25.15 | 26.8 | 0.458 | 0.249 | 4.94 | 2026-10-07 21:40 |
| **CoPR**, width 3 | 100/100 | 54 | 29.54 | 23.8 | 0.369 | 0.207 | 4.55 | 2026-10-04 22:27 |
| **CoPR**, repeat three days later | 100/100 | 54 | 29.78 | 24.6 | 0.404 | 0.219 | 5.01 | 2026-10-07 19:30 |

"exact": replies identical to the same engine without drafting. The paper prints 0.225 and 0.370 for two of these cells; the data gives 0.224 and 0.369 (rounded twice).

### Table V — ablation, n=300 per row; every row byte-identical to little-gemma

| model | engine | decode tok/s | prompt tok / q | wall s / q | J / tok | replies = little-gemma |
|---|---|---:|---:|---:|---:|---:|
| E2B | little-gemma | 25.58 | 1,444 | 28.3 | 0.446 | — |
| E2B | little-gemma + prompt lookup | 29.51 | 1,444 | 24.8 | 0.378 | 300/300 |
| E2B | little-gemma + prefix reuse | 25.81 | 385 | 27.2 | 0.464 | 300/300 |
| E2B | + both (**CoPR**) | 29.52 | 385 | 24.1 | 0.370 | 300/300 |
| E4B | little-gemma | 15.05 | 1,446 | 51.9 | 0.838 | — |
| E4B | little-gemma + prompt lookup | 17.82 | 1,444 | 42.7 | 0.696 | 300/300 |
| E4B | little-gemma + prefix reuse | 15.47 | 385 | 47.6 | 0.853 | 300/300 |
| E4B | + both (**CoPR**) | 17.67 | 385 | 41.6 | 0.676 | 300/300 |

### Table VI — verify width, 28 s1 questions (2 per subject)

| width | E2B tok/s | E2B J/tok | E4B tok/s | E4B J/tok | +tokens / verify (E2B) | verify cost, plain steps (E2B) | byte-identical E2B · E4B |
|---|---:|---:|---:|---:|---:|---:|---:|
| none | 25.63 | 0.451 | 15.39 | 0.879 | — | 1.00 | 28/28 · 28/28 |
| 2 | 29.62 | 0.386 | 17.76 | 0.736 | 0.57 | 1.24 | 28/28 · 28/28 |
| 3 | 29.93 | 0.381 | 17.91 | 0.707 | 0.90 | 1.47 | 28/28 · 28/28 |
| 4 | 28.81 | 0.393 | 17.63 | 0.713 | 1.12 | 1.76 | 28/28 · 28/28 |

Repeats of two E2B sweeps, not in the paper:

| run | tok/s | J/tok | +tokens / verify | byte-identical |
|---|---:|---:|---:|---:|
| ae-sweep-e2b-b0-r2 | 25.60 | 0.462 | — | 28/28 |
| ae-sweep-e2b-b2-r2 | 29.64 | 0.385 | 0.57 | 28/28 |

### Table VIII — the same checkpoint and 300 questions on three devices

| device | engine | model | accuracy % | decode tok/s | J / token |
|---|---|---|---:|---:|---:|
| Jetson Orin Nano, 15 W | CoPR | E2B | 53.0 | 29.52 | 0.370 |
| Jetson Orin Nano, 15 W | llama.cpp | E2B | 52.7 | 23.00 | 0.465 |
| Raspberry Pi 5 (CPU) | llama.cpp | E2B | 51.7 | 6.87 | 1.130 |
| iPhone 15 Pro | MLX 4-bit | E2B | 51.0 | 14.50 | 0.354 (battery est.) |
| Jetson Orin Nano, 15 W | CoPR | E4B | 65.3 | 17.67 | 0.676 |
| Jetson Orin Nano, 15 W | llama.cpp | E4B | 66.0 | 11.62 | 0.965 |
| Raspberry Pi 5 (CPU) | llama.cpp | E4B | 65.7 | 3.37 | 2.223 |
| iPhone 15 Pro | MLX 4-bit | E4B | 66.0 | 9.18 | 0.593 (battery est.) |

Pi rates are pooled over the two subsets with request logs (s2, s3); the iPhone's energy is a whole-phone battery estimate, not board DC power, and it ran thermally throttled. These rows compare deployments, not engines.

## 2. Which engines give the same replies

Replies byte-identical between two engines, out of 300 questions per model (Jetson, same weights and prompts). Greedy decoding on one engine is deterministic; across engines, kernels differ and greedy flips at near-ties.

**E2B**

|  | llama.cpp | llama.cpp + n-gram (width 4) | little-gemma | **CoPR** | little-gemma + prompt lookup | little-gemma + prefix reuse |
|---|---:|---:|---:|---:|---:|---:|
| llama.cpp | 300 | 29 | 32 | 32 | 32 | 32 |
| llama.cpp + n-gram (width 4) | 29 | 300 | 34 | 34 | 34 | 34 |
| little-gemma | 32 | 34 | 300 | 300 | 300 | 300 |
| **CoPR** | 32 | 34 | 300 | 300 | 300 | 300 |
| little-gemma + prompt lookup | 32 | 34 | 300 | 300 | 300 | 300 |
| little-gemma + prefix reuse | 32 | 34 | 300 | 300 | 300 | 300 |

**E4B**

|  | llama.cpp | llama.cpp + n-gram (width 4) | little-gemma | **CoPR** | little-gemma + prompt lookup | little-gemma + prefix reuse |
|---|---:|---:|---:|---:|---:|---:|
| llama.cpp | 300 | 20 | 28 | 28 | 28 | 28 |
| llama.cpp + n-gram (width 4) | 20 | 300 | 20 | 20 | 20 | 20 |
| little-gemma | 28 | 20 | 300 | 300 | 300 | 300 |
| **CoPR** | 28 | 20 | 300 | 300 | 300 | 300 |
| little-gemma + prompt lookup | 28 | 20 | 300 | 300 | 300 | 300 |
| little-gemma + prefix reuse | 28 | 20 | 300 | 300 | 300 | 300 |

## 3. Accuracy

MMLU-Pro, 5-shot chain of thought, greedy, thinking off. ± is the 95% interval from question sampling (±9.7 points at n=100, ±5.6 at n=300); runs differ far less than that from one repeat to the next.

### By subset

| device | engine | model | s1 | s2 | s3 | pooled % (95% CI) |
|---|---|---|---:|---:|---:|---:|
| Jetson | llama.cpp | E2B | 56 | 47 | 55 | 52.7 ± 5.6 |
| Jetson | llama.cpp + n-gram (width 4) | E2B | 56 | 51 | 53 | 53.3 ± 5.6 |
| Jetson | little-gemma | E2B | 54 | 51 | 54 | 53.0 ± 5.6 |
| Jetson | **CoPR** | E2B | 54 | 51 | 54 | 53.0 ± 5.6 |
| Jetson | llama.cpp | E4B | 67 | 66 | 65 | 66.0 ± 5.4 |
| Jetson | llama.cpp + n-gram (width 4) | E4B | 62 | 66 | 67 | 65.0 ± 5.4 |
| Jetson | little-gemma | E4B | 64 | 67 | 65 | 65.3 ± 5.4 |
| Jetson | **CoPR** | E4B | 64 | 67 | 65 | 65.3 ± 5.4 |
| Pi 5 | llama.cpp | E2B | 56 | 51 | 48 | 51.7 ± 5.7 |
| Pi 5 | llama.cpp | E4B | 64 | 66 | 67 | 65.7 ± 5.4 |
| iPhone | MLX 4-bit | E2B | 51 | 47 | 55 | 51.0 ± 5.7 |
| iPhone | MLX 4-bit | E4B | 65 | 64 | 69 | 66.0 ± 5.4 |

### Paired tests (exact two-sided McNemar, same question ids)

| model | comparison | Δ points | right only in first | right only in llama.cpp | p |
|---|---|---:|---:|---:|---:|
| E2B | llama.cpp + n-gram (width 4) vs llama.cpp | +0.7 | 17 | 15 | 0.86 |
| E2B | little-gemma vs llama.cpp | +0.3 | 14 | 13 | 1.00 |
| E2B | **CoPR** vs llama.cpp | +0.3 | 14 | 13 | 1.00 |
| E4B | llama.cpp + n-gram (width 4) vs llama.cpp | -1.0 | 11 | 14 | 0.69 |
| E4B | little-gemma vs llama.cpp | -0.7 | 13 | 15 | 0.85 |
| E4B | **CoPR** vs llama.cpp | -0.7 | 13 | 15 | 0.85 |

### By subject, pooled s1–s3 (Jetson)

**E2B** — 9–33 questions per subject, so read these as indicative only.

| subject | n | llama.cpp | little-gemma | CoPR (= little-gemma) |
|---|---:|---:|---:|---:|
| biology | 18 | 14 (78%) | 13 (72%) | 13 (72%) |
| business | 21 | 12 (57%) | 12 (57%) | 12 (57%) |
| chemistry | 27 | 14 (52%) | 17 (63%) | 17 (63%) |
| computer science | 9 | 5 (56%) | 5 (56%) | 5 (56%) |
| economics | 21 | 12 (57%) | 10 (48%) | 10 (48%) |
| engineering | 24 | 6 (25%) | 6 (25%) | 6 (25%) |
| health | 21 | 11 (52%) | 12 (57%) | 12 (57%) |
| history | 9 | 4 (44%) | 5 (56%) | 5 (56%) |
| law | 27 | 9 (33%) | 6 (22%) | 6 (22%) |
| math | 33 | 25 (76%) | 25 (76%) | 25 (76%) |
| other | 24 | 8 (33%) | 10 (42%) | 10 (42%) |
| philosophy | 12 | 7 (58%) | 7 (58%) | 7 (58%) |
| physics | 33 | 20 (61%) | 22 (67%) | 22 (67%) |
| psychology | 21 | 11 (52%) | 9 (43%) | 9 (43%) |

**E4B** — 9–33 questions per subject, so read these as indicative only.

| subject | n | llama.cpp | little-gemma | CoPR (= little-gemma) |
|---|---:|---:|---:|---:|
| biology | 18 | 13 (72%) | 12 (67%) | 12 (67%) |
| business | 21 | 15 (71%) | 15 (71%) | 15 (71%) |
| chemistry | 27 | 18 (67%) | 17 (63%) | 17 (63%) |
| computer science | 9 | 7 (78%) | 7 (78%) | 7 (78%) |
| economics | 21 | 15 (71%) | 13 (62%) | 13 (62%) |
| engineering | 24 | 10 (42%) | 12 (50%) | 12 (50%) |
| health | 21 | 13 (62%) | 14 (67%) | 14 (67%) |
| history | 9 | 7 (78%) | 7 (78%) | 7 (78%) |
| law | 27 | 11 (41%) | 10 (37%) | 10 (37%) |
| math | 33 | 28 (85%) | 27 (82%) | 27 (82%) |
| other | 24 | 14 (58%) | 14 (58%) | 14 (58%) |
| philosophy | 12 | 8 (67%) | 8 (67%) | 8 (67%) |
| physics | 33 | 26 (79%) | 27 (82%) | 27 (82%) |
| psychology | 21 | 13 (62%) | 13 (62%) | 13 (62%) |

## 4. Every Jetson run in `findings/runs/jetson/`

One row per run, straight from its `measured/summary.json` and samples. Runs from 2026-10-07 19:30 on had the clocks pinned (CPU ~1,497 MHz instead of scaling), which adds 5–9% energy; compare their time, not their energy, with earlier rows. "fingerprint" is the live serving command line checked against `benchmark/baselines.json`; the S1 runs predate the queue and were launched by hand with the same flags.

| run | started | acc % | decode tok/s | prefill tok/s | prompt tok/q | gen. tokens | wall min | W gen. | J/tok | above idle | idle W | peak °C | GPU MHz | CPU MHz | fingerprint |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `e2b-s1` | 2026-09-22 00:22 | 56 | 23.04 | 482 | 380 | 59,053 | 46.5 | 10.27 | 0.466 | 0.259 | 4.49 | 60.8 | 612 | 902 | hand-launched |
| `e2b-s2` | 2026-09-21 22:40 | 47 | 23.00 | 472 | 371 | 74,149 | 57.3 | 10.25 | 0.462 | 0.256 | 4.51 | 57.5 | 612 | 898 | hand-launched |
| `e2b-s3` | 2026-09-22 01:08 | 55 | 22.96 | 477 | 391 | 65,504 | 51.3 | 10.27 | 0.466 | 0.258 | 4.53 | 56.9 | 612 | 887 | hand-launched |
| `e4b-s1` | 2026-09-22 09:52 | 67 | 11.63 | 273 | 381 | 66,165 | 101.9 | 10.76 | 0.963 | 0.553 | 4.48 | 59.7 | 612 | 902 | hand-launched |
| `e4b-s2` | 2026-09-22 12:52 | 66 | 11.60 | 272 | 371 | 68,372 | 105.4 | 10.78 | 0.967 | 0.552 | 4.53 | 59.6 | 612 | 913 | hand-launched |
| `e4b-s3` | 2026-09-22 14:48 | 65 | 11.64 | 279 | 391 | 68,679 | 105.9 | 10.77 | 0.964 | 0.552 | 4.50 | 57.8 | 612 | 912 | hand-launched |
| `ngram-n3m3-e2b-s1` | 2026-10-07 20:56 | 56 | 26.97 | 480 | 381 | 63,741 | 43.5 | 10.84 | 0.424 | 0.224 | 4.99 | 60.6 | 612 | 1497 | ok · ngram-baseline |
| `ngram-n3m3-e2b-s2` | 2026-10-08 04:38 | 51 | 26.39 | 482 | 371 | 68,322 | 47.6 | 10.85 | 0.433 | 0.231 | 4.95 | 61.7 | 612 | 1497 | ok · ngram-baseline |
| `ngram-n3m3-e2b-s3` | 2026-10-08 05:26 | 53 | 26.56 | 489 | 391 | 69,997 | 48.2 | 10.83 | 0.429 | 0.229 | 4.94 | 61.4 | 612 | 1497 | ok · ngram-baseline |
| `ngram-n3m3-e4b-s1` | 2026-10-08 06:14 | 62 | 13.78 | 280 | 381 | 69,200 | 90.6 | 11.53 | 0.875 | 0.491 | 4.94 | 62.5 | 612 | 1497 | ok · ngram-baseline |
| `ngram-n3m3-e4b-s2` | 2026-10-08 07:45 | 66 | 13.82 | 280 | 371 | 69,324 | 90.3 | 11.54 | 0.872 | 0.486 | 4.99 | 62.6 | 612 | 1497 | ok · ngram-baseline |
| `ngram-n3m3-e4b-s3` | 2026-10-08 09:15 | 67 | 13.88 | 284 | 391 | 69,860 | 90.5 | 11.53 | 0.867 | 0.484 | 4.99 | 62.8 | 612 | 1497 | ok · ngram-baseline |
| `ngram-n3m2-e2b-s1` | 2026-10-07 20:11 | 56 | 23.80 | 492 | 380 | 59,053 | 45.6 | 11.10 | 0.491 | 0.266 | 4.96 | 61.3 | 612 | 1497 | ok · ngram-baseline |
| `ngram-default-e2b-s1` | 2026-10-07 21:40 | 53 | 25.15 | 489 | 381 | 62,024 | 44.6 | 11.01 | 0.458 | 0.249 | 4.94 | 60.7 | 612 | 1497 | ok · ngram-baseline |
| `lg-e2b-s1` | 2026-09-25 22:50 | 54 | 25.57 | 1687 | 1444 | 64,880 | 47.2 | 10.88 | 0.451 | 0.255 | 4.59 | 60.5 | 612 | 845 | ok · lg-baseline |
| `lg-e2b-s2` | 2026-09-25 23:59 | 51 | 25.59 | 1694 | 1435 | 68,627 | 48.4 | 10.86 | 0.443 | 0.253 | 4.58 | 60.9 | 612 | 849 | ok · lg-baseline |
| `lg-e2b-s3` | 2026-09-26 00:48 | 54 | 25.59 | 1690 | 1454 | 64,470 | 45.8 | 10.83 | 0.443 | 0.254 | 4.55 | 55.3 | 612 | 834 | ok · lg-baseline |
| `lg-e4b-s1` | 2026-09-27 00:15 | 64 | 15.05 | 331 | 1444 | 67,070 | 86.2 | 11.64 | 0.844 | 0.491 | 4.63 | 60.2 | 612 | 856 | ok · lg-baseline |
| `lg-e4b-s2` | 2026-09-27 01:41 | 67 | 15.12 | 375 | 1435 | 65,943 | 83.2 | 11.65 | 0.836 | 0.492 | 4.59 | 60.5 | 612 | 858 | ok · lg-baseline |
| `lg-e4b-s3` | 2026-09-27 03:04 | 65 | 14.99 | 351 | 1460 | 71,241 | 90.2 | 11.58 | 0.836 | 0.487 | 4.64 | 59.9 | 612 | 864 | ok · lg-baseline |
| `ae-full-e2b-s1` | 2026-10-04 22:27 | 54 | 29.54 | 1305 | 385 | 64,880 | 39.7 | 10.56 | 0.369 | 0.207 | 4.55 | 59.8 | 612 | 870 | ok · ae-full |
| `ae-full-e2b-s2` | 2026-10-04 23:07 | 51 | 29.38 | 1296 | 376 | 68,627 | 41.7 | 10.60 | 0.371 | 0.210 | 4.53 | 59.7 | 612 | 882 | ok · ae-full |
| `ae-full-e2b-s3` | 2026-10-04 23:49 | 54 | 29.64 | 1315 | 395 | 64,470 | 39.1 | 10.59 | 0.368 | 0.206 | 4.59 | 60.6 | 612 | 870 | ok · ae-full |
| `ae-full-e4b-s1` | 2026-10-05 00:28 | 64 | 17.46 | 221 | 385 | 67,070 | 70.8 | 11.33 | 0.683 | 0.399 | 4.55 | 62.0 | 612 | 871 | ok · ae-full |
| `ae-full-e4b-s2` | 2026-10-05 01:39 | 67 | 17.74 | 267 | 376 | 65,943 | 68.0 | 11.44 | 0.675 | 0.396 | 4.58 | 61.7 | 612 | 883 | ok · ae-full |
| `ae-full-e4b-s3` | 2026-10-05 02:47 | 65 | 17.82 | 282 | 395 | 67,601 | 69.2 | 11.40 | 0.670 | 0.393 | 4.58 | 60.7 | 612 | 879 | ok · ae-full |
| `ae-full-r2-e2b-s1` | 2026-10-07 19:30 | 54 | 29.78 | 634 | 385 | 64,880 | 40.9 | 11.42 | 0.404 | 0.219 | 5.01 | 62.2 | 612 | 1497 | ok · ae-full |
| `ae-ngram-e2b-s1` | 2026-10-05 03:56 | 54 | 29.55 | 1687 | 1444 | 64,880 | 41.1 | 10.55 | 0.380 | 0.211 | 4.55 | 59.6 | 612 | 863 | ok · ae-ngram |
| `ae-ngram-e2b-s2` | 2026-10-05 04:37 | 51 | 29.37 | 1691 | 1435 | 68,627 | 42.7 | 10.57 | 0.378 | 0.213 | 4.54 | 59.8 | 612 | 855 | ok · ae-ngram |
| `ae-ngram-e2b-s3` | 2026-10-05 05:20 | 54 | 29.63 | 1687 | 1454 | 64,470 | 40.0 | 10.56 | 0.376 | 0.211 | 4.55 | 59.6 | 612 | 856 | ok · ae-ngram |
| `ae-ngram-e4b-s1` | 2026-10-05 06:21 | 64 | 17.71 | 473 | 1444 | 67,070 | 72.4 | 11.41 | 0.702 | 0.413 | 4.53 | 60.9 | 612 | 862 | ok · ae-ngram |
| `ae-ngram-e4b-s2` | 2026-10-05 07:33 | 67 | 17.83 | 520 | 1435 | 65,943 | 70.2 | 11.42 | 0.696 | 0.410 | 4.55 | 60.3 | 612 | 864 | ok · ae-ngram |
| `ae-ngram-e4b-s3` | 2026-10-05 08:44 | 65 | 17.90 | 524 | 1454 | 67,601 | 71.2 | 11.41 | 0.691 | 0.407 | 4.55 | 61.6 | 612 | 864 | ok · ae-ngram |
| `ae-reuse-e2b-s1` | 2026-10-07 22:24 | 54 | 25.80 | 1339 | 385 | 64,880 | 44.7 | 11.68 | 0.464 | 0.263 | 4.98 | 61.6 | 612 | 1497 | ok · ae-reuse |
| `ae-reuse-e2b-s2` | 2026-10-07 23:09 | 51 | 25.81 | 1331 | 376 | 68,627 | 47.0 | 11.68 | 0.463 | 0.264 | 4.95 | 61.8 | 612 | 1497 | ok · ae-reuse |
| `ae-reuse-e2b-s3` | 2026-10-07 23:56 | 54 | 25.82 | 1351 | 395 | 64,470 | 44.3 | 11.69 | 0.464 | 0.264 | 4.95 | 62.6 | 612 | 1497 | ok · ae-reuse |
| `ae-reuse-e4b-s1` | 2026-10-08 00:41 | 64 | 15.45 | 184 | 385 | 67,070 | 80.3 | 12.61 | 0.858 | 0.502 | 5.01 | 63.6 | 612 | 1497 | ok · ae-reuse |
| `ae-reuse-e4b-s2` | 2026-10-08 02:01 | 67 | 15.50 | 216 | 376 | 65,943 | 77.9 | 12.61 | 0.851 | 0.504 | 4.97 | 63.8 | 612 | 1497 | ok · ae-reuse |
| `ae-reuse-e4b-s3` | 2026-10-08 03:19 | 65 | 15.48 | 231 | 395 | 67,601 | 79.7 | 12.60 | 0.851 | 0.503 | 4.99 | 63.7 | 612 | 1497 | ok · ae-reuse |

### Failed runs

| run | started | why it failed |
|---|---|---|
| `mmlupro100-ae-reuse-e2b-s1-flagsbug` | 2026-10-05 06:00 | lg_openai_shim.py: error: argument --engine-flags: expected one argument |
| `mmlupro100-ae-reuse-e2b-s2-flagsbug` | 2026-10-05 06:07 | lg_openai_shim.py: error: argument --engine-flags: expected one argument |
| `mmlupro100-ae-reuse-e2b-s3-flagsbug` | 2026-10-05 06:14 | lg_openai_shim.py: error: argument --engine-flags: expected one argument |
| `mmlupro100-ae-reuse-e4b-s1-flagsbug` | 2026-10-05 09:55 | lg_openai_shim.py: error: argument --engine-flags: expected one argument |
| `mmlupro100-ae-reuse-e4b-s2-flagsbug` | 2026-10-05 10:02 | lg_openai_shim.py: error: argument --engine-flags: expected one argument |
| `mmlupro100-ae-reuse-e4b-s3-flagsbug` | 2026-10-05 10:09 | lg_openai_shim.py: error: argument --engine-flags: expected one argument |

All six were rerun after the fix; the reruns are the `ae-reuse-*` rows above.

## 5. Pi 5 and iPhone, run by run

### Raspberry Pi 5, llama.cpp `661643e` (CPU), from `findings/export/`

| run | subset | acc % | minutes | decode tok/s | mean W | Wh | J / gen. token | peak °C |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `mmlupro100-e2b` | s1 | 56 | 181 | 6.66 | 7.05 | 21.37 | 1.179 | 72 |
| `mmlupro100-e2b-s2` | s2 | 51 | 177 | 6.82 | 6.89 | 20.37 | 1.124 | 71 |
| `mmlupro100-e2b-s3` | s3 | 48 | 190 | 6.91 | 7.08 | 22.42 | 1.135 | 73 |
| `mmlupro100-e4b-s1` | s1 | 64 | 359 | 3.37 | 6.66 | 39.98 | 2.164 | 73 |
| `mmlupro100-e4b-s2` | s2 | 66 | 377 | 3.33 | 6.72 | 42.37 | 2.200 | 73 |
| `mmlupro100-e4b-s3` | s3 | 67 | 369 | 3.41 | 7.01 | 43.16 | 2.247 | 76 |

### iPhone 15 Pro, MLX, every upload in `findings/phone/`

| run | subset | status | correct | decode tok/s | Wh (est.) | J/tok (est.) | iOS thermal max |
|---|---|---|---:|---:|---:|---:|---:|
| `mmlupro-e2b-s1-20261002-222849` | s1 | done | 51/100 | 12.4 | — | — | 3 |
| `mmlupro-e2b-s1-20261003-002005` | s1 | stopped (last live snapshot) | 10/20 | 15.0 | 1.90 | 0.467 | 2 |
| `mmlupro-e2b-s1-20261003-150850` | s1 | done (current) | 51/100 | 14.0 | 6.35 | 0.347 | 2 |
| `mmlupro-e2b-s2-20261003-212509` | s2 | stopped (last live snapshot) | 22/40 | 14.5 | 3.68 | 0.373 | 3 |
| `mmlupro-e2b-s2-20261003-233936` | s2 | done (current) | 47/100 | 14.6 | 6.98 | 0.361 | 3 |
| `mmlupro-e2b-s3-20261004-115841` | s3 | done (current) | 55/100 | 14.2 | 6.99 | 0.353 | 3 |
| `mmlupro-e4b-oq4-s1-20261004-210658` | s1 | stopped (last live snapshot) | 7/10 | 10.4 | — | — | 2 |
| `mmlupro-e4b-oq4-s1-20261004-211929` | s1 | done (current) | 65/100 | 9.2 | 11.43 | 0.598 | 3 |
| `mmlupro-e4b-oq4-s2-20261005-112446` | s2 | done (current) | 64/100 | 8.9 | 11.43 | 0.598 | 3 |
| `mmlupro-e4b-oq4-s3-20261005-152451` | s3 | done (current) | 69/100 | 9.4 | 10.79 | 0.582 | 3 |

## 6. tinyGSM8k (Pi 5, llama.cpp)

100 items, IRT-estimated full-GSM8K accuracy. The 256-token cap is lm-eval's default and truncates chain of thought mid-solution; at 1,024 the same model scores 15 points higher.

| model | answer cap | flexible extract % | strict match % | data |
|---|---:|---:|---:|---|
| E2B | 256 | 65.3 | 46.5 | `B-e2b` |
| E2B | 1,024 | 80.2 | 50.8 | `tiny1024-e2b` |
| E4B | 256 | 72.6 | 69.5 | `B-e4b` |

## 7. Own suite (Pi 5, not in the manuscript)

The 10-case suite against five architectures, MTP × thinking and an E4B quantisation sweep, from `benchmark/results/*.json` via `benchmark/report.py`. Write-up: `findings/RESULTS.md` §2–§4.

### T1 — Architecture comparison

Tool-selection and fabrication are over the tool-requiring cases; static accuracy over the fixed-ground-truth cases. Latency is warm median, cold shown separately.

| device | cond | architecture | model | tool sel. | fabrication | static acc | TTFT (warm) | total (warm) | total (cold) |
|---|---|---|---|---|---|---|---|---|---|
| raspi5 | A-cpu | little-gemma (bare) [CPU] | gemma4-e2b | 0.0% (0/12) | 0.0% (0/12) | 100.0% (4/4) | 11.79 | 43.529 | 43.651 |
| raspi5 | A-cpu | little-gemma (bare) [CPU] | gemma4-e4b | 0.0% (0/12) | 0.0% (0/12) | 100.0% (4/4) | 24.75 | 92.51 | 92.524 |
| raspi5 | B | llama.cpp (bare) | gemma4-e2b | 0.0% (0/24) | 0.0% (0/24) | 100.0% (8/8) | 0.221 | 6.445 | 6.625 |
| raspi5 | B | llama.cpp (bare) | gemma4-e2b | 0.0% (0/8) | 0.0% (0/8) | 100.0% (8/8) | 0.22 | 3.596 | 3.774 |
| raspi5 | B | llama.cpp (bare) | gemma4-e4b | 0.0% (0/4) | 0.0% (0/4) | 50.0% (4/8) | 0.645 | 5.565 | 7.479 |
| raspi5 | B | llama.cpp (bare) | gemma4-e4b | 0.0% (0/24) | 0.0% (0/24) | 100.0% (8/8) | 0.462 | 12.434 | 12.815 |
| raspi5 | B | llama.cpp (bare) | gemma4-e4b | 0.0% (0/8) | 0.0% (0/8) | 100.0% (8/8) | 0.473 | 8.303 | 8.921 |
| raspi5 | B | llama.cpp (bare) | gemma4-e4b | 0.0% (0/4) | 0.0% (0/4) | 100.0% (8/8) | 0.44 | 5.19 | 5.967 |
| raspi5 | B | llama.cpp (bare) | gemma4-e4b | 0.0% (0/4) | 0.0% (0/4) | 100.0% (8/8) | 0.738 | 8.864 | 11.104 |
| raspi5 | B | llama.cpp (bare) | gemma4-e4b | 0.0% (0/4) | 0.0% (0/4) | 87.5% (7/8) | 0.924 | 12.622 | 15.246 |
| raspi5 | B-mtp | llama.cpp (bare) [MTP] | gemma4-e2b | 0.0% (0/8) | 0.0% (0/8) | 100.0% (8/8) | 0.221 | 2.331 | 2.508 |
| raspi5 | B-mtp | llama.cpp (bare) [MTP] | gemma4-e4b | 0.0% (0/8) | 0.0% (0/8) | 100.0% (8/8) | 0.428 | 4.912 | 5.481 |
| raspi5 | B-mtp-think | llama.cpp (bare) [MTP, thinking] | gemma4-e2b | 0.0% (0/8) | 0.0% (0/8) | 100.0% (8/8) | 11.615 | 13.682 | 14.006 |
| raspi5 | B-mtp-think | llama.cpp (bare) [MTP, thinking] | gemma4-e4b | 0.0% (0/8) | 0.0% (0/8) | 100.0% (8/8) | 20.518 | 29.399 | 29.097 |
| raspi5 | B-think | llama.cpp (bare) [thinking] | gemma4-e2b | 0.0% (0/8) | 0.0% (0/8) | 100.0% (8/8) | 23.802 | 28.283 | 28.552 |
| raspi5 | B-think | llama.cpp (bare) [thinking] | gemma4-e4b | 0.0% (0/8) | 0.0% (0/8) | 100.0% (8/8) | 44.347 | 63.176 | 63.637 |
| raspi5 | C | LiteRT-LM (bare) | gemma4-e2b | skipped: model — E2B is NOT imported on this box, so condition C is E4B-only. Serve with: /home/mitlab/litert-venv/bin/litert-lm serve --host 127.0.0.1 --port 9379 (no model argument; the request's model id picks the bundle) | — | — | — | — | — |
| raspi5 | C | LiteRT-LM (bare) | gemma4-e4b | 0.0% (0/24) | 0.0% (0/24) | 50.0% (4/8) | 4.287 | 17.511 | 18.648 |
| raspi5 | D | llama.cpp + naive function calling | gemma4-e2b | 100.0% (24/24) | 0.0% (0/24) | 50.0% (4/8) | 0.142 | 2.54 | 3.018 |
| raspi5 | D | llama.cpp + naive function calling | gemma4-e4b | 100.0% (24/24) | 0.0% (0/24) | 100.0% (8/8) | 0.272 | 5.05 | 6.03 |
| raspi5 | E | proposed orchestrator | gemma4-e2b | 83.3% (20/24) | 0.0% (0/24) | 50.0% (4/8) | 24.195 | 26.16 | 33.575 |
| raspi5 | E | proposed orchestrator | gemma4-e2b | 100.0% (8/8) | 0.0% (0/8) | 50.0% (4/8) | 29.51 | 29.51 | 37.24 |
| raspi5 | E | proposed orchestrator | gemma4-e4b | 100.0% (24/24) | 0.0% (0/24) | 87.5% (7/8) | 57.785 | 60.235 | 66.395 |
| raspi5 | E | proposed orchestrator | gemma4-e4b | 100.0% (8/8) | 0.0% (0/8) | 87.5% (7/8) | 54.17 | 54.17 | 66.61 |
| raspi5 | E-mtp | proposed orchestrator [MTP] | gemma4-e2b | 100.0% (8/8) | 0.0% (0/8) | 50.0% (4/8) | 23.68 | 23.68 | 37.05 |
| raspi5 | E-mtp | proposed orchestrator [MTP] | gemma4-e4b | 100.0% (8/8) | 0.0% (0/8) | 100.0% (8/8) | 40.68 | 40.68 | 64.42 |
| raspi5 | E-mtp-think | proposed orchestrator [MTP, thinking] | gemma4-e2b | 100.0% (8/8) | 0.0% (0/8) | 100.0% (8/8) | 45.07 | 51.05 | 52.96 |
| raspi5 | E-mtp-think | proposed orchestrator [MTP, thinking] | gemma4-e4b | 100.0% (8/8) | 0.0% (0/8) | 100.0% (8/8) | 88.02 | 94.1 | 94.86 |
| raspi5 | E-think | proposed orchestrator [thinking] | gemma4-e2b | 100.0% (8/8) | 0.0% (0/8) | 100.0% (8/8) | 51.46 | 59.36 | 72.33 |
| raspi5 | E-think | proposed orchestrator [thinking] | gemma4-e4b | 100.0% (8/8) | 0.0% (0/8) | 100.0% (8/8) | 107.34 | 109.32 | 128.67 |

### T2 — MTP x thinking x CUDA

Only engines that support the toggles appear. `model time` excludes tool network I/O, which is not the architecture's cost.

| device | cuda | cond | model | mtp | TTFT | total | model time | tok/s | static acc |
|---|---|---|---|---|---|---|---|---|---|
| raspi5 | no | B | gemma4-e2b | off | 0.221 | 6.445 | — | — | 100.0% (8/8) |
| raspi5 | no | B | gemma4-e2b | off | 0.22 | 3.596 | — | — | 100.0% (8/8) |
| raspi5 | no | B | gemma4-e4b | off | 0.645 | 5.565 | — | — | 50.0% (4/8) |
| raspi5 | no | B | gemma4-e4b | off | 0.462 | 12.434 | — | — | 100.0% (8/8) |
| raspi5 | no | B | gemma4-e4b | off | 0.473 | 8.303 | — | — | 100.0% (8/8) |
| raspi5 | no | B | gemma4-e4b | off | 0.44 | 5.19 | — | — | 100.0% (8/8) |
| raspi5 | no | B | gemma4-e4b | off | 0.738 | 8.864 | — | — | 100.0% (8/8) |
| raspi5 | no | B | gemma4-e4b | off | 0.924 | 12.622 | — | — | 87.5% (7/8) |
| raspi5 | no | B-mtp | gemma4-e2b | on | 0.221 | 2.331 | — | — | 100.0% (8/8) |
| raspi5 | no | B-mtp | gemma4-e4b | on | 0.428 | 4.912 | — | — | 100.0% (8/8) |
| raspi5 | no | B-mtp-think | gemma4-e2b | on | 11.615 | 13.682 | — | — | 100.0% (8/8) |
| raspi5 | no | B-mtp-think | gemma4-e4b | on | 20.518 | 29.399 | — | — | 100.0% (8/8) |
| raspi5 | no | B-think | gemma4-e2b | off | 23.802 | 28.283 | — | — | 100.0% (8/8) |
| raspi5 | no | B-think | gemma4-e4b | off | 44.347 | 63.176 | — | — | 100.0% (8/8) |
| raspi5 | no | E | gemma4-e2b | off | 24.195 | 26.16 | 25.775 | — | 50.0% (4/8) |
| raspi5 | no | E | gemma4-e2b | off | 29.51 | 29.51 | 29.51 | — | 50.0% (4/8) |
| raspi5 | no | E | gemma4-e4b | off | 57.785 | 60.235 | 60.055 | — | 87.5% (7/8) |
| raspi5 | no | E | gemma4-e4b | off | 54.17 | 54.17 | 54.17 | — | 87.5% (7/8) |
| raspi5 | no | E-mtp | gemma4-e2b | on | 23.68 | 23.68 | 23.68 | — | 50.0% (4/8) |
| raspi5 | no | E-mtp | gemma4-e4b | on | 40.68 | 40.68 | 40.68 | — | 100.0% (8/8) |
| raspi5 | no | E-mtp-think | gemma4-e2b | on | 45.07 | 51.05 | 49.04 | — | 100.0% (8/8) |
| raspi5 | no | E-mtp-think | gemma4-e4b | on | 88.02 | 94.1 | 92.54 | — | 100.0% (8/8) |
| raspi5 | no | E-think | gemma4-e2b | off | 51.46 | 59.36 | 57.12 | — | 100.0% (8/8) |
| raspi5 | no | E-think | gemma4-e4b | off | 107.34 | 109.32 | 108.77 | — | 100.0% (8/8) |

### T3 — Quantization sweep

| device | cond | model | quant | tok/s | TTFT | total | static acc | tool sel. |
|---|---|---|---|---|---|---|---|---|
| raspi5 | B | gemma4-e4b | Q4_K_M | — | 0.645 | 5.565 | 50.0% (4/8) | 0.0% (0/4) |
| raspi5 | A-cpu | gemma4-e2b | Q4_K_XL | 1.5 | 11.79 | 43.529 | 100.0% (4/4) | 0.0% (0/12) |
| raspi5 | B | gemma4-e2b | Q4_K_XL | — | 0.221 | 6.445 | 100.0% (8/8) | 0.0% (0/24) |
| raspi5 | D | gemma4-e2b | Q4_K_XL | — | 0.142 | 2.54 | 50.0% (4/8) | 100.0% (24/24) |
| raspi5 | E | gemma4-e2b | Q4_K_XL | — | 24.195 | 26.16 | 50.0% (4/8) | 83.3% (20/24) |
| raspi5 | A-cpu | gemma4-e4b | Q4_K_XL | 0.7 | 24.75 | 92.51 | 100.0% (4/4) | 0.0% (0/12) |
| raspi5 | B | gemma4-e4b | Q4_K_XL | — | 0.462 | 12.434 | 100.0% (8/8) | 0.0% (0/24) |
| raspi5 | D | gemma4-e4b | Q4_K_XL | — | 0.272 | 5.05 | 100.0% (8/8) | 100.0% (24/24) |
| raspi5 | E | gemma4-e4b | Q4_K_XL | — | 57.785 | 60.235 | 87.5% (7/8) | 100.0% (24/24) |
| raspi5 | B | gemma4-e2b | Q4_K_XL | — | 0.22 | 3.596 | 100.0% (8/8) | 0.0% (0/8) |
| raspi5 | B-mtp | gemma4-e2b | Q4_K_XL | — | 0.221 | 2.331 | 100.0% (8/8) | 0.0% (0/8) |
| raspi5 | B-think | gemma4-e2b | Q4_K_XL | — | 23.802 | 28.283 | 100.0% (8/8) | 0.0% (0/8) |
| raspi5 | B-mtp-think | gemma4-e2b | Q4_K_XL | — | 11.615 | 13.682 | 100.0% (8/8) | 0.0% (0/8) |
| raspi5 | E | gemma4-e2b | Q4_K_XL | — | 29.51 | 29.51 | 50.0% (4/8) | 100.0% (8/8) |
| raspi5 | E-mtp | gemma4-e2b | Q4_K_XL | — | 23.68 | 23.68 | 50.0% (4/8) | 100.0% (8/8) |
| raspi5 | E-think | gemma4-e2b | Q4_K_XL | — | 51.46 | 59.36 | 100.0% (8/8) | 100.0% (8/8) |
| raspi5 | E-mtp-think | gemma4-e2b | Q4_K_XL | — | 45.07 | 51.05 | 100.0% (8/8) | 100.0% (8/8) |
| raspi5 | B | gemma4-e4b | Q4_K_XL | — | 0.473 | 8.303 | 100.0% (8/8) | 0.0% (0/8) |
| raspi5 | B-mtp | gemma4-e4b | Q4_K_XL | — | 0.428 | 4.912 | 100.0% (8/8) | 0.0% (0/8) |
| raspi5 | B-think | gemma4-e4b | Q4_K_XL | — | 44.347 | 63.176 | 100.0% (8/8) | 0.0% (0/8) |
| raspi5 | B-mtp-think | gemma4-e4b | Q4_K_XL | — | 20.518 | 29.399 | 100.0% (8/8) | 0.0% (0/8) |
| raspi5 | E | gemma4-e4b | Q4_K_XL | — | 54.17 | 54.17 | 87.5% (7/8) | 100.0% (8/8) |
| raspi5 | E-mtp | gemma4-e4b | Q4_K_XL | — | 40.68 | 40.68 | 100.0% (8/8) | 100.0% (8/8) |
| raspi5 | E-think | gemma4-e4b | Q4_K_XL | — | 107.34 | 109.32 | 100.0% (8/8) | 100.0% (8/8) |
| raspi5 | E-mtp-think | gemma4-e4b | Q4_K_XL | — | 88.02 | 94.1 | 100.0% (8/8) | 100.0% (8/8) |
| raspi5 | B | gemma4-e4b | Q4_K_XL | — | 0.44 | 5.19 | 100.0% (8/8) | 0.0% (0/4) |
| raspi5 | C | gemma4-e4b | Q4_K_XL | — | 4.287 | 17.511 | 50.0% (4/8) | 0.0% (0/24) |
| raspi5 | B | gemma4-e4b | Q5_K_M | — | 0.738 | 8.864 | 100.0% (8/8) | 0.0% (0/4) |
| raspi5 | B | gemma4-e4b | Q8_0 | — | 0.924 | 12.622 | 87.5% (7/8) | 0.0% (0/4) |

_File size on disk and resident RSS are not captured automatically — record them by hand for this table._

### T4 — Classifier behaviour (condition E only)

`creative` calling no tool is a positive result: the classifier does not over-trigger. Per-category latency shows the tool tax is paid only where it is needed.

**raspi5 / E / gemma4-e2b Q4_K_XL**

| category | n | tool(s) called | tool correct | fabricated | total (warm med) |
|---|---|---|---|---|---|
| creative | 4 | none | n/a | 0 | 5.31 |
| currency | 4 | none | 0/4 | 0 | 2.89 |
| fixture | 4 | match_result | 4/4 | 0 | 37.39 |
| knowledge | 8 | none | n/a | 0 | 8.9 |
| match_result | 4 | match_result | 4/4 | 0 | 40.17 |
| news | 4 | web_search | 4/4 | 0 | 22.12 |
| race_result | 4 | f1_result | 4/4 | 0 | 36.89 |
| thinking | 4 | none | n/a | 0 | 29.07 |
| weather | 4 | weather_forecast | 4/4 | 0 | 40.26 |

**raspi5 / E / gemma4-e2b Q4_K_XL**

| category | n | tool(s) called | tool correct | fabricated | total (warm med) |
|---|---|---|---|---|---|
| creative | 4 | none | n/a | 0 | 5.36 |
| knowledge | 4 | none | n/a | 0 | 0.45 |
| match_result | 4 | match_result | 4/4 | 0 | 40.28 |
| thinking | 4 | none | n/a | 0 | 29.51 |
| weather | 4 | weather_forecast | 4/4 | 0 | 40.51 |

**raspi5 / E / gemma4-e4b Q4_K_XL**

| category | n | tool(s) called | tool correct | fabricated | total (warm med) |
|---|---|---|---|---|---|
| creative | 4 | none | n/a | 0 | 11.33 |
| currency | 4 | currency_rate | 4/4 | 0 | 68.15 |
| fixture | 4 | match_result | 4/4 | 0 | 65.54 |
| knowledge | 8 | none | n/a | 0 | 17.92 |
| match_result | 4 | match_result | 4/4 | 0 | 72.35 |
| news | 4 | web_search | 4/4 | 0 | 47.01 |
| race_result | 4 | f1_result | 4/4 | 0 | 66.94 |
| thinking | 4 | none | n/a | 0 | 54.82 |
| weather | 4 | weather_forecast | 4/4 | 0 | 69.86 |

**raspi5 / E / gemma4-e4b Q4_K_XL**

| category | n | tool(s) called | tool correct | fabricated | total (warm med) |
|---|---|---|---|---|---|
| creative | 4 | none | n/a | 0 | 11.09 |
| knowledge | 4 | none | n/a | 0 | 0.75 |
| match_result | 4 | match_result | 4/4 | 0 | 72.35 |
| thinking | 4 | none | n/a | 0 | 54.17 |
| weather | 4 | weather_forecast | 4/4 | 0 | 70.03 |

**raspi5 / E-mtp / gemma4-e2b Q4_K_XL**

| category | n | tool(s) called | tool correct | fabricated | total (warm med) |
|---|---|---|---|---|---|
| creative | 4 | none | n/a | 0 | 4.68 |
| knowledge | 4 | none | n/a | 0 | 0.53 |
| match_result | 4 | match_result | 4/4 | 0 | 39.36 |
| thinking | 4 | none | n/a | 0 | 23.68 |
| weather | 4 | weather_forecast | 4/4 | 0 | 39.54 |

**raspi5 / E-mtp / gemma4-e4b Q4_K_XL**

| category | n | tool(s) called | tool correct | fabricated | total (warm med) |
|---|---|---|---|---|---|
| creative | 4 | none | n/a | 0 | 9.25 |
| knowledge | 4 | none | n/a | 0 | 0.87 |
| match_result | 4 | match_result | 4/4 | 0 | 67.16 |
| thinking | 4 | none | n/a | 0 | 40.68 |
| weather | 4 | weather_forecast | 4/4 | 0 | 64.46 |

**raspi5 / E-mtp-think / gemma4-e2b Q4_K_XL**

| category | n | tool(s) called | tool correct | fabricated | total (warm med) |
|---|---|---|---|---|---|
| creative | 4 | none | n/a | 0 | 33.94 |
| knowledge | 4 | web_search | n/a | 0 | 30.06 |
| match_result | 4 | match_result | 4/4 | 0 | 52.88 |
| thinking | 4 | none | n/a | 0 | 56.15 |
| weather | 4 | weather_forecast | 4/4 | 0 | 51.05 |

**raspi5 / E-mtp-think / gemma4-e4b Q4_K_XL**

| category | n | tool(s) called | tool correct | fabricated | total (warm med) |
|---|---|---|---|---|---|
| creative | 4 | none | n/a | 0 | 58.52 |
| knowledge | 4 | none | n/a | 0 | 53.69 |
| match_result | 4 | match_result | 4/4 | 0 | 94.1 |
| thinking | 4 | none | n/a | 0 | 134.64 |
| weather | 4 | weather_forecast | 4/4 | 0 | 94.57 |

**raspi5 / E-think / gemma4-e2b Q4_K_XL**

| category | n | tool(s) called | tool correct | fabricated | total (warm med) |
|---|---|---|---|---|---|
| creative | 4 | none | n/a | 0 | 45.17 |
| knowledge | 4 | web_search | n/a | 0 | 33.29 |
| match_result | 4 | match_result | 4/4 | 0 | 72.25 |
| thinking | 4 | none | n/a | 0 | 101.7 |
| weather | 4 | weather_forecast | 4/4 | 0 | 59.36 |

**raspi5 / E-think / gemma4-e4b Q4_K_XL**

| category | n | tool(s) called | tool correct | fabricated | total (warm med) |
|---|---|---|---|---|---|
| creative | 4 | none | n/a | 0 | 90.38 |
| knowledge | 4 | web_search | n/a | 0 | 80.23 |
| match_result | 4 | match_result | 4/4 | 0 | 109.32 |
| thinking | 4 | none | n/a | 0 | 188.33 |
| weather | 4 | weather_forecast | 4/4 | 0 | 128.81 |

## 8. Where the data and the manuscript disagree

From `paper_tables.py --table issues`:

```
1. Table IV's 'llama.cpp n-gram, width 3' row (n3m2) never drafted.
   Requests whose llama-server log has a draft-acceptance line:
     mmlupro100-ngram-n3m2-e2b-s1           0/100
     mmlupro100-ngram-n3m3-e2b-s1         100/100
     mmlupro100-ngram-default-e2b-s1       94/100
   So its 100/100 'exact' is plain decoding and its +3% is day-to-day spread;
   it says nothing about whether width-3 drafting in llama.cpp is exact.
2. Runs from 2026-10-07 19:30 on had the Jetson's clocks pinned (jetson_clocks,
   RESULTS 7.7): CPU at its 1,497.6 MHz cap instead of scaling. The paper puts the
   cross-day energy band down to idle floor and temperature without naming it.
     run                                  started            CPU MHz idle W
     mmlupro100-e2b-s1                    20260922-002204        902   4.49
     mmlupro100-ae-full-e2b-s1            20261004-222749        870   4.55
     mmlupro100-ae-full-r2-e2b-s1         20261007-193003       1497   5.01
     mmlupro100-ae-reuse-e2b-s1           20261007-222454       1497   4.98
     mmlupro100-ngram-n3m3-e2b-s1         20261007-205641       1497   4.99
     mmlupro100-ngram-n3m2-e2b-s1         20261007-201101       1497   4.96
```
