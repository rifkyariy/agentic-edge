# Experiment plan

The protocol this harness exists to run: what to build first, what to run in
what order on which device, what each table proves, and what is likely to go
wrong. Written to be followed at 2am next to a Jetson, not admired.

**Claim under test:** wrapping a small edge model in an agentic orchestration
layer (intent classification → pinned tool choice → orchestrator-side
fallback execution) measurably improves factual reliability over the same
model with naive function calling, and the latency cost of that layer is
bounded and attributable.

**Secondary claim:** CUDA changes which inference-time optimisations are
worth enabling — specifically that MTP loses on CPU and may win on GPU with
the identical model and draft head.

---

## Phase 0 — Prerequisites

### 0.1 Harness changes — **DONE**

All eight landed and were verified against the live Pi (condition E, real
tool call, `tool_selection 100%`, `fabrication 0%`, `tool_time 1.0s` split
out of `model_time 46.5s`, cold 80.5s vs warm 47.6s). Kept here as the record
of what changed and why.

| # | change | file | why |
|---|---|---|---|
| 1 | `offer_tools` config flag → include tool schemas + `tool_choice: auto` in the request | `adapters.py` (`run_openai_compat`) | Condition D does not exist yet. Without it the headline comparison is "system with internet vs system without", which proves nothing. |
| 2 | Static `tool_schemas.json`, dumped once from `va-tools` | new file | Condition D must offer *the same* schemas on the Jetson, where `va-tools` may not be running. Generate with `{"op":"list"}` over the tools socket on the Pi, commit the result. |
| 3 | `fabricated` per-case metric | `run_benchmark.py` | The metric that carries the argument without needing live ground truth. `fabricated = (case has expected_tool) AND (no tool called) AND (answer is substantive, i.e. not a refusal/hedge)`. Needs a small `REFUSAL` regex — reuse the shape of `PROMISE` in `orchestrator.py`. |
| 4 | `condition` label in config (`"A"`…`"E"`) | `conditions/*.json` | Tables group by condition. Inferring it from `engine` + flags breaks the moment two conditions share an engine (B and D both use llama.cpp). |
| 5 | Median + cold/warm split | `run_benchmark.py` summary, `report.py` | `mean` over `repeat: 3` averages one cold and two warm turns and describes neither — this project's own README documents turn 1 being ~2.2× slower from system-prompt prefill caching. Report `cold` (repeat 0) and `median_warm` (repeats 1+) separately. Default `repeat: 4` → n=3 warm. |
| 6 | Capture per-tool `took` and subtract it | `adapters.py` (`run_proposed`) | `proposed`'s total includes network I/O to Sofascore/Open-Meteo, which is not the architecture's cost and varies with the internet. The `tool_result` event already carries `took`; record it so `model_time = total − tool_time` can be reported. Without this, network variance dominates the comparison and the result is not defensible. |
| 7 | `report.py` subcommands `t1 t2 t3 t4` | `report.py` | Four different tables, four different groupings. One flat table cannot serve all of them. |
| 8 | `DEPLOY_HOST` env override | `voice-agent/deploy.sh` | `HOST=MITLAB-EDGE` is hardcoded. Condition E on the Jetson needs the stack deployed there too. |

### 0.2 Per-device prerequisites

**Raspberry Pi 5 — already done.** Full voice-agent stack deployed and
running; llama.cpp + little-gemma built; models present.

**Jetson Orin Nano — the real setup cost. Budget a day.**

