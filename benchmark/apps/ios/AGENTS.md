# benchmark/apps/ios — the iPhone arm (GemmaBench)

Read this before changing anything here; the repo-wide rules are in `/AGENTS.md`.

## 0. Coding rule — always `/ponytail`

**Every coding session in this repo runs with `/ponytail` (full) active.** Invoke it
before writing code. Laziest solution that works: stdlib and platform first, no new
dependency for what a few lines do, fewest files, shortest diff, and mark deliberate
shortcuts with a `ponytail:` comment that names the ceiling and the upgrade path.
Never simplify away the measurement protocol below — that is the "explicitly requested"
part ponytail must not touch.

## 1. What this is

The iPhone arm of agentic-edge: the same
MMLU-Pro experiment it runs on the Raspberry Pi 5 and the Jetson Orin Nano, but run
**inside an iOS app** on MLX (Metal), so the three devices can be compared question for
question.

| | agentic-edge (Pi / Jetson) | here (iPhone) |
|---|---|---|
| models | `gemma-4-E{2,4}B-it-qat-UD-Q4_K_XL.gguf` | `mlx-community/gemma-4-E{2,4}B-it-qat-4bit` (same QAT checkpoint, MLX affine 4-bit g64, MLPs 8-bit) |
| engine | llama.cpp `llama-server` | mlx-swift-lm 3.31.4 / mlx-swift 0.31.4, `LLMModelFactory` (text-only) |
| task | lm-eval `mmlu_pro`, unmodified | the same chat messages, byte-identical (checked by `prep/build_prompts.py`) |
| subsets | s1/s2/s3, seeds 20260918/19/20, 100 q, stratified | the same ids, read from `findings/stdbench/` |
| decoding | greedy, `max_gen_toks` 2048, `until: ["Question:"]` | `temperature: 0` (ArgMaxSampler), `maxTokens` 2048, stop on `Question:` |
| thinking | `-rea off --reasoning-budget -1` | chat template `enable_thinking: false` |
| context | `-c 8192` | full KV cache (no `maxKVSize`), longest prompt 2,427 + 2,048 fits |
| scoring | `answer is \(?([ABCDEFGHIJ])\)?`, first match, exact match | `extractAnswer()` in `Bench.swift`, same regex |
| power | board DC draw (PMIC / INA3221) | no rails in-app: PowerLog battery V×I attached after the run (§3b), else battery-% **estimate** (§4.5) |

## 2. Layout

```
project.yml                 xcodegen spec -> GemmaBench.xcodeproj (generated; edit the yml, re-run xcodegen)
prep/build_prompts.py       builds GemmaBench/Resources/mmlupro.json (stdlib only)
prep/power_trace.py         sysdiagnose PowerLog or Power Profiler trace -> power.json the app imports (Mac, stdlib)
GemmaBench/App.swift        SwiftUI: pick model + subset, run one or the full grid
GemmaBench/Bench.swift      runner, scoring, every output file
GemmaBench/Models.swift     model store: pinned HF commits -> Application Support/models/, list/download/delete
GemmaBench/Telemetry.swift  1 Hz sampler (cpu, thermalState, battery, memory, MLX memory)
GemmaBench/RunDetail.swift  run drill-down, as agentic-edge dashboard RunDetail.js: Device tab
                            (cost tiles, request timeline, telemetry tracks, per-request table)
                            + Questions tab (filters, per-question stats, options, highlighted answer)
GemmaBench/Resources/mmlupro.json    300 prompts + Pi/Jetson reference scores
```

## 3. Running

```bash
# 1. prompts (reads findings/ from this repo: subset ids, s1 byte check, reference scores)
python3 prep/build_prompts.py
# 2. project
brew install xcodegen && xcodegen generate
open GemmaBench.xcodeproj    # set your Team, run on a real iPhone
```

In the app: pick E2B/E4B and s1/s2/s3 → **Run**, or **Run full grid** (6 runs, as in
agentic-edge §6).

**Models** ("Models on this iPhone" card): each model is a plain folder,
`Library/Application Support/models/<repo name>/`, holding one **pinned** Hugging Face commit
(`GemmaModel.revision`, recorded as `model_revision` in `meta.json`). "Downloaded" = every file
present at the size the Hub reports — a fact about the disk. Download resumes per file,
checks free space first, and is excluded from iCloud backup; a run that finds its model missing
downloads it **before** the idle baseline, so nothing measured includes the download. Bumping a
revision = a different model for the paper: say so. From the Mac:
`xcrun devicectl device process launch --device <id> com.mitlab.GemmaBench -- -downloadModels`
starts both downloads, and `xcrun devicectl device info files --device <id> --domain-type
appDataContainer --domain-identifier com.mitlab.GemmaBench --subdirectory "Library/Application Support/models"`
lists what's on the phone.

Results land in the app's Documents (Files → On My iPhone → GemmaBench, or Finder →
iPhone → Files), in the agentic-edge layout:

```
measured/mmlupro-<model>-<subset>-<stamp>/  meta.json  requests.csv  telemetry.csv  summary.json  run.json
stdbench/mmlupro100-<model>-<subset>/       results_<stamp>.json  samples_mmlu_pro_<subject>_<stamp>.jsonl
```

`comparison.md` (Documents root) is the iPhone vs Pi 5 vs Jetson table for the GitHub write-up —
latest complete run per model × subset plus the pooled n=300 row; rewritten after every run.
`run.json` is the app's own record (questions + timings + telemetry) that the in-app run
detail reads; rewritten after every question. `requests.csv` keeps agentic-edge's columns (plus `question_id,stop`); samples follow
lm-eval's `samples_*.jsonl` shape, so the repo's compare/export tooling can read them.

