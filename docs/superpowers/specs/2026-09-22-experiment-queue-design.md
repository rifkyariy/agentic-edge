# Experiment queue, config UI and run logging — design

**Date:** 2026-09-22
**Status:** approved design, not yet implemented
**Scope:** a device-side job queue for the Pi 5 and Jetson Orin Nano, a
configuration UI in the dashboard that feeds it, and per-job logging that
catches both loud failures (crashes, OOM kills) and silent ones (a run that
completes but is methodologically invalid).

Related: [`AGENTS.md`](../../../AGENTS.md) §3 (running things), §4 (rules),
§5 (methodology invariants), §7 (adding a feature), §9 (one job per device),
§10 (diff the server command line).

---

## 1. Problem

Every benchmark run today is launched by hand over ssh. Three costs follow
from that.

**Runs are tied to a laptop.** A run takes two to three hours. Launching it
from the dashboard with a plain `ssh board ./queue_jetson.sh` would kill it
the moment the Mac sleeps or the Wi-Fi drops.

**Failures are found late.** `mmlupro100-e4b-s2` was OOM-killed at question 94
after 2h39m. `queue_jetson.sh` now guards that specific case with a
free-memory precheck, but the guard lives in one script and covers one
benchmark.

**Some failures are silent.** Every Jetson MMLU-Pro run before 2026-09-22
served without the reasoning flags the Pi used. The runs completed, wrote
plausible scores, and were invalid: median response 993 characters against
the Pi's 1,880, and 11 of 100 answers completely empty. Nothing in the harness
noticed; it was caught by reading answers days later. AGENTS §10 prescribes
the check — diff `ps -o args= -C llama-server` between boards — but it is
manual and therefore skipped.

A queue that only started and stopped jobs would fix the first two. The third
is the expensive one, so the fingerprint check in §5 is part of the same
design rather than a later addition.

## 2. Architecture

The queue lives on each board and owns execution. The dashboard is a client:
it composes jobs, reads state, and tails logs. It never executes a benchmark
itself.

```
Mac (dashboard)                     Board (Pi 5 / Jetson Orin Nano)

  POST /api/queue  ──ssh──▶  queue_ctl.py --add ──▶ queue.json
  GET  /api/queue  ──ssh──▶  queue_ctl.py --status
  GET  /api/logs   ──ssh──▶  queue_ctl.py --log                │
                                                                ▼
                                       queue_runner.py  (daemon, one job at a time)
                                         ├ precheck    memory, stale dir, subset ids
                                         ├ fingerprint resolved server argv vs baseline
                                         │   └ drift → refuse, or recorded override
                                         ├ exec        run_measured.sh <label> -- <cmd>
                                         ├ progress    tail lm_eval.log → events.jsonl
                                         └ outcome     .done marker, not exit status
```

This follows AGENTS §7: work the dashboard needs from a device goes through a
device-side script, not an ad-hoc ssh command in the web app. `probe_status.py`
and `run_detail.py` keep their current roles; `queue_ctl.py` is the third such
entry point and the only one that mutates state.

### Why device-side

The daemon owns the queue file, so "one job per device" (AGENTS §9) stops
being a rule to remember and becomes a property of a single-threaded loop.
Runs survive the Mac sleeping. And there is exactly one answer to "what is
running on this board", which today is inferred on the Mac from process names
(see §6).

## 3. On-device layout

Under the board's results root (`~/Research` on the Pi, `~/research` on the
Jetson — the case difference is detected, never hardcoded):

```
queue/
  queue.json        job list; atomic write (temp + rename), flock while mutating
  events.jsonl      append-only, every transition of every job
  runner.pid        liveness, for the watchdog and check-ssh.mjs
  jobs/<job_id>/
    job.json        the resolved job: kind, params, label, command, timestamps
    precheck.json   each check, its measured value, pass or fail
    fingerprint.json  captured server argv, model path, governor, subset hash
    events.jsonl    this job's slice, for cheap per-job reads
```

Logs are not copied here. `job.json` points at the run's real outputs —
`<measured root>/<label>-<stamp>/command.log`, `<stdbench>/<run>/lm_eval.log`,
and on the Jetson `<stdbench>/<run>/server.log` — and `queue_ctl.py --log`
reads them in place.

### Job lifecycle

```
queued ──▶ prechecking ──▶ fingerprinting ──▶ running ──▶ completed
   │            │                │               │
   │            ▼                ▼               ▼
   └──▶ cancelled           blocked           failed
```

