# Agentic Edge — where the project stands

Agentic AI on edge devices: Gemma 4 **E2B** and **E4B** on a **Raspberry Pi 5**
(CPU and RAM only) and an **Nvidia Jetson Orin Nano** (CUDA), compared against
the standard native runtimes **llama.cpp** and **little-gemma**, with an
orchestration layer this project proposes on top.

**Paper 1 is text and reasoning parameters only.** Voice into Gemma's multimodal
path is paper 2.

**Baseline serving config:** both boards run `-rea off --reasoning-budget -1`
(plus `-c 8192 --cache-ram 0`). `-rea` is `--reasoning-format`, not a reasoning
switch — without it llama.cpp splits Gemma's thinking into `reasoning_content`,
which lm-eval never reads, and answers arrive truncated or empty. The Jetson ran
without it until 2026-09-22; those runs are archived under `stdbench/failed/`.
Thinking-on (`THINKING=on`, budget 320) is a separate condition.

Read next: [`benchmark/EXPERIMENT_PLAN.md`](benchmark/EXPERIMENT_PLAN.md) for the
protocol and statistical design, [`findings/RESULTS.md`](findings/RESULTS.md)
for every number measured so far, [`benchmark/README.md`](benchmark/README.md)
for the harness.

---

## 1. Devices

| device | ssh | state |
|---|---|---|
| Raspberry Pi 5, 8GB | `MITLAB-EDGE` | working box, everything below measured on it |
| Jetson Orin Nano | `MITLAB-JETSON` (`ari@mitlab-orin-nano`) | **not set up** — see §5 |

Repo lives at `~/Research/agentic-edge` on each device. Benchmark outputs go to
`~/Research/stdbench` (accuracy) and `~/Research/measured` (telemetry).

For the web UI and microphone, tunnel rather than hitting the LAN IP —
`getUserMedia` needs a secure context:

```bash
ssh -L 8090:localhost:8090 MITLAB-EDGE     # then open http://localhost:8090
```

## 2. What exists and works

- **`voice-agent/`** — six systemd services on the Pi (`va-asr`, `va-llm`,
  `va-tts`, `va-orchestrator`, `va-tools`, `va-web`), six live tools, five UI
  cards, a 13-stage pipeline inspector.
- **`benchmark/`** — two halves: the own suite (architectures, tool calling,
  MTP, quant sweep) and standard benchmarks wrapped in **1 Hz device
  telemetry** (power from the PMIC rails, per-core CPU, temperature, throttle
  flags, memory, per-request token timings).
- **`findings/`** — results, per-question outputs, the audits, and an
  interactive page built by `benchmark/build_viz.py`.

**The architecture under test:** the orchestrator classifies each turn, pins
`tool_choice` to one function, offers only that schema, and — if the model
answers anyway — **calls the tool itself** from derived arguments. That last
mechanism is the contribution.

## 3. Results so far (Pi 5)

Full detail in [`findings/RESULTS.md`](findings/RESULTS.md). The headline:

| | E2B | E4B |
|---|---|---|
| **MMLU-Pro**, 100-question subset s1 | **56.0% ± 5.0** | **64.0% ± 5.0** |
| published figure (Google model card) | 60.0% | 69.4% |
| GSM8K (tinyGSM8k, 1024-token cap) | 80.2% | pending |
| idle / working board power | \~2.3 W / \~6.9 W | measured per run |

**Five findings that contradicted the plan**, kept deliberately:

1. **Gemma 4 refuses rather than fabricates.** Zero fabrications across 62
   audited live-data answers, against an expected ~100%. The metric was
   reframed to SimpleQA-style correct / incorrect / not-attempted.
2. **Naive function calling already selects tools perfectly** (24/24, both
   models) on single-turn prompts. It just never answers — it emits a call and
   stops. The orchestrator's claim is grounded answering, not selection.
3. **MTP is 1.25-2.15× faster on this CPU** with byte-identical output,
   contradicting the earlier "speculative decoding loses on CPU" note.
4. **Benchmark defaults understate these models by ~15 points** — lm-eval's
   256-token cap truncated 24% of E2B's GSM8K answers mid-solution.
