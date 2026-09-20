# Agentic Edge — repository guide

Read this before changing anything. It covers what the repo is, where things
live, how to run them, and the handful of rules that are easy to break and
expensive to discover afterwards.

**The project:** agentic AI on edge devices. Gemma 4 **E2B** and **E4B** on a
**Raspberry Pi 5** (CPU and RAM only) and an **Nvidia Jetson Orin Nano**
(CUDA), measured against the standard runtimes **llama.cpp** and
**little-gemma**, plus an orchestration layer this project proposes. Accuracy
and device cost (power, thermals, utilisation) are measured in the same run.

**Paper 1 scope: text and reasoning parameters only.** Voice into Gemma's
multimodal path is paper 2 — keep audio results out of this one.

Deeper background: [`benchmark/EXPERIMENT_PLAN.md`](benchmark/EXPERIMENT_PLAN.md)
(protocol, statistical design, revisions results forced),
[`findings/RESULTS.md`](findings/RESULTS.md) (every number so far),
[`summary.md`](summary.md) (current state).

---

## 1. Layout

```
benchmark/          the harness (stdlib only on the devices, no pip needed)
  run_benchmark.py    own suite: device + condition + model -> results/*.json
  adapters.py         one adapter per engine (llama.cpp, little-gemma, proposed)
  pi5_run.sh          tiers 1-3 on the Pi, with per-condition server juggling
  report.py           tables T1-T4 from results/
  devices/*.json      per box: model paths, endpoints, cuda, power mode
  conditions/*.json   per condition: engine, offer_tools, mtp, thinking
  cases*.json         the 10-case suite and its reduced tiers

  mmlupro_subset.py   draws a seeded, stratified, disjoint MMLU-Pro subset
  std_mmlupro.sh      one MMLU-Pro run on the Pi (SUBSET=, THINKING=)
  std_mmlupro_jetson.sh  same, but launches a CUDA llama-server directly
  std_run.sh          tinyGSM8k; IFEval and BFCL wired but deferred

  run_measured.sh     wraps any run with idle baselines + telemetry
  telemetry.py        1Hz sampler: cpu/mhz/temp/throttle/mem/disk/rss/power/gpu
  parse_llama_log.py  per-request token timings (journal or --file)
  stamp.py            gives a raw server log journal-style timestamps
  summarize_run.py    energy, J/token, tok/s/W, thermals for one run
  probe_status.py     one-shot JSON status of a box (dashboard polls this)
  run_detail.py       one run's timeline + answers + per-request device stats
  build_viz.py        builds findings/viz/mmlupro_run.html

dashboard/          Next.js live monitor (runs on the Mac, not the devices)
  app/page.js         queue matrix, device cards, live charts
  app/RunDetail.js    drill-down sheet: timeline, device tracks, Q&A
  app/lib/plan.js     which runs exist, and run-name matching rules
  app/api/status      ssh -> probe_status.py on both boxes, every 5s
  app/api/run         ssh -> run_detail.py for one run

findings/           results and analysis (committed)
  RESULTS.md          the write-up of everything measured
  stdbench/           lm-eval results + per-question samples + subset ids
  measured/           telemetry.csv / requests.csv / summary.json per run
  viz/                static results page + its template
  early-engine-benchmarks/  raw Sep-14 engine comparison, rescued from the Pi

voice-agent/        the agent under test (condition E), deployed to the Pi
  services/           asr, llm, tts, orchestrator, tools, web
  systemd/, config/, deploy.sh
```

## 2. The two devices

| | Pi 5 | Jetson Orin Nano |
|---|---|---|
| ssh alias | `MITLAB-EDGE` (`mitlab@192.168.1.233`) | `MITLAB-JETSON` (`ari@mitlab-orin-nano`) |
| repo path | `~/Research/agentic-edge` | `~/research/agentic-edge` (symlink to `/mnt/ssd-ex`) |
| results root | `~/Research/{stdbench,measured}` | `~/research/{stdbench,measured}` |
| llama.cpp | `~/llama.cpp/build/bin` , systemd unit `va-llm` | `~/build/llama.cpp/build/bin`, **launched directly** |
| models | `~/models` | `~/research/models` (on the SSD) |
| eval venv | `~/Research/eval-venv` | `~/venvs/eval` |
| power source | PMIC rails via `vcgencmd pmic_read_adc` | INA3221 hwmon: `VDD_IN` total, plus CPU+GPU and SOC |
| sudo | passwordless | **password required** — no apt installs |

Case matters: `~/Research` on the Pi, `~/research` on the Jetson. Scripts
detect this; keep it that way rather than hardcoding one.

## 3. Running things

