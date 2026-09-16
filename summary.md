# Handoff: run the agentic-edge benchmark

You are picking up a built, working system and running an experiment with it.
Nothing here needs designing from scratch — the harness, the protocol, and the
tables are already written and verified. Your job is to execute the runs, fix
what breaks, and produce the tables.

Read this file, then [`benchmark/EXPERIMENT_PLAN.md`](benchmark/EXPERIMENT_PLAN.md)
(the protocol) and [`benchmark/README.md`](benchmark/README.md) (the harness).

---

## 1. Access

| device | ssh alias | notes |
|---|---|---|
| Raspberry Pi 5, 8GB | `MITLAB-EDGE` | The working box. Everything below is verified on it. |
| Jetson Orin Nano | `MITLAB-JETSON` | **Not set up yet** — see §6. |

Passwordless ssh and `sudo -n` both work on the Pi (`sudo -n` matters: toggling
MTP/thinking restarts `va-llm` through it).

The repo lives at **`~/Research/agentic-edge`** on each device (does not exist
yet — clone it there):

```bash
ssh MITLAB-EDGE
mkdir -p ~/Research && cd ~/Research
git clone https://github.com/rifkyariy/agentic-edge.git
cd agentic-edge/benchmark
```

For the **web UI and microphone**, tunnel rather than hitting the LAN IP —
`getUserMedia` only works in a secure context, so `http://192.168.1.233:8090`
refuses mic access while `localhost` does not:

```bash
ssh -L 8090:localhost:8090 MITLAB-EDGE     # then open http://localhost:8090
```

---

## 2. What already exists and works

Verified end-to-end on 2026-09-17, on the Pi:

- **`voice-agent/`** — six systemd services (`va-asr`, `va-llm`, `va-tts`,
  `va-orchestrator`, `va-tools`, `va-web`) deployed to `/opt/voice-agent`
  (code), `/etc/voice-agent` (config). All six active; web UI returns 200.
- **Six tools**, all returning live data: `web_search`, `match_result`
  (football, past *and* next fixture), `f1_result`, `currency_rate`,
  `weather_forecast`, `fetch_page`.
- **Five UI cards** (match, fixture, F1, currency, weather) rendering with no
  console errors, plus a 13-stage live pipeline inspector.
- **`benchmark/`** — the harness: adapters for four architectures, a 10-case
  suite, capability gating, three objective metrics, four report tables.

### The architecture being tested

The orchestrator does something the bare engines do not: it classifies each
turn, **pins `tool_choice` to one specific function**, offers only that schema,
and — if the model *still* answers without calling it — **calls the tool
itself** from derived arguments. That last mechanism is the contribution. You
will see it fire in the logs as:

```
orchestrator: model skipped the pinned tool, calling weather_forecast directly
```

---

## 3. The experiment in one paragraph

Five conditions (A little-gemma, B llama.cpp bare, C LiteRT-LM bare,
D llama.cpp + naive function calling, E the proposed orchestrator) × 2 models
(Gemma 4 E2B/E4B) × 2 devices, then MTP/thinking toggles on the two engines
that support them, then a quant sweep. **D vs E is the claim** — A/B/C have no
tool access at all, so beating them only proves a system with internet beats
one without. D is the same engine with the same schemas offered naively.

Three metrics, none needing live ground truth: **tool-selection accuracy**,
**fabrication rate** (substantive answer to a live-data question with no tool
call), and **static-answer accuracy** (fixed-truth cases only).

---

## 4. Running it

```bash
cd ~/Research/agentic-edge/benchmark

# FIRST: sanity-check the metric before burning hours on it
python3 run_benchmark.py --device devices/pi5.json --condition conditions/A.json --model e2b
# Read the result JSON. fabrication.pct MUST be ~100 for a no-tools engine on
# tool-requiring cases. If it is not, the metric is broken and every later run
# is wasted. (Condition E is already verified at 0%, so both ends have a
# known-good reference.)

./sweep.sh tier1 devices/pi5.json    # 5 conditions x 2 models, full suite
./sweep.sh tier2 devices/pi5.json    # MTP x thinking, conditions B and E
./sweep.sh tier3 devices/pi5.json    # quant sweep (needs downloads first, §5)

python3 report.py t1                 # the four tables
python3 report.py t2
python3 report.py t3
python3 report.py t4
```