## 3a. Upload to the dashboard API

Each run is POSTed to the dashboard's `/api/phone` when it ends (and again from a run's
detail › "Re-upload", e.g. after attaching power data). The dashboard stores it on the Mac
(`dashboard/data/phone/`) and serves it as a third box, `iphone`, in `/api/history`,
`/api/baseline`, `/api/compare` and `/api/run` — see `dashboard/public/openapi.yaml`.
The body is `RunRecord.apiPayload()` (RunDetail.swift), deliberately in `run_detail.py --run`'s
shape so the dashboard's run sheet renders it unchanged; `questions[].question_id` is what
pairs iPhone answers with the boards' for McNemar.

In the app, Dashboard API card: the URL (default `https://edge-monitor.chaoticraccon.cloud`;
empty = never upload) and the dashboard's `API_TOKEN`, kept in the Keychain. A failed
upload is recorded on the run and shown in its header — retry from there. Plain `http://`
works only for LAN/Tailscale hosts (`NSAllowsLocalNetworking`).

## 3b. Measured power (optional, attach after the run)

iOS apps can't read power, so it's attached afterwards from an Apple source. Both go through
`prep/power_trace.py` → `<file>.power.json` → run detail › Device › power card › ↓. The app
matches it to the run by timestamp, stores it in `run.json`, writes
`measured/<run>/power_summary.json`, and rebuilds `comparison.md`.

**A. PowerLog — measured watts, works with Xcode 16 (primary).** Every sysdiagnose carries
iOS's powerlog database, where the battery fuel gauge logs voltage, instant current and
temperature. V × I = battery-side watts (whole phone incl. screen) — the closest iPhone
equivalent of the boards' DC draw, and it adds battery °C.
1. Run the benchmark **unplugged**. Right after it ends, trigger a sysdiagnose: hold both
   volume buttons + side button ~1 s (short vibration).
2. ~10 min later: Settings › Privacy & Security › Analytics & Improvements › Analytics Data ›
   `sysdiagnose_…tar.gz` → share to the Mac.
3. `python3 prep/power_trace.py --powerlog sysdiagnose_….tar.gz` (`--toc` lists the battery
   tables if it can't find one).
Caveats: undocumented format (tables matched by the `Voltage`/`InstantAmperage` columns);
samples are tens of seconds apart, so it gives whole-run energy (needs ≥ 3 samples inside
the run), not per-question. Discharge current is flipped to positive.

**B. Power Profiler — relative "power impact", needs Xcode 26's `xctrace`.** CPU/GPU/display/
network breakdown, not watts, so it never goes next to board Wh. Settings › Developer ›
Performance Trace → enable Power Profiler for GemmaBench, trace from Control Center while
running unplugged, then `python3 prep/power_trace.py <trace>`.

Energy precedence everywhere: PowerLog measured Wh > battery-% estimate (`*` in
`comparison.md`). `python3 prep/power_trace.py --demo` self-checks both parsers.

## 4. Rules that are easy to break

1. **Simulator can't run this.** MLX needs a real Apple-silicon GPU; this Mac is Intel.
   Build for a device.
2. **Xcode 16.4 pins.** mlx-swift-lm `main` needs swift-tools 6.2 and mlx-swift 0.31.5+
   needs 6.3. `project.yml` pins mlx-swift-lm **3.31.4** and mlx-swift **0.31.4**; bump
   them only together with Xcode 26. First open asks to **Trust & Enable** the
   `MLXHuggingFaceMacros` macro; CLI builds need `-skipMacroValidation`.
3. **Keep the app in the foreground.** iOS stops Metal work in the background; the app
   disables the idle timer during runs. A locked screen = a failed run.
4. **Memory.** E2B is ~4.3 GB on disk, E4B ~6.8 GB (includes vision/audio towers, which the
   text-only loader drops). The entitlements `increased-memory-limit` and
   `extended-virtual-addressing` are required; E4B on an 8 GB iPhone (15 Pro) may still be
   jetsam-killed — that is a result, record it, don't hide it.
5. **Every `n/a` gets a written reason.** iOS has no power rails, so `energy_wh`/`mean_w`/
   `j_per_token` stay null in `summary.json` with `na_reasons`. The comparison uses an
   **estimate** instead (`*_battery_est`): battery % used during the requests × battery
   capacity (Wh). It is whole-phone drain including the screen, at 1% resolution — never call
   it board DC draw. The capacity is the calibration knob in the app (nominal Wh × Battery
   Health %), saved per run; the nominal table in `Telemetry.swift` is from regulatory
   filings — verify it for your phone. Charging during a run voids the estimate (null).
   `thermal_max` (0 nominal … 3 critical) replaces temperature.
6. **Cold and warm latency separately** (`cold_total_ms`, `warm_median_total_ms`), never a
   mean. Model load is `load_s` in `meta.json`, outside request timing.
7. **Timing definitions.** `prompt_ms` = request start → first token (prefill + first
   sample). `gen_tok_s` = (gen_tokens − 1) / time after the first token. Close to, not
   identical to, llama.cpp's `timings`; say so when comparing.
8. **Report every run**, stopped and failed included — the app never deletes a run
   directory, and it appends each request as it finishes.
9. **Template parity check.** `summary.json → prompt_tokens_vs_pi` should be ~1.0. If it
   isn't, the MLX chat template or tokenizer differs from llama.cpp's and the comparison
   is suspect.
10. **A prompt change means rebuilding with `--ref`.** `build_prompts.py` refuses to write
    unless all 100 s1 prompts match lm-eval byte for byte.
