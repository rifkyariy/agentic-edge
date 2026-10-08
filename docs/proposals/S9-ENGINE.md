# S9: the proposed engine — little-gemma + three greedy-exact switches

**Status 2026-10-04:** built on the Jetson, quality gate passed (56/56 replies
byte-identical to S3), timing **on hold** until 15W is re-applied —
`nvpmodel.service` failed at the 17:22 boot (see the last section). S9 runs at
the recorded 15W caps so it compares with S1/S3 as they stand; no baseline is
re-run.

## Why an engine row at all

S3 showed little-gemma beats llama.cpp on the Orin Nano only through decode
(+11% E2B, +30% E4B; generated tokens identical, `findings/measured`), while
re-prefilling the whole 5-shot prompt per question — 433k prompt tokens where
llama.cpp's slot cache processed 114k. S9 asks how far the same engine goes
when the harness stops leaving speed on the table, **without touching quality**:
every switch must leave greedy output byte-identical, so accuracy is S3's by
construction and only cost is measured.

S9 is not a new engine from scratch. It is little-gemma at the S3 pin
(`aee759d` + `agentic-edge.patch`) plus `benchmark/little_gemma/ae.patch`,
built in its own tree (`AE=1 ./little_gemma/setup_jetson.sh` →
`~/build/little-gemma-ae`), so S3's binary is never rebuilt under it. The
kernels are untouched; all changes are host-side C in `run.c`, plus the
prefix-save buffers being allocated once.

## The switches

| switch | what | why it is exact |
|---|---|---|
| `-ngram` | **prompt-lookup drafting**: the tokens that followed the last earlier occurrence of the current 3-gram (else 2-gram) in prompt + reply are the draft | drafts go through little-gemma's MTP verify (`model_forward_spec`), which accepts only what greedy decoding would have produced |
| `-reuse` | **shared-prefix KV**: a prompt that misses the snapshot saves its KV up to its final user turn (system turn + few-shot block); the next prompt that starts with those tokens restores it — from a subject's 2nd question on, as llama-server's slot does. (The first version keyed on what two consecutive prompts shared, so it only restored from the 3rd question: 14 restores in the 3-per-subject gate, none in the 2-per-subject sweep.) | restore writes back the very rows the prefill wrote; SWA rings are saved whole, since they wrap during a reply |
| `-block N` | verify width (the `LG_MTP_N` knob) on the command line, so the fingerprint records it | width changes only how many tokens one pass may confirm |
| ~~`-mtp head`~~ | **not used.** Stock Gemma 4 draft head; it works through the same verify, but neither baseline ran speculative decoding (S1 no `draft-mtp`, S3 no `-mtp`), so S9 would be crediting itself with a feature the baselines left off. Measured at width 4 it was near break-even on E2B anyway (below) | — |

Ideas considered and not built: stopping at the first `answer is (X)` (lm-eval
takes the first match, so exact — but only **1.0%** of reply tokens follow it,
measured on S3 E2B); a certified-exact argmax that skips most of the 262k-row
output projection (≤10% of a token's weight traffic, needs a new kernel);
sm_87 kernel tuning (profile with nsys first); power mode (not an engine
change, and a system setting).

## Evidence so far

**Offline, before any code** — replaying S3's 300 recorded E2B replies (greedy
output is fixed, so acceptance is exact): prompt-lookup drafting gives
1.29 / 1.41 / 1.48 / 1.52 tokens per verify at width 2 / 3 / 4 / 5, drafting
on ~45% of steps. The 17 replies that hit the 2048 cap barely move it
(uncapped only: 1.39 at width 3).