Config is two layers that never duplicate each other: `devices/<box>.json`
(paths, endpoints, cuda — written once per box) and `conditions/<X>.json`
(engine, tools, mtp, thinking — identical everywhere). Adding a device is one
file; adding a condition is one file.

Commit results as you go — `results/*.json` is gitignored by default, so
either `git add -f` the ones worth keeping or copy the report tables into a
findings doc.

---

## 5. Pi 5 inventory — verified, with the gaps

```
/home/mitlab/models/
  gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf   2.44 GiB   -> model key "e2b"
  gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf   3.93 GiB   -> model key "e4b"
  mtp-gemma-4-E2B-it.gguf              0.06 GiB   MTP draft head
  mtp-gemma-4-E4B-it.gguf              0.06 GiB   MTP draft head
/usr/local/bin/lg                                 little-gemma (NOT ~/little-gemma)
/home/mitlab/litert-venv/bin/litert-lm            LiteRT-LM CLI
~/.litert-lm/models/gemma-4-E4B-it.litertlm  3.4 GB
Disk: 82G free of 117G.  Python 3.13.5.  node: ABSENT.
```

**Three gaps you must handle:**

1. **Condition C (LiteRT-LM) needs a server started, and only has E4B.**
   Nothing is listening on 9379. Start it:
   ```bash
   /home/mitlab/litert-venv/bin/litert-lm serve gemma-4-E4B-it.litertlm --port 9379
   ```
   E2B is **not imported** — either `litert-lm import` it, or report C/E2B as
   `n/a` with that reason. Do not silently skip it.
2. **Tier 3 quant files do not exist.** Only Q4_K_XL is present. Fetch
   `Q4_K_M`, `Q5_K_M`, `Q8_0` for E4B (paths already in `devices/pi5.json`,
   marked `_missing`) or drop Tier 3 and say so.
3. **`node` is absent on the Pi.** Only affects `tests/test-readable.js` (a UI
   test), not the benchmark. Ignore it there.

---

## 6. Jetson Orin Nano — a full day of setup

`devices/jetson.json` is a template with placeholder paths. On the box:

