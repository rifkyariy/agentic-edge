# Experiment monitor

Live view of the Agentic Edge benchmark runs on both boards: current run and
ETA, board power, CPU and GPU utilisation, temperature, memory, the queue of
MMLU-Pro subsets, and a drill-down into any run's per-request timeline and
per-question answers.

```bash
cd dashboard
npm install
npm run dev          # http://localhost:3939
```

**No agent runs on the devices.** One API route shells out to
`ssh <host> 'python3 benchmark/probe_status.py'` for each box every 5 seconds
and a second route calls `benchmark/run_detail.py` when you open a run. It
reuses your existing SSH config, so the only requirement is that
`ssh MITLAB-EDGE` and `ssh MITLAB-JETSON` already work.

Hosts are listed in `app/api/status/route.js`; the paths differ per box because
the Pi keeps its tree in `~/Research` and the Jetson in `~/research` (a symlink
to its SSD).

## What the cells mean

| cell | meaning |
|---|---|
| green, with score | finished in the current batch, with telemetry |
| blue, with % and ETA | running now |
| grey dotted, with a date | an earlier batch, before telemetry — not part of this rerun |
| dashed | queued |

Click any finished or running cell (or the run name on a device card) for the
request timeline and every question with the model's full answer. A run still
in flight has no samples file yet, so its answers are recovered from lm-eval's
response cache and matched to questions by the option text they quote — the
sheet says so when that is what you are looking at.

Power is board DC draw: the Pi's PMIC rails summed, the Jetson's INA3221
`VDD_IN`. It excludes power-supply conversion loss, so it is comparable between
runs and between the two boards, but it is not wall power.