`blocked` is a precheck or fingerprint refusal. It is distinct from `failed`:
nothing ran, so nothing was wasted, and the job can be released with an
override or fixed and requeued.

## 4. Job kinds

`benchmark/job_kinds.json` declares each kind: its parameters and their
allowed values, a label template, an output-directory template, and per-board
command templates. The dashboard renders its form from this file, fetched from
the device via `queue_ctl.py --describe`, so there is one source of truth and
no drift between what the UI offers and what the daemon will run.

Shipping in the first version:

**`mmlupro`** — parameters `model` ∈ {e2b, e4b}, `subset` ∈ {s1, s2, s3},
`thinking` ∈ {off, on}. Resolves to the invocation AGENTS §3 documents:

```sh
# Pi
./run_measured.sh mmlupro-<model>-<subset> \
  -- env SUBSET=<subset> THINKING=<thinking> ./std_mmlupro.sh <model>

# Jetson — SRVLOG lets run_measured.sh find the directly-launched server's log
SRVLOG=~/research/stdbench/<output-dir>/server.log \
SUBSET=<subset> ./run_measured.sh mmlupro-<model>-<subset> \
  -- env SUBSET=<subset> THINKING=<thinking> ./std_mmlupro_jetson.sh <model>
```

`SRVLOG` must be built from the *output-directory* template, not the label:
`std_mmlupro_jetson.sh` sets `SRVLOG=$OUT/server.log` internally, and `$OUT`
carries the `-think` suffix on a thinking-on run. A `SRVLOG` hardcoded to
`mmlupro100-<model>-<subset>` would point at a file that never exists for
those runs, and `run_measured.sh` would silently fall back to parsing the
journal — which on the Jetson has no `llama-server` unit, so `requests.csv`
would come out empty.

**`raw`** — a free-text label and command, wrapped in `run_measured.sh`. The
escape hatch, so the UI never blocks work it has not learned. Prechecks that
depend on knowing the model (memory) are skipped with a visible note;
directory and fingerprint checks still apply.

`tinygsm8k` (`./std_run.sh queue`) and `pi5_tier` (`./pi5_run.sh tier<n>`) are
**not** in the first version. Each is one registry entry when wanted; leaving
them out keeps the first implementation honest about what has been tested. The
same applies to IFEval, BFCL and the eventual safety benchmark.

### Two naming details the registry must carry

The label given to `run_measured.sh` and the directory lm-eval writes are
**not** the same string: label `mmlupro-e4b-s2`, output `mmlupro100-e4b-s2`.
Both templates therefore live in the registry rather than being derived from
one another.

A thinking-on run appends a suffix: `std_mmlupro.sh` sets
`OUT=$OUT-think`, producing `mmlupro100-e4b-s2-think`. See §6 for why this
matters to the dashboard today.

## 5. Prechecks and the fingerprint

### Prechecks — before anything starts

| check | rule | source |
|---|---|---|
| free memory | e4b ≥ 5400 MB, e2b ≥ 3900 MB available | `queue_jetson.sh`, from the s2 OOM |
| stale output dir | `<stdbench>/<run>` must not exist | a stale lm-eval cache is replayed, not regenerated |
| subset ids | `mmlupro_subset100_<subset>_samples.json` present, hash matches the committed copy | AGENTS §5, identical subsets on both boards |
| board idle | no `lm_eval` / `run_measured` / `llama-server` from another job | AGENTS §9 |

Each result is written to `precheck.json` with its measured value, not just a
verdict, so a refusal explains itself: *"only 4,102 MB available, e4b needs
~5,400"*, with the per-user RSS breakdown `queue_jetson.sh` already prints.

### The fingerprint — after the server is up, before lm-eval

`benchmark/baselines.json` (committed) declares the expected serving
configuration per condition. At job start the daemon captures the ground truth
and diffs it:

- `ps -o args= -C llama-server` — the resolved argv, which is the AGENTS §10
  check made automatic
- `model_path` from `http://127.0.0.1:8080/props`
- CPU governor, kernel, and for the Jetson the power mode
- the subset ids hash and the lm-eval task arguments

**The resolved argv is the only common ground between the boards, and this is
the whole point.** The two reach it by completely different routes: the Pi
rewrites `VA_LLM_MODEL_PATH`, `VA_LLM_SPEC_ARGS`, `VA_LLM_REASONING` and
`VA_LLM_CTX` in `/etc/voice-agent/runtime.env` and restarts `va-llm`, which
synthesises the command line; the Jetson passes flags directly to
`llama-server` in a `nohup`. Comparing the *inputs* on each board compares two
incomparable things. Comparing the resolved argv is what catches drift.