5. **The orchestrator over-triggers**: 15.7% of static questions are sent into
   a pointless lookup ("How many kilograms are in a pound?" → currency tool).

## 4. Running an experiment

```bash
ssh MITLAB-EDGE
cd ~/Research/agentic-edge/benchmark

# accuracy + telemetry in one run
./run_measured.sh mmlupro-e2b-s1 -- env SUBSET=s1 ./std_mmlupro.sh e2b

# own suite
./pi5_run.sh tier1

# rebuild the results page from whatever data is on disk
python3 build_viz.py
```

**Statistical design, in one line:** decoding is greedy, so repeating the same
questions measures only ~1 point of implementation noise; the real uncertainty
is which questions were drawn (±9.7 at n=100), so the study uses **three
disjoint seeded subsets** (s1/s2/s3) pooled to n=300 (±5.6), with every run
reported rather than the best.

## 5. Jetson Orin Nano — not started

- [ ] SSH key installed (`ssh-copy-id -i ~/.ssh/id_ed25519.pub ari@mitlab-orin-nano`)
- [ ] llama.cpp built with CUDA (`-DGGML_CUDA=ON`), serving on 8080
- [ ] little-gemma built — it is C/**CUDA**, so this is the row its design
      premise was written for, and the Pi never gave it a GPU to justify
      itself on
- [ ] Models: E2B + E4B Q4_K_XL + both MTP heads (~7GB); check disk first
- [ ] Telemetry: `telemetry.py` needs a Jetson power source — `tegrastats` or
      the INA3221 rails under `/sys/bus/i2c/.../hwmon`, not `vcgencmd`
- [ ] **Record the power mode** (`nvpmodel -q`): a 15W and a 25W run are not
      the same experiment
- [ ] Same subsets, same scripts, then the Pi-vs-CUDA comparison

## 6. Things that will bite you

| gotcha | what to do |
|---|---|
| **llama.cpp does not reliably honour a named `tool_choice`** when several tools are offered — verified by replaying a request pinned to `weather_forecast`: it invented "scattered thunderstorms, 31.7°C". | This is *why* the orchestrator offers one schema and has a fallback executor. Do not "simplify" it away. |
| **llama.cpp's default host prompt cache is 8192 MiB**, more than the Pi has. | `--cache-ram 0` for any run with many distinct prompts, or the server is OOM-killed mid-run (it died at question 48 of the first E4B GSM8K attempt). |
| **The deployed 4096 context truncates MMLU-Pro answers** — longest prompt is 2,427 tokens against a 2,048-token budget. | `-c 8192`, which `std_mmlupro.sh` sets and restores. |
| **lm-eval's default 256-token cap** silently truncates chain-of-thought mid-solution. | Pass `max_gen_toks` explicitly; 1,024 is Meta's GSM8K setting. |
| **Cold vs warm is ~1.7-2.2×** from system-prompt prefill caching. | Repeat 0 is cold, 1+ is warm median. Never quote a mean across repeats. |
| **little-gemma on the Pi is ~0.5-1.5 tok/s** and has no max-token flag. | A runaway generation blocks the queue; the harness kills and respawns the server on timeout and keeps the partial answer. |
| **DuckDuckGo rate-limits** and starts returning challenge pages. | `COOLDOWN=60`. The tool raises `SearchBlocked` rather than pretending there are no results. |
| **`va-*` services are NOT enabled at boot.** | After a reboot: `sudo systemctl start va-llm va-asr va-tts va-orchestrator va-web`. Ask before `systemctl enable`-ing them. |
| **The Pi is slow.** MMLU-Pro is ~100s/question on E2B, ~215s on E4B. | Use background runs and polling, not blocking waits. |
| **The web UI has no authentication** and binds `0.0.0.0`. | Fine on a trusted LAN; do not expose it further. |

## 7. What is left

Priority order: finish the MMLU-Pro subsets on the Pi (s2, s3 for both models,
queued) → Jetson setup and the same runs → capability (b) standard benchmark
(IFEval/BFCL are installed but unrun) → capability (c) safety and security
benchmark, not yet chosen → thinking-on rows → manuscript.
