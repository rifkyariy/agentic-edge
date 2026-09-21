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

## Setup

```bash
cd dashboard
npm install
npm run check      # can this Mac reach both boards?
npm run dev        # http://localhost:3939
```

`npm run check` is the important step on a fresh clone. It verifies, per board:
ssh works with key auth, the repo is where the dashboard expects it,
`probe_status.py` runs, and the eval venv's python exists. Every failure prints
the command that fixes it. `npm run dev` runs it first too, but does not block
on it.

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
--cache-ram 0`). `-rea` is `--reasoning-format`, not a reasoning switch —
without it llama.cpp splits Gemma's thinking into `reasoning_content`, which
lm-eval never reads, and answers arrive truncated or empty. Jetson runs from
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

A run still in flight shows both tabs. Its answers come from lm-eval's response
cache and are matched to questions by the option text they quote, so a few may
read `unmatched`; its device figures are marked `so far` and are computed from
the telemetry written up to that moment.
