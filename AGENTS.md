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

  queue_runner.py     the job queue daemon; one per board, a systemd user unit
  queue_ctl.py        the only thing the dashboard runs over ssh (JSON in/out)
  jobqueue/           paths, store, events, kinds, prechecks, fingerprint, runner
  job_kinds.json      what can be queued, and what it resolves to per board
  baselines.json      expected serving flags per condition, for the fingerprint
  install_queue.sh    installs and starts the unit (run it on the board)
  tests/              stdlib unittest; `python3 -m unittest discover -s tests`

dashboard/          Next.js live monitor (runs on the Mac, not the devices)
  app/page.js         queue matrix, device cards, live charts
  app/RunDetail.js    drill-down sheet: device tab + questions tab
  app/Charts.js       every chart (recharts): live metric, telemetry track, timeline
  app/lib/plan.js     which runs exist, and run-name matching rules
  app/lib/hosts.js    the two boxes, overridable from .env.local
  app/api/status      ssh -> probe_status.py on both boxes, every 5s
  app/api/run         ssh -> run_detail.py for one run
  app/queue/          queue a run, see its prechecks, follow its logs
  app/api/queue       ssh -> queue_ctl.py: status, preflight, add, cancel
  app/api/logs        ssh -> queue_ctl.py --log, offset-based tailing
  scripts/check-ssh.mjs  `npm run check` — preflight before a fresh clone runs

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

# queue a run instead of launching it by hand (survives the Mac sleeping)
ssh MITLAB-JETSON
cd ~/research/agentic-edge/benchmark
./queue_ctl.py --preflight '{"kind":"mmlupro","params":{"model":"e4b","subset":"s2"}}'
./queue_ctl.py --add       '{"kind":"mmlupro","params":{"model":"e4b","subset":"s2"}}'
./queue_ctl.py --status
# or do all of that at http://localhost:3939/queue

# dashboard, on the Mac
cd dashboard && npm install
npm run check      # can this Mac ssh to both boards? fix anything it flags
npm run dev        # http://localhost:3939

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
10. **Diff the actual `llama-server` command line between boards before
   trusting a cross-device comparison.** The Pi reaches it through va-llm and
   `runtime.env`, the Jetson launches it directly, so the two drift apart
   silently. `ps -o args= -C llama-server` on each is the check; a difference
   there invalidates the comparison no matter how clean the harness looks.

   **Do this while the run is live — `meta.json` cannot answer it** (verified
   2026-09-22). `run_measured.sh` writes `meta.json` *before* it starts the
   wrapped command, but it is the run script that then restarts va-llm, or
   launches the Jetson's server, with the run's real settings. So
   `server_args` records whatever was running beforehand:
   - On the Pi it is the idle deployed server. Four of six archived MMLU-Pro
     runs name the *wrong model*, and all six say `-c 4096` although the run
     itself sets `8192`.
   - On the Jetson it is empty for all nine runs — the previous run's `pkill`
     left nothing to sample.

   This is why the missing `-rea` survived days of review: the audit trail
   AGENTS relies on was blank at exactly the moment it mattered.

   **`run_measured.sh` now takes a second sample**, once the run's own server
   is serving, under `server_args_after`. That is the honest field; read it,
   not `server_args`, which is kept only so nothing already parsing it
   changes meaning. Runs archived before 2026-09-22 have no
   `server_args_after` at all — for those, treat `server_args` as evidence of
   nothing. A queued run also records the same capture, diffed against
   `baselines.json`, in `<results root>/queue/jobs/<id>/fingerprint.json`.

   **The runs themselves are fine** — it is the record that lied. The Pi's
   journal shows both servers on either side of one capture:

   ```
   Sep 21 20:48:28  llama-server  n_ctx_slot = 4096   idle server, sampled into meta.json
   Sep 21 20:50:04  llama-server  n_ctx_slot = 8192   the restart std_mmlupro.sh performs
   ```

   The run served `8192` as rule 4 requires. Use the journal
   (`journalctl -u va-llm`) as the Pi's real check until the capture is fixed;
   note it only covers the current boot.
11. **Never `next build` in `dashboard/` while `npm run dev` is running.** The
   build wipes `.next` under the dev server and every request 500s until it is
   restarted. Stop the dev server first, or just don't build — dev compiles.

## 5. Methodology invariants

These are not preferences — breaking them invalidates the paper.

- **Both devices must run the identical question subsets** (`s1`/`s2`/`s3`,
  seeds 20260918/19/20, disjoint, ids committed in `findings/stdbench/`) with
  the identical task config. Only the device differs.
- **The baseline serves with `-rea off --reasoning-budget -1`** on both boards.
  These are **two different flags**, and an earlier version of this section had
  them confused — verified 2026-09-22 against `llama-server --help` on both
  boards (Pi build `661643e`, Jetson `a894dae`):

  | flag | what it does | default |
  |---|---|---|
  | `-rea`, `--reasoning [on\|off\|auto]` | **the thinking switch itself** | `auto` — detect from template |
  | `--reasoning-format none\|deepseek\|deepseek-legacy` | where the thoughts go: `none` leaves them inline in `message.content`, `deepseek` moves them to `message.reasoning_content` | `auto` |
  | `--reasoning-budget N` | token budget for thinking; `-1` unrestricted | `-1` |

  So `-rea off` means the model **does not think**, and the baseline is a
  genuine no-chain-of-thought condition — not, as previously written here, a
  thinking model whose thoughts are merely displayed inline. `--reasoning-budget
  -1` is already llama.cpp's default; it is passed explicitly so the resolved
  command line records it.

  Omitting `-rea` is what cost the Jetson: it falls back to `auto`, Gemma's
  template turns thinking **on**, and the default `--reasoning-format auto` then
  files the thoughts under `reasoning_content`, which lm-eval never reads. Every
  Jetson run before 2026-09-22 lost its answer that way — median response 993
  characters against the Pi's 1,880, and 11 of 100 completely empty.

  The thinking-on row is a *separate* condition (`THINKING=on`, budget 320). It
  sets `-rea on` **and must pin `--reasoning-format none`**, or the thoughts
  vanish into `reasoning_content` exactly as above. Both run scripts already do
  this correctly.
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

## 6. State as of 2026-09-22

Done: Pi tiers 1-3, MTP × thinking, quant sweep, tinyGSM8k, the live-answer and
classifier audits, Jetson setup (CUDA llama.cpp for sm_87, models on the SSD,
eval venv, telemetry with GPU), and **the full MMLU-Pro baseline grid — s1/s2/s3
× E2B/E4B on both boards with telemetry**, all on matched serving flags.

Baseline headline (n=300 per model, paired over the same questions): E2B Pi
51.7% vs Jetson 52.7%, E4B Pi 65.7% vs Jetson 66.0% — tied on both (McNemar
p = 0.76 and 1.00). The Jetson is ~3.4× faster at decode and ~2.4× cheaper per
token while drawing ~1.5× the power. The boards pick the same answer letter on
only 71% (E2B) / 85% (E4B) of questions despite greedy decoding; see
`findings/RESULTS.md` §7.1.

Running: nothing.

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