- [ ] llama.cpp built **with CUDA** (`-DGGML_CUDA=ON`), serving `/v1/chat/completions`
- [ ] little-gemma built — note it is C/**CUDA**, so on this board it may
      actually use the GPU. That makes Jetson-little-gemma a *different
      condition* from Pi-little-gemma, not the same row on another device.
      Label them separately (`A-cpu` / `A-cuda`). **This is plausibly the most
      interesting cell in the whole study** — little-gemma's design premise is
      CUDA, and the Pi never gave it a GPU to justify itself on.
- [ ] LiteRT-LM installed. **Unknown whether it supports the Jetson GPU at
      all.** If it does not, that cell is reported `n/a` explicitly — never
      silently dropped.
- [ ] Models present: E2B + E4B at the primary quant, plus MTP draft heads
      (`mtp-gemma-4-{E2B,E4B}-it.gguf`), plus the Tier-3 quant variants.
      ~15GB. Check disk before starting.
- [ ] Full voice-agent stack for condition E: whisper.cpp + piper + models +
      the six `va-*` units. Reuse `deploy.sh` once change #8 lands.
- [ ] Fixed cooling/power mode. Record `nvpmodel` / power mode in the config
      `_note` — a 15W vs 25W run is not the same experiment.

### 0.3 Case files

| file | cases | used by |
|---|---|---|
| `cases.json` | all 10 | Tier 1 |
| `cases_t2.json` | 5: `knowledge-capital`, `thinking-arithmetic`, `creative-poem`, `weather-now`, `football-result` | Tier 2 — the MTP/thinking axes need latency and static accuracy, not all five tool categories |
| `cases_t3.json` | 4: `knowledge-capital`, `thinking-arithmetic`, `weather-now`, `knowledge-socket` | Tier 3 |

Tier 2 and 3 exist mainly to cut wall clock (see §4).

---

## Phase 1 — Tier 1: the headline (20 runs)

Fixed quant (`Q4_K_XL` QAT), MTP off, thinking off, `repeat: 4`, all 10 cases.

| condition | engine | `offer_tools` | devices | models |
|---|---|---|---|---|
| A little-gemma | `little_gemma` | — | Pi, Jetson | E2B, E4B |
| B llama.cpp bare | `llama_cpp` | false | Pi, Jetson | E2B, E4B |
| C LiteRT-LM bare | `litert_lm` | false | Pi, Jetson | E2B, E4B |
| D llama.cpp + naive tools | `llama_cpp` | **true** | Pi, Jetson | E2B, E4B |
| E proposed | `proposed` | (inherent) | Pi, Jetson | E2B, E4B |

5 conditions × 2 models × 2 devices = **20 runs**.

One command per device — `sweep.sh` groups by model then condition so
weights are not reloaded more than necessary:

```bash
./sweep.sh tier1 devices/pi5.json      # on the Pi
./sweep.sh tier1 devices/jetson.json   # on the Jetson
```

**Before queueing the whole tier, run condition A alone and read the result
file by hand:**

```bash
python3 run_benchmark.py --device devices/pi5.json \
                        --condition conditions/A.json --model e2b
```

If `fabrication.pct` is not ~100 for a no-tools engine on the tool-requiring
cases, the metric is wrong and all 55 later runs are wasted. (Condition E was
already verified to give 0% on the same metric, so both ends of the scale
have a known-good reference.)

---

## Phase 2 — Tier 2: MTP × thinking × CUDA (32 runs)

Only conditions B (`llama_cpp`, no tools) and E (`proposed`) — the two that
actually support both toggles. `cases_t2.json`, `repeat: 4`.

2 devices × 2 models × 2 MTP × 2 thinking × 2 conditions = **32 runs**.

```bash
./sweep.sh tier2 devices/pi5.json
./sweep.sh tier2 devices/jetson.json
```

For condition E the harness flips the toggles itself (`configure_proposed()`
→ `POST /option` → waits for `va-llm`). For condition B **the server must be
relaunched with matching flags** (`--spec-type draft-mtp …`, `-rea on`) —
the config field is only a label, and a mismatch silently mislabels the row.
This is the one remaining manual step: write a `serve_llama_cpp.sh` that
reads the same device+condition JSON so the server and the harness cannot
disagree, rather than relaunching by hand 16 times.

**The cell to look at:** Jetson × E4B × MTP on/off. Pi already measured 1.7×
*slower* with MTP at 100% draft acceptance. If it wins on the Jetson with the
same model and draft head, CUDA is isolated as the causal variable in a clean
natural experiment — a stronger finding than a throughput chart, and the
empirical counterpart to [Dovetail](https://arxiv.org/abs/2412.18934), which
proposes CPU/GPU-split speculation precisely because the CPU-only case loses.

---

## Phase 3 — Tier 3: quant sweep (4 runs)

One device (Pi 5), one engine (`llama_cpp`, bare), one model (E4B),
`cases_t3.json`, `repeat: 4`. Quants: `Q4_K_M`, `Q4_K_XL` (QAT), `Q5_K_M`,
`Q8_0`. Also record file size on disk and resident RSS — those are the
columns that make this table worth having, and neither is captured
automatically today (`ps`/`systemctl status` by hand, or add it to change #6).

Deliberately an appendix: quant sweeps are well covered already
([Kurt 2026](https://arxiv.org/abs/2601.14277),
[Sustainable LLM Inference](https://arxiv.org/pdf/2504.03360)). This is a
robustness check on the headline, not a competing result.

---

## Phase 4 — Tables and the claim each supports

| table | grouping | supports |
|---|---|---|
| **T1** architecture comparison | condition × device × model | D vs E is the contribution: tool-selection accuracy and fabrication rate at bounded latency cost. A/B/C are the floor. |
| **T2** MTP × thinking × CUDA | device × model × mtp × thinking | (e) and (f). The MTP sign-flip across devices, and thinking's accuracy-for-latency trade. |
| **T3** quant sweep | quant | (c), robustness. |
| **T4** classifier behaviour | category (condition E only) | The intent classifier works *and does not over-trigger* — `creative` calling no tool is a positive result, and per-category latency shows the tool tax is paid only where needed. |

Columns per table as specified in the design discussion; `report.py t1`…`t4`
after change #7.

---

## Phase 5 — Risks, and what to do about each

| risk | mitigation |
|---|---|
| **External API rate limiting** polluting latency. ~20 runs × 4 repeats × 5 tool cases ≈ 400 live calls in Tier 1 alone; DuckDuckGo already returned HTTP 202 challenges under lighter load during development. | Report `model_time` (total − tool I/O) as the primary latency metric (change #6). Space runs. Treat tool-fetch time as an environmental variable, reported but not compared. |
| **Thermal throttling** over multi-hour runs, on both boards. | Fixed cooldown between runs; log `vcgencmd measure_temp` / `tegrastats` per run into the result file. A throttled run is not a comparable run. |
| **LiteRT-LM may not support the Jetson GPU.** | Report `n/a` explicitly in T1/T2 and say so in the text. An honest gap beats a quietly missing row. |
| **MTP draft heads may not exist** for every model/quant combination. | Already handled — `mtp_args()` refuses and returns a message. Record the refusal as `n/a`, do not silently run without MTP while labelling the row "on". |
| **n=3 warm repeats is thin.** | Report median with min/max (or IQR), not mean ± SD implying more precision than 3 points support. Accuracy metrics are better off: 10 cases × 3 repeats = 30 observations per cell. State both sample sizes in the writeup. |
| **Condition E on Jetson is a day of setup** and may not happen. | If it slips, Tier 1 on the Pi alone still supports the headline claim (D vs E); the Jetson then contributes only Tier 2's CUDA finding. Sequence Pi-complete before Jetson-start so a partial study is still publishable. |

---

## Wall-clock estimate

Rough, from observed Pi latencies (tool cases 60–90s, knowledge 3–20s;
~30s average per case execution):

| phase | runs | executions | estimate |
|---|---|---:|---|
| Tier 1 | 20 | 800 | ~7 h |
| Tier 2 | 32 | 640 | ~5 h |
| Tier 3 | 4 | 64 | ~0.5 h |
| | | | **~13 h** compute, plus Jetson setup |

Spread across two devices over 2–3 days of background running. This is the
reason Tiers 2 and 3 use reduced case files — the full 10-case suite
everywhere would roughly double it for no additional claim.

---

## Definition of done

- [x] All eight Phase-0 changes landed
- [ ] Condition A verified to produce `fabrication ≈ 100%` on tool cases
- [ ] `serve_llama_cpp.sh` so condition B's MTP/thinking labels cannot
      disagree with how the server was launched
- [ ] 20 Tier-1 runs complete on both devices (or Pi-complete + documented
      Jetson gap)
- [ ] 32 Tier-2 runs complete, MTP sign compared across devices
- [ ] 4 Tier-3 runs complete
- [ ] `report.py t1 t2 t3 t4` produces all four tables from `results/`
- [ ] Every `n/a` cell has a one-line reason in the writeup