```bash
# accuracy + device cost, one run (Pi)
ssh MITLAB-EDGE
cd ~/Research/agentic-edge/benchmark
./run_measured.sh mmlupro-e2b-s1 -- env SUBSET=s1 ./std_mmlupro.sh e2b

# same on the Jetson (SRVLOG lets the wrapper find the server log)
ssh MITLAB-JETSON
cd ~/research/agentic-edge/benchmark
SRVLOG=~/research/stdbench/mmlupro100-e2b-s1/server.log SUBSET=s1 \
  ./run_measured.sh mmlupro-e2b-s1 -- env SUBSET=s1 ./std_mmlupro_jetson.sh e2b

# the own suite (architectures, MTP x thinking, quant sweep)
./pi5_run.sh tier1 ; python3 report.py t1

# dashboard, on the Mac
cd dashboard && npm install && npm run dev     # http://localhost:3939

# rebuild the static results page from whatever data is on disk
python3 benchmark/build_viz.py
```

A measured run writes `<results root>/measured/<label>-<stamp>/` with
`telemetry.csv`, `requests.csv`, `meta.json`, `summary.json`, `command.log`.
lm-eval writes `<results root>/stdbench/<run>/` with its results and
per-question samples.

## 4. Rules that are easy to break

1. **Never `scp` over a script a device is currently running.** Bash re-reads
   the file mid-execution and dies at a shifted offset. This already cost one
   run its `requests.csv` and `summary.json` (both rebuilt from the journal).
   Write to a new name, or wait.
2. **`pkill -f "<pattern>"` over ssh matches the ssh command itself** and kills
   your own shell. Use `pgrep -f "[p]attern"`, or kill by pid.
3. **`--cache-ram 0` on llama.cpp** for any run with many distinct prompts. The
   default host prompt cache is 8192 MiB, more than either board has, and the
   server gets OOM-killed mid-run.
4. **`-c 8192` for MMLU-Pro.** The longest subset prompt is 2,427 tokens and the
   answer budget is 2,048; the deployed 4,096 truncates.
5. **Set generation limits explicitly.** lm-eval's default `max_gen_toks` is 256
   and silently truncates chain-of-thought — it understated E2B on GSM8K by
   ~15 points.
6. **The Pi's model switch goes through va-web's `/model`**, which rewrites
   `VA_LLM_SPEC_ARGS`; setting flags directly in `runtime.env` and restarting
   `va-llm` is the way to keep `--cache-ram 0` and `-c 8192`.
7. **Restore what you change.** The run scripts put `runtime.env` back to the
   deployed defaults; keep that property.
8. **`va-*` services are not enabled at boot.** After a reboot:
   `sudo systemctl start va-llm va-asr va-tts va-orchestrator va-web`.
9. **One job per device.** Both boards are single-resource; a second concurrent
   run invalidates the telemetry of both.

## 5. Methodology invariants

These are not preferences — breaking them invalidates the paper.

- **Both devices must run the identical question subsets** (`s1`/`s2`/`s3`,
  seeds 20260918/19/20, disjoint, ids committed in `findings/stdbench/`) with
  the identical task config. Only the device differs.
- **Report every run, including failures and superseded ones.** No quiet
  replacement of a bad run with a good one.
- **Greedy decoding**, so repeats of the same questions measure only ~1 point of
  implementation noise. Uncertainty comes from question sampling: ±9.7 at
  n=100, ±5.6 pooled at n=300. More questions beat more repeats.
- **Cold and warm latency separately**, never a mean across repeats.
- **Every `n/a` gets a written reason.**
- **A metric change means rescoring every run with it**, not mixing rules.
- **Power is board DC draw** (PMIC / INA3221), excluding PSU conversion loss.
  Same method on both boards, so the comparison holds — but never call it wall
  power.

## 6. State as of 2026-09-21

Done: Pi tiers 1-3, MTP × thinking, quant sweep, MMLU-Pro s1 both models,
tinyGSM8k, the live-answer and classifier audits, Jetson setup (CUDA llama.cpp
for sm_87, models on the SSD, eval venv, telemetry with GPU).

Running: Pi and Jetson each working through MMLU-Pro s1/s2/s3 × E2B/E4B with
telemetry.

Not started: capability (b) standard benchmark — IFEval and BFCL are installed
but unrun, so tool calling currently rests on the custom 10-case suite;
capability (c) safety and security — no benchmark chosen (candidates: XSTest,
SimpleSafetyTests, AgentDojo); thinking-on MMLU-Pro rows; the manuscript.

Dropped: LiteRT-LM (condition C) entirely; the deployed-prompt MMLU-Pro row;
further GSM8K runs (its results stay as a methodological appendix).

## 7. If you add a feature

- Device-side scripts are **stdlib-only Python or POSIX-ish bash** — the boards
  have no pip access worth relying on (the Jetson has no passwordless sudo and
  no `python3-venv`; its venvs are bootstrapped with `get-pip.py`).
- Anything the dashboard needs from a device should go through
  `probe_status.py` (fast, polled) or `run_detail.py` (heavier, on demand),
  not a new ad-hoc ssh command in the web app.
- New metrics belong in `telemetry.py` as columns; `summarize_run.py` and
  `build_viz.py` read by column name, so adding one is safe.
- Test on **both** boards. Several bugs were board-specific: `~/Research` vs
  `~/research`, PMIC vs INA3221, journal vs file logs, `"N/A"` strings from
  lm-eval where a float was expected.