- [ ] llama.cpp built **with CUDA** (`-DGGML_CUDA=ON`), serving on 8080
- [ ] little-gemma built — it is C/**CUDA**, so here it may actually use the
      GPU. The harness auto-labels it `A-cuda` vs the Pi's `A-cpu`, because a
      GPU row is not the same condition. **This is plausibly the single most
      interesting cell in the study**: little-gemma's whole design premise is
      CUDA, and the Pi never gave it a GPU to justify itself on.
- [ ] LiteRT-LM — **unknown whether it supports the Jetson GPU at all.** If
      not, report `n/a` with that reason rather than omitting the row.
- [ ] Models: E2B + E4B Q4_K_XL + both MTP heads (~7GB). Check disk first.
- [ ] Condition E needs the whole voice-agent stack (whisper.cpp, piper,
      models, six units). Deploy with:
      `DEPLOY_HOST=MITLAB-JETSON ./deploy.sh` from `voice-agent/`
- [ ] **Record the power mode** (`nvpmodel -q`) in `devices/jetson.json`. A
      15W run and a 25W run are not the same experiment.

Sequence the Pi to completion *before* starting Jetson setup. If the Jetson
slips, a Pi-only study still supports the headline claim (D vs E); two
half-finished halves support nothing.

---

## 7. Things that will bite you — all learned the hard way here

| gotcha | what to do |
|---|---|
| **llama.cpp does not reliably honour a *named* `tool_choice`** when several tools are offered. Verified by replaying a request pinned to `weather_forecast`: it returned plain text inventing "scattered thunderstorms, 31.7°C". | This is *why* the orchestrator offers only the pinned schema and has a fallback executor. Do not "simplify" it away. It is also the finding condition D exists to measure. |
| **Cold vs warm is ~1.7–2.2×** from system-prompt prefill caching. Measured 80.5s cold vs 47.6s warm on the same config. | Already handled: repeat 0 is reported as cold, 1+ as warm median. Never quote a mean across repeats. |
| **little-gemma on the Pi is ~0.5 tok/s** with E4B. A 10-case run × 4 repeats could take **hours**. | Consider `--repeat 2` for condition A, and raise `timeout_s` in the device file above 240 if cases time out. Budget it; do not assume it hangs. |
| **DuckDuckGo rate-limits** and starts returning HTTP 202 challenge pages for *every* query, including unrelated ones. Tier 1 alone is ~400 live external calls. | `COOLDOWN=60 ./sweep.sh …`. The tool raises `SearchBlocked` rather than pretending to have no results, so it is visible in the logs. |
| **Wikimedia 429s** on bursts (F1 flags). | Already fixed: 39 flag URLs are pre-resolved in `tool_schemas`-adjacent static tables, no live lookups. |
| **MTP is ~1.7× *slower* on the Pi** at 100% draft acceptance — it is a CPU-width problem, not an acceptance problem. | Expected result, not a bug. The open question is whether the sign flips on the Jetson's GPU. |
| **`va-*` services are NOT enabled at boot.** The Pi rebooted mid-project and everything was down for 9 hours. | After any reboot: `sudo systemctl start va-llm va-asr va-tts va-orchestrator va-web`. Ask the user before `systemctl enable`-ing them. |
| **The Pi is slow.** Tool turns take 60–95s. | Use background commands and polling loops, not blocking waits. Do not conclude something is hung before ~2 minutes. |
| **Restarting `va-web` mid-turn** drops the browser's SSE stream and the pipeline panel shows a mix of two turns. | Do not deploy while a turn is in flight. |
| **The web UI has no authentication** and binds `0.0.0.0`. | Fine on a trusted LAN; do not expose it further. |

---

## 8. Definition of done

- [ ] Condition A verified to give `fabrication ≈ 100%` on tool cases
- [ ] Tier 1 complete on the Pi (10 runs), Jetson too if it is up
- [ ] Tier 2 complete (MTP sign compared across devices — the CUDA finding)
- [ ] Tier 3 complete, or explicitly dropped with a reason
- [ ] `report.py t1 t2 t3 t4` produces all four tables
- [ ] **Every `n/a` cell has a one-line reason** in the writeup — LiteRT-LM on
      Jetson, C/E2B, missing quants, unsupported toggles. An honest gap beats
      a quietly missing row.

## 9. One framing note for the writeup

"little-gemma doesn't work on non-CUDA" is stronger than the evidence and
aimed at a claim its authors never made — its README says it is not a
llama.cpp competitor and its numbers are explicitly CUDA-scoped. The
defensible version is what the data shows: *0.47–0.55 tok/s on Pi 5 ARM CPU
versus llama.cpp's several tok/s on identical hardware and model* — you
quantify a limitation its authors already documented, then show whether the
GPU row vindicates the design. That is a stronger and fairer result, and it
cannot be argued with.

Related work, and the gap this fills, is in the git history of
`benchmark/EXPERIMENT_PLAN.md` discussion — the short version: device/quant
throughput benchmarks exist (Renney et al. 2026 covers Pi 5 + Jetson Orin
Nano), tool-calling reliability benchmarks exist (TinyLLM; "Beyond Fluent
Generation" found only 5/1000 raw responses parseable as JSON), and the Gemma
4 technical report is arXiv:2607.02770 — but **nothing runs one fixed suite
across device × engine × quant *and* scores MTP, tool calling, and thinking
together**, and no published benchmark covers Gemma 4 E2B/E4B specifically.