**Gate** (`benchmark/ae_gate.py`, E2B, s1 questions in category order, replies
compared byte for byte with S3's):

| config | replies | identical |
|---|---|---|
| S9 binary, no switches | 14 (1 per category) | **14/14** |
| `-reuse -ngram -mtp … -block 4` (before MTP was dropped) | 42 (3 per category) | **42/42** |

The second covers snapshot save and restore (14 restores, 17,507 prompt tokens
skipped), n-gram verifies, MTP verifies and a capped reply.

**Gate timing, internal only** (both runs at the post-reboot clocks, so they
compare with each other, not with S3):

| E2B | tokens per pass | ms per pass | effective |
|---|---|---|---|
| plain decode | 1 | 24.3 | 41.2 tok/s |
| n-gram verify, width 4 | 2.31 | 40.3 | ~57 tok/s |
| MTP draft + verify, width 4 | 2.20 | 51.4 (13 drafting) | ~43 tok/s |
| whole decode, all switches | | | **49.0 tok/s (1.19×)** |

Reading: n-gram drafting delivers what the replay predicted; MTP at width 4 is
roughly break-even on E2B, because a width-4 verify costs 1.6× a decode step
and three chained drafts add 13 ms — which, with the fairness argument above,
is why S9 drops it. `full` is therefore `-reuse -ngram`. The width sweep
(2/3/4, per model, at 15W) decides the default.

## Width sweep at 15W (2026-10-04, queue jobs `ae-sweep-*`)

28 s1 questions per config (2 per subject), every reply byte-identical to S3
(224/224). Same boot, `clocks` precheck passed on all. With 2 per subject the
old reuse rule never restored, so these isolate the n-gram width.

| | E2B tok/s | E2B J/tok | E4B tok/s | E4B J/tok | +tok per verify (E2B/E4B) | verify cost vs a plain step |
|---|---|---|---|---|---|---|
| base | 25.63 | 0.451 | 15.39 | 0.879 | – | – |
| width 2 | 29.62 | 0.386 | 17.76 | 0.736 | 0.57 / 0.54 | 1.24× / 1.19× |
| **width 3** | **29.93** | **0.381** | **17.91** | **0.707** | 0.90 / 0.84 | 1.47× / 1.40× |
| width 4 | 28.81 | 0.393 | 17.63 | 0.713 | 1.12 / 1.04 | 1.76× / 1.60× |

Width 3 wins on both models, on time and energy: the default. Measured gain
per verify matches the offline replay within 0.03 tokens. A verify costs more
on the Orin Nano than little-gemma's journal reports for the NX (width 2:
~1.2× here, ~1.0× there), which is what caps width 4.

Base reproduces S3 (E2B 25.63 vs 25.58 tok/s over 300; E4B 15.39 vs 15.05),
so the sweep's clock state is S3's. Against the 300-question baselines:
E2B 1.30× llama.cpp's decode (23.00) and 1.17× little-gemma's; E4B 1.54× and
1.19×; energy per generated token −18% / −27% vs llama.cpp. ae-sweep-e2b-b0
and -b2 ended `failed`: exit 0, data valid, only the queue's `.done` marker
missing (ae_gate.py wrote none until 20:03).

For scale: llama.cpp and little-gemma agree byte for byte on only 12 of 100
E2B s1 replies (`ae_gate.py --diff`), with tied accuracy. A 100/100 match is
therefore no accident of the task; it is the engine changing nothing but speed.

## The clock problem

Every Jetson run on record (S1, S2, S3, S8, edge-grader; `telemetry.csv`
`gpu_mhz`, `cpu*_mhz`) ran at **GPU 612 MHz, CPU 1,497 MHz** — the caps
`/etc/nvpmodel.conf` declares for mode 0 (15W). At the 2026-10-04 17:22 boot
**`nvpmodel.service` failed** (exit 234), so the caps were never applied: the
GPU sat at its hardware default, max 1,020 MHz under the `performance`
governor, the CPU at 1,728 MHz. `nvpmodel -q` kept saying 15W because it reads
`/var/lib/nvpmodel/status`, last written on the previous boot (Oct 2). The S9
gate's 41 tok/s plain decode (S3: 25.6) is that, not the engine.

Fix: `sudo nvpmodel -m 0` (or `sudo systemctl restart nvpmodel`). Guard: the
queue now refuses any job whose live caps differ from its mode's declared ones
(`clocks` precheck, `jobqueue/prechecks.py`; not overridable; no-op on the Pi).

## Running it

```bash
AE=1 ./little_gemma/setup_jetson.sh          # build (~5 min)
./ae_gate.py --model e2b --flags "-ngram -block 3" \
    --against ~/research/stdbench/mmlupro100-lg-e2b-s1 --per-category 3
./queue_ctl.py --add '{"kind":"mmlupro-ae","params":{"model":"e2b","subset":"s1","variant":"full"}}'
```

Variants: `base`, `reuse`, `ngram`, `full` = `-reuse -ngram` (`std_mmlupro_lg_jetson.sh`);
fingerprint baselines `ae-*` require the `little-gemma-ae` build.
