# Every experiment that ran

One row per experiment actually carried out, whether or not the manuscript
uses it. Nothing here is a plan: conditions that were proposed and never run
(S5 cascade, S6 encoder router, S7 precision control, IFEval/BFCL as a
benchmark, a safety benchmark) have been removed from the repository; they are
in git history before 2026-10-13 if ever needed.

**Fixed on every MMLU-Pro row:** three disjoint, seeded, stratified
100-question subsets (`s1`/`s2`/`s3`, seeds 20260918/19/20, ids in
`findings/stdbench/`), lm-eval `mmlu_pro` 5-shot chain of thought, greedy,
2,048-token answer cap, 8,192 context, the same Gemma 4 QAT `UD-Q4_K_XL` GGUF
per model. One run = one device × one model × one subset. A condition is
complete at 6 runs per device (n=300 per model).

## Used in the manuscript

| condition | what | device | runs | paper | write-up | data in the repo |
|---|---|---|---|---|---|---|
| **S1** | llama.cpp baseline, thinking off (`-rea off`) | Jetson | 6 | Tables I, III, IV; §VI | RESULTS §7.1 | `findings/runs/jetson/mmlupro100-<m>-<s>/` |
| **S1** | the same, on the Pi | Pi 5 | 6 | Table VIII; Table VII; §VII | RESULTS §7.1 | `findings/runs/pi/mmlupro100-<m>-<s>/`; also `findings/export/` |
| **S3** | little-gemma, stock engine (+ `agentic-edge.patch` for raw prompts) | Jetson | 6 | Tables I, III, V | RESULTS §7.4 | `findings/runs/jetson/mmlupro100-lg-*` |
| **S9 / CoPR** | little-gemma + `ae.patch`: `full` = `-reuse -ngram -block 3` | Jetson | 6 + 1 repeat | Tables III, IV, V; §V repeat | RESULTS §7.6 | `findings/runs/jetson/mmlupro100-ae-full-*` |
| **S9 ablation** | `-ngram -block 3` alone; `-reuse` alone | Jetson | 6 + 6 | Table V | RESULTS §7.6 | `…/mmlupro100-ae-ngram-*`, `…/mmlupro100-ae-reuse-*` |
| **S9 failed** | the first six `-reuse` runs, dead at startup (shim flag parsing) | Jetson | 6 | §VI-D | RESULTS §7.6 | `findings/runs/jetson/failed/` |
| **S9 width sweep** | `ae_gate.py`, 28 s1 questions, widths none/2/3/4 | Jetson | 8 + 2 repeats | Table VI | RESULTS §7.6 | `findings/runs/jetson/ae-sweep-*` |
| **S10** | llama.cpp's own n-gram drafting, `n3m3` (width 4) | Jetson | 6 | Tables III, IV; §VI-C | RESULTS §7.8 | `findings/runs/jetson/mmlupro100-ngram-n3m3-*` |
| **S10 settings** | `n3m2` (width 3, matched to CoPR) and stock settings, s1 | Jetson | 2 | Table IV | RESULTS §7.8 | `…/mmlupro100-ngram-n3m2-e2b-s1`, `…-default-e2b-s1` |
| **iPhone** | MLX 4-bit builds of the same QAT checkpoints | iPhone 15 Pro | 6 + 4 superseded/stopped | Table VIII | RESULTS §7.3 | `findings/phone/` |
| **S2** | llama.cpp, thinking on (`-rea on`, budget 320) | Pi 5 | 6 | Table VII (replies replayed) | RESULTS §7.2 | `findings/runs/pi/mmlupro100-<m>-<s>-think/` |
| **tinyGSM8k** | E2B at 256 and 1,024 answer tokens | Pi 5 | 2 | Table VII (200 replies replayed) | RESULTS §1 | `findings/stdbench/B-e2b/`, `findings/stdbench/tiny1024-e2b/` |
| **replay** | prompt-lookup acceptance replayed on recorded replies (`replay_lookup.py`, Pi tokenizer) | Pi 5 | 3 | Table VII; §III; §VII | — | `findings/runs/pi/replay-lookup-pi/`, `…/replay-lookup-lg-e2b/` (run 2026-10-21 on the committed little-gemma replies) |
| **Pi batch cost** | llama.cpp CPU cost of a 1–4 token batch (`llama-bench`) | Pi 5 | 1 | §VII | — | `findings/runs/pi/pi-verify-cost-e2b/` |

Every row with data in the repo is rebuilt and checked against the manuscript
by `python3 benchmark/paper_tables.py`, and laid out as tables in
[`../findings/TABLES.md`](../findings/TABLES.md).

## Run, reported, not used in the manuscript

| condition | what | device | runs | write-up | data |
|---|---|---|---|---|---|
| **Own suite, tiers 1–3** | architectures A/B/C/D/E × E2B/E4B, MTP × thinking, E4B quant sweep (10-case suite) | Pi 5 | 29 | RESULTS §2–§4 | `benchmark/results/*.json` |
| **Audits** | live-answer fabrication audit (62 answers), intent classifier on BFCL prompts | Pi 5 | — | RESULTS §2 | `benchmark/live_audit.json`, `findings/audits/` |
| **tinyGSM8k E4B** | E4B at 256 answer tokens | Pi 5 | 1 | RESULTS §1 | `findings/stdbench/B-e4b/` |
| **S2** | llama.cpp, thinking on | Jetson | 6 | RESULTS §7.2 | on the Jetson |
| **S3t** | little-gemma, thinking on | Jetson | 6 | RESULTS §7.2, §7.4 | on the Jetson |
| **S4** | letter-only answers, no chain of thought | Pi 5 | 3 (E2B) | `findings/analyses/s4-letter-only.md` | on the Pi |
| **S4 rotations** | letter-only with option orders rotated, for the permutation ensemble | Pi 5 | E2B, rotations r0/r2/r4/r6 × 3 subsets, r8 on s1 | `findings/analyses/permutation-ensemble.md` | on the Pi |
| **Model cascade** | E2B→E4B cascade scored offline from S1 | offline | — | `findings/analyses/model-cascade.md` | `findings/export/` |
| **Iso-accuracy** | budget capping and loop detection scored offline | offline | — | `findings/analyses/iso-accuracy.md` | `findings/export/` |
| **S8** | llama.cpp TurboQuant fork, `-ctk turbo3 -ctv turbo3`, thinking off and on | Pi 5 + Jetson | 24 | RESULTS §7.5 | on the boards |
| **Agent prompts** | IFEval and BFCL prompts replayed through llama.cpp, little-gemma and CoPR, for replies only (not scored) | Jetson | 4 | — | on the Jetson; their prompt-lookup replays (and BFCL's reference answers) are in `findings/runs/pi/replay-*` |
| **Early engines** | little-gemma vs llama.cpp vs LiteRT-LM on one Pi, Sep 14 | Pi 5 | — | `findings/early-engine-benchmarks/README.md` | same folder |
| **Superseded / failed** | the Jetson's S1 runs before `-rea off` (2026-09-22), LiteRT-LM (condition C) | both | — | RESULTS §7.1; §2 | on the boards (`stdbench/failed/`), `benchmark/results/` |

"On the board" means the run's samples and telemetry are still only in that
board's results root (`~/Research` on the Pi, `~/research` on the Jetson). To
bring any of them into the repo:

```bash
python3 benchmark/collect_runs.py --board jetson --from MITLAB-JETSON:research <run> ...
```
