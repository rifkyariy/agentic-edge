# iPhone arm — MMLU-Pro on iPhone 15 Pro (iPhone16,1, iOS 26.6, MLX)

Every run the GemmaBench app (`benchmark/apps/ios`) uploaded to the dashboard's `/api/phone`,
archived from `dashboard/data/phone/` (git-ignored on the Mac). One gzipped JSON per run, in
`run_detail.py --run`'s shape: per-question answers (`questions[].question_id` pairs with the
boards), per-request timeline, 1 Hz telemetry, device summary. Nothing is left out: stopped runs
stay as their last live snapshot (AGENTS §5). To serve them again, gunzip into `dashboard/data/phone/`.

## Result (current run per cell, greedy, thinking off, n=300 per model)

| model | s1 | s2 | s3 | pooled |
|---|---|---|---|---|
| E2B (`mlx`) | 51 | 47 | 55 | **51.0%** (153/300) |
| E4B (`mlx-oq4`) | 65 | 64 | 69 | **66.0%** (198/300) |

Boards, same subsets (AGENTS §6): E2B Pi 51.7% / Jetson 52.7%, E4B Pi 65.7% / Jetson 66.0%.
Paired tests against the boards: the dashboard's /compare (per-question, from these files).

## Not like-for-like with the boards — read before comparing

- **Engine and weights differ.** The boards run llama.cpp / little-gemma on the same
  `gemma-4-E*B-it-qat-UD-Q4_K_XL.gguf`; the iPhone runs MLX 4-bit builds of the same QAT models:
  E4B `mlx-community/unsloth-gemma-4-E4B-it-qat-oQ4` (`engine: mlx-oq4`, recorded in each file),
  E2B `gemma-4-E2B-it-qat-4bit` (`engine: mlx`; these records predate `model_repo`, the name is
  from the app's commit 67d21cb). Same prompts and subsets, different quantisation and kernels.
- **Energy is not board DC draw.** It is a whole-phone battery estimate (`energy_source`:
  battery % × capacity, screen included, 1 % steps), so never compare it to the PMIC / INA3221
  figures as equals. Early runs have none (`energy_source: none`).
- **Heavy thermal throttling.** iOS thermal state reached 3 (critical) on most runs, and the
  throttled column is minutes at state ≥ 2 (serious). Decode speed is the throttled speed.
- `—` = not recorded: no energy estimate on those runs (see `na_reasons` in each file).

## Every upload

| run | model | subset | status | correct/answered | min | decode tok/s | energy Wh (est.) | mean W (est.) | J/token (est.) | thermal max | throttled min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `mmlupro-e2b-s1-20261002-222849` | e2b | s1 | done | 51/100 | 97 | 12.4 | — | — | — | 3 | 89 |
| `mmlupro-e2b-s1-20261003-002005` | e2b | s1 | stopped (last live snapshot) | 10/20 | 17 | 15.0 | 1.90 | 6.56 | 0.467 | 2 | 14 |
| `mmlupro-e2b-s1-20261003-150850` | e2b | s1 | done **(current)** | 51/100 | 84 | 14.0 | 6.35 | 4.53 | 0.347 | 2 | 74 |
| `mmlupro-e2b-s2-20261003-212509` | e2b | s2 | stopped (last live snapshot) | 22/40 | 44 | 14.5 | 3.68 | 5.08 | 0.373 | 3 | 32 |
| `mmlupro-e2b-s2-20261003-233936` | e2b | s2 | done **(current)** | 47/100 | 86 | 14.6 | 6.98 | 4.90 | 0.361 | 3 | 69 |
| `mmlupro-e2b-s3-20261004-115841` | e2b | s3 | done **(current)** | 55/100 | 90 | 14.2 | 6.99 | 4.66 | 0.353 | 3 | 78 |
| `mmlupro-e4b-oq4-s1-20261004-210658` | e4b-oq4 | s1 | stopped (last live snapshot) | 7/10 | 10 | 10.4 | — | — | — | 2 | 7 |
| `mmlupro-e4b-oq4-s1-20261004-211929` | e4b-oq4 | s1 | done **(current)** | 65/100 | 142 | 9.2 | 11.43 | 4.83 | 0.598 | 3 | 137 |
| `mmlupro-e4b-oq4-s2-20261005-112446` | e4b-oq4 | s2 | done **(current)** | 64/100 | 143 | 8.9 | 11.43 | 4.79 | 0.598 | 3 | 131 |
| `mmlupro-e4b-oq4-s3-20261005-152451` | e4b-oq4 | s3 | done **(current)** | 69/100 | 136 | 9.4 | 10.79 | 4.78 | 0.582 | 3 | 124 |

Two complete E2B s1 runs (both 51/100): the later one is current, it is the one with an energy
estimate. The four stopped runs were cut short on the phone; their final upload never happened, so
what is here is the last `status: running` snapshot.
