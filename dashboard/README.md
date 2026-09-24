# Live experiment monitor

A Next.js page that watches both boards over SSH while they work through the
MMLU-Pro queue: what is running, how far along, what the board is drawing, and —
per run — the request timeline, the device conditions behind each request, and
every question and answer.

It runs on your Mac. Nothing is installed on the boards; it calls two scripts
that already live in the repo there:

| | |
|---|---|
| `benchmark/probe_status.py` | one-shot status, polled every 5s |
| `benchmark/run_detail.py` | one run in full, on demand |
| `benchmark/queue_ctl.py` | the queue: status, preflight, add, cancel, logs |

## Setup

```bash
cd dashboard
npm install
npm run check      # can this Mac reach both boards?
npm run dev        # http://localhost:3939
```

`npm run check` is the important step on a fresh clone. It verifies, per board:
ssh works with key auth, the repo is where the dashboard expects it,
`probe_status.py` runs, the eval venv's python exists, and the queue daemon is
running. Every failure prints the command that fixes it. `npm run dev` runs it
first too, but does not block on it.

### SSH

The dashboard reaches each board by name, using your own `~/.ssh/config` and
agent — it never asks for a password (`BatchMode=yes`), so key auth has to work
before the page shows anything.

```
Host MITLAB-EDGE
  HostName 192.168.1.233
  User mitlab

Host MITLAB-JETSON
  HostName mitlab-orin-nano
  User ari
```

Then `ssh-copy-id MITLAB-EDGE` (and the Jetson) if the key is not there yet.

Different machines? Copy `.env.example` to `.env.local` and set `PI_HOST` /
`JETSON_HOST` to an alias or `user@host`, plus `*_REPO` and `*_PY` if the paths
differ. Note the case convention the boards use: `~/Research` on the Pi,
`~/research` on the Jetson.

## Reading the page

**Queue matrix** — model × subset per board. Green is finished this batch,
blue is running, dotted is the earlier batch before telemetry existed. Click a
finished or running cell to open it.

**Device cards** — live power, CPU, temperature and GPU over the last 20
minutes, plus progress and ETA for whatever is running.

All MMLU-Pro runs shown here are the **baseline, thinking-off** config: both
boards serve with `-rea off --reasoning-budget -1` (plus `-c 8192
--cache-ram 0`). `-rea` is `--reasoning`, the thinking switch itself, so `off`
is a genuine no-chain-of-thought condition. Omitting it defaults to `auto`,
which turns thinking on for Gemma and — via the separate `--reasoning-format`,
also `auto` — files the thoughts under `reasoning_content`, which lm-eval never
reads, so answers arrive truncated or empty. Jetson runs from
before 2026-09-22 lack it and are archived as superseded.

**Run detail** has two tabs:

- **Device** — prefill and decode seconds per request as stacked bars with
  decode tok/s over them, then board power, CPU, GPU and temperature across the
  same time span, so a spike lines up with the request that caused it. Below
  that, the same thing as a table.
- **Questions** — every question, the model's full answer, what it picked and
  what was correct.

Click any bar in the timeline, or any row in the request table, to jump to that
question — its own power, energy, J/token and thermals are shown with it.

## Queueing a run

`/queue` starts runs instead of only watching them. Each board runs a small
daemon (`benchmark/queue_runner.py`, a systemd user unit) that owns a queue
file and takes one job at a time, so a run survives this Mac going to sleep and
"one job per device" is a property of the loop rather than a rule to remember.

The form is built from each board's own `job_kinds.json`, so it cannot offer a
job the daemon would refuse. Every change re-runs the preflight, and you see
the answer before committing three hours:

- **memory** — E4B needs ~5,400 MB free, E2B ~3,900 MB. This is the check that
  would have caught the s2 run OOM-killed at question 94 after 2h39m.
- **output directory** — a run whose `stdbench/` directory already exists is
  refused, because a stale lm-eval cache there is replayed, not regenerated.
- **subset ids** — the committed question ids for that subset must be present.
- **board idle** — nothing else benchmarking.

Before lm-eval starts, the daemon captures the resolved `llama-server` command
line and diffs it against `benchmark/baselines.json`. **On drift it refuses to
start.** This is the AGENTS §10 check made automatic: it is what would have
caught the Jetson serving without `-rea off` before 2026-09-22, which cost
every run its thinking and was only noticed days later by reading answers. An
override exists, is written to the event log, and marks the job permanently.

Each job's page shows its timeline, the flag diff, and live tails of
`lm_eval.log`, `server.log` and `command.log`. Completion is the `.done`
marker, never the exit status — `std_mmlupro_jetson.sh` ends on
`echo finished` and always returns 0.

## Run detail

A run still in flight shows both tabs. Its answers come from lm-eval's response
cache and are matched to questions by the option text they quote, so a few may
read `unmatched`; its device figures are marked `so far` and are computed from
the telemetry written up to that moment.

## Adding a page or a feature

The pieces below exist so a new page is a few lines, not a copy of an old one.

| you need | use | don't |
|---|---|---|
| a new page in the sidebar | add `{ href, label, hint }` to `PAGES` in `app/components/Nav.js` | add link rows to page headers |
| a page title | `<PageHeader title sub>`; put live status in its children | hand-build `<header className="top">` |
| data from a board | `onBoard(box, "script.py", args)` or `onEveryBoard(...)` from `app/lib/ssh.js`, in a route under `app/api/` | `exec`/`execFile` ssh in the route; ad-hoc ssh commands (AGENTS §7) |
| a polled endpoint | wrap it in `shared(key, ttl, fn)` (`app/lib/shared.js`) so tabs share one probe | poll the boards per tab |
| the queue on a page | `useQueue()` (`app/lib/queue-context.js`): `boxes`, `refresh()` | fetch `/api/queue` yourself |
| "what is this run doing now" | `latestPerRun(jobs)`; a requeued job replaces its earlier attempts | the first or newest *live* job — both showed stale "blocked" cells |
| a job or run state | `<StatePill state family>` | inline `state-pill` classes |
| numbers, durations, times | `fmt`, `durSeconds`, `durMinutes`, `clock` from `app/lib/format.js` | a local `dur` or `fmtTime` |
| a client poll | `usePoll(fn, ms, { hiddenMs })`: pauses or slows in a hidden tab | `setInterval` |

Tests: `node --test dashboard/app/lib/*.test.mjs`.