**Policy on drift: refuse to start.** An override exists, is recorded in
`events.jsonl` with what differed, and marks the job in the UI permanently.
This matches AGENTS §5 — every run is reported, including failed and
superseded ones — rather than letting an overridden run blend in later.

The fingerprint is re-checked once mid-run (a cheap `ps`), because the Pi's
model switch goes through va-web's `/model`, which recomputes
`VA_LLM_SPEC_ARGS` and can drop flags underneath a running job.

### Settled 2026-09-22: what `-rea` is, and why nothing caught the drift

Checked against `llama-server --help` on both boards (Pi build `661643e`,
Jetson `a894dae`). The run-script comments were right and AGENTS.md §5 was
wrong; §5 has been corrected.

```
-rea,  --reasoning [on|off|auto]   Use reasoning/thinking in the chat
                                   (default: 'auto' (detect from template))
--reasoning-format FORMAT          none: leaves thoughts unparsed in message.content
                                   deepseek: puts thoughts in message.reasoning_content
                                   (default: auto)
--reasoning-budget N               -1 unrestricted (default: -1)
```

`-rea` is `--reasoning`, the thinking switch. `--reasoning-budget -1` is
already the default, so the baseline's explicit form is redundant but worth
keeping — it puts the value in the resolved command line where the fingerprint
records it. The first `baselines.json` entry follows directly.

**The more important finding is that `meta.json` could not have answered this.**
`run_measured.sh` writes `meta.json` — including `server_args` from
`ps -o args= -C llama-server` — *before* it starts the wrapped command, and it
is the run script that afterwards restarts va-llm, or launches the Jetson's
server, with the run's real settings. The captured argv is therefore always
the **previous** state:

| board | archived `server_args` | why |
|---|---|---|
| Pi | the idle deployed server — 4 of 6 runs name the wrong model, all 6 say `-c 4096` where the run sets `8192` | va-llm still serving the last job's config |
| Jetson | **empty, all 9 runs** | the previous run's `pkill` left no process to sample |

Confirmed by inspection: the Pi's live idle argv today is byte-for-byte what
all six archived runs recorded.

This is why a missing `-rea` survived for days. The check AGENTS §10
prescribes was being performed against a field that describes a different
moment, and on the Jetson against nothing at all.

Two consequences for this design, both already load-bearing above:

1. **Capture timing is the whole point.** The fingerprint must be taken after
   the server is up and before lm-eval starts — not at job start. A
   fingerprint captured the way `meta.json` captures would reproduce the
   original bug exactly.
2. **`run_measured.sh` needs a second capture** written to `meta.json` after
   the wrapped command's server is serving, so runs launched outside the queue
   keep an honest record too. Small, and in scope: without it the two paths
   disagree about what a run's own `meta.json` means.

## 6. Dashboard changes

### New

- `app/api/queue/route.js` — GET status, POST add, DELETE cancel, each a thin
  wrapper over `queue_ctl.py`
- `app/api/logs/route.js` — incremental log reads by byte offset, so tailing a
  three-hour `lm_eval.log` does not re-send it every poll
- `app/queue/page.js` — the registry-driven job form, a live preflight panel
  showing each check as it would run, and the per-board queue with reordering
  and cancel
- `app/JobDetail.js` — event timeline, fingerprint diff, and log tabs
  (`lm_eval.log`, `server.log`, `command.log`)

### Changed

`app/lib/plan.js` — `cell()` currently decides a run is live by combining a
tqdm-parsed progress line with process names:

```js
const live = procs.lm_eval || procs.run_measured || procs.telemetry;
```

Its own comment explains the fragility: the log keeps reading `100/100` long
after a run ends, so the process check is what stops a finished run showing a
blue 100%. With a queue there is an authoritative answer, and `cell()` should
read it, falling back to the present heuristic when no daemon is running so a
board without the queue still renders.

`RUN_RE` in the same file is `/^mmlupro100-(e2b|e4b)(?:-(s\d))?$/i`, which
does not match the `-think` suffix that `std_mmlupro.sh` produces. **Thinking-on
runs are listed in AGENTS §6 as not-started work, so today this is latent; the
first such run will complete and not appear in the matrix.** The pattern and
the matrix need a thinking dimension. This is in scope because the queue can
launch those runs.

