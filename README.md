# agentic-edge

Agentic AI on edge devices: Gemma 4 **E2B** and **E4B** on a **Raspberry Pi 5**
(CPU only), an **Nvidia Jetson Orin Nano** (CUDA) and an **iPhone** (MLX),
measured against the standard runtimes **llama.cpp** and **little-gemma** and
an orchestration layer this project proposes. Accuracy and device cost (power,
thermals, utilisation) are measured in the same run.

Paper 1 covers text and reasoning only; voice is paper 2.

## Where things are

| folder | what it holds |
|---|---|
| [`benchmark/`](benchmark/) | the harness that runs on the boards: run scripts, telemetry, the job queue, tests, and the iPhone app (`apps/ios/`) |
| [`dashboard/`](dashboard/) | Next.js live monitor and queue UI, runs on the Mac |
| [`docs/`](docs/) | the study's design: protocol, condition matrix, method proposals, tooling design |
| [`findings/`](findings/) | every result: the write-up, per-question data, telemetry, analyses, audits |

The voice agent (condition E's pipeline: ASR, LLM, TTS, orchestrator, tools,
web UI) is on the **[`voice-agent`](https://github.com/rifkyariy/agentic-edge/tree/voice-agent)**
branch. The benchmark drives the copy deployed on the Pi and does not need it
checked out.

## What to read

| if you want to… | read |
|---|---|
| change anything in the repo (rules, devices, invariants) | [`AGENTS.md`](AGENTS.md) — **start here** |
| know what to do next | [`TODO.md`](TODO.md) |
| see every number and the current status | [`findings/RESULTS.md`](findings/RESULTS.md) (§10 is the status) |
| understand the protocol and statistics | [`docs/experiment-plan.md`](docs/experiment-plan.md) |
| see which conditions exist and what they cost | [`docs/experiment-matrix.md`](docs/experiment-matrix.md) |
| read the method proposals | [`docs/proposals/README.md`](docs/proposals/README.md) |
| read a single experiment's analysis | [`findings/analyses/`](findings/analyses/): S4 letter-only, permutation ensemble, iso-accuracy |
| run the harness | [`benchmark/README.md`](benchmark/README.md) |
| run the dashboard | [`dashboard/README.md`](dashboard/README.md) |
| work on the iPhone arm | [`benchmark/apps/ios/AGENTS.md`](benchmark/apps/ios/AGENTS.md) |
| see the first engine comparison (Sep 14, Pi only) | [`findings/early-engine-benchmarks/README.md`](findings/early-engine-benchmarks/README.md) |

## Baseline serving config

Every baseline MMLU-Pro number is served on both boards with:

```
llama-server -m <model> -c 8192 --host 127.0.0.1 --port 8080 \
  -rea off --reasoning-budget -1 --cache-ram 0
```

`-rea` is `--reasoning`, the thinking switch itself, and is not the same flag as
`--reasoning-format`. Why each flag is there, and what leaving one out cost, is
in [`AGENTS.md`](AGENTS.md) §4–§5.