`scripts/check-ssh.mjs` — one more check per board: is the queue daemon alive
(`runner.pid` fresh), and does its `job_kinds.json` parse.

## 7. Keeping the daemon alive

| | Pi 5 | Jetson Orin Nano |
|---|---|---|
| supervision | systemd **user** unit + `loginctl enable-linger` | `@reboot` cron entry |
| watchdog | systemd `Restart=always` | `*/5 * * * *` cron checking `runner.pid` |
| why | passwordless sudo available | **no passwordless sudo**, no apt; cron is per-user |

One entry point, `queue_runner.py --daemon`, on both; only supervision
differs. Stdlib only, per AGENTS §7 — the Jetson has no reliable pip and its
venvs are bootstrapped by hand.

## 8. Failure behaviour

| situation | behaviour |
|---|---|
| daemon not running | board shows "queue offline"; jobs stay pending on disk; nothing lost |
| Mac asleep, ssh down | runs continue; dashboard replays `events.jsonl` on reconnect |
| job killed externally | pid gone with no `.done` → `failed`, last 20 log lines captured |
| power cut mid-write | atomic rename means `queue.json` is either the old or the new file, never a torn one |
| two tabs add at once | `flock` on `queue.json` serialises them |
| job exits 0 but no `.done` | `failed`. `std_mmlupro_jetson.sh` ends on `echo finished` and always returns 0, so exit status is not evidence — `queue_jetson.sh` learned this and the daemon inherits the rule |

## 9. Testing

`queue_runner.py` is stdlib-only and its state machine does not need a board:

- **State machine** — a fake job kind running `sleep 2` exercises
  queued → prechecking → fingerprinting → running → completed, plus every
  failure edge, on the Mac.
- **Fingerprint diff** — table-driven over recorded `ps` output. The
  2026-09-22 Jetson argv, missing the reasoning flags the Pi had, is a
  regression fixture: it must produce `blocked`.
- **Precheck** — synthetic `/proc/meminfo` and directory fixtures, including
  the 4,102 MB-against-5,400 MB case.
- **Atomicity** — concurrent `--add` under `flock` leaves a parseable
  `queue.json` with both jobs.
- **`--dry-run`** — resolves the command and runs every precheck without
  executing, so the full path can be exercised against a live board without
  spending three hours.
- **Both boards**, per AGENTS §7. Board-specific bugs have been the norm here:
  `~/Research` vs `~/research`, PMIC vs INA3221, journal vs file logs.

No test may run a real benchmark as part of the suite.

## 10. Scope

**In:** the daemon, `queue_ctl.py`, the `mmlupro` and `raw` job kinds,
prechecks, the fingerprint and `baselines.json`, the queue and job-detail UI,
the `plan.js` changes above, supervision on both boards, the `check-ssh.mjs`
check, and the second `server_args` capture in `run_measured.sh` (§5).

**Scheduling is FIFO per board, plus an optional "not before HH:MM" per job**,
interpreted in the board's own local time — the daemon evaluates it, and the
dashboard shows the board's timezone next to the field so a Mac in another
timezone cannot mislead. No recurrence, no cross-board dependencies, no
calendar. Queueing `e4b s2,s3` before bed is the real use case and
`queue_jetson.sh` already serves it; this generalises that rather than
building a scheduler.

**Out:** authentication and multi-user support; retry and backoff; editing
`conditions/*.json` or `devices/*.json` from the browser; any change to
`/compare`; the `tinygsm8k` and `pi5_tier` job kinds; replacing
`queue_jetson.sh`, which keeps working as the command-line path.

**Separate, smaller task, to land first:** the dashboard efficiency fixes —
SSH `ControlMaster` multiplexing in `app/lib/hosts.js`, and replacing the 5s
client poll with one server-side SSE stream. Measured today, a poll costs
0.67s against the Pi and 0.96s against the Jetson, of which roughly 0.2s and
0.5s is SSH handshake that multiplexing removes; at `POLL_MS = 5000` across
two boards an eight-hour run opens about 11,500 connections, each forking an
`sshd` and a Python interpreter on a board that AGENTS §5 requires to be
otherwise quiet. These are independently useful and the queue page benefits
from both, so they are not folded into this spec.

**Explicitly not recommended:** migrating the dashboard off Next.js. The app
is 1,974 lines; a rewrite to Vite or a bare Node server would reclaim disk and
dev-boot time while costing a full rewrite of `RunDetail.js` and `Charts.js`.
The measured cost is in the SSH layer, not the framework.
