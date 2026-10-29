# PRD: Edge Tool-Calling Experiment — Code Mode × TurboQuant on Gemma 4

**Status:** Draft v2 **Date:** 2026-10-28 **Devices:** NVIDIA Jetson Orin Nano (now); RTX 4090 server (later, accuracy only) **Benchmark basis:** *The Bitter Lesson of Tool Calling* (arXiv 2608.06370), extended for long-context pressure

***

## 1. Summary

This experiment compares two ways a small on-device model can call tools, and asks whether a compressed KV cache changes the comparison:

* **JSON tool calling**: the model emits one JSON tool call per turn through the chat template.
* **Cloudflare-style Code Mode**: the model writes a script against a typed tool API, and the script makes the calls.
* **TurboQuant**: KV-cache compression that lets more context fit in a fixed amount of memory.

Code Mode reduces how much context a task consumes: tool outputs stay in the script, not in the prompt. TurboQuant increases how much context fits. The experiment measures when Code Mode beats or loses to JSON, what each interface costs on the edge, and how TurboQuant interacts with both. It runs Gemma 4 E2B and E4B, with and without thinking, on a Jetson Orin Nano 8 GB.

**Motivation.** The Bitter Lesson paper compared code-based ("programmatic") and JSON tool calling on BFCL v4, but only on cloud frontier models, with echo-only stubs that never stress context. No published work tests this on small models running on edge hardware, or combines it with KV-cache compression.

**Prior work in this repository.** S8 (`findings/RESULTS.md` §7.5 on `main`) served MMLU-Pro with the same TurboQuant fork on both boards. On E4B it cost 2.7–5.4 points, significant with thinking on (pooled p = 0.0003). E2B showed no loss. It was also 20–30% slower on the Jetson. S8 is not a tool-calling benchmark: its prompts stayed under 8K tokens, where the boards are not short of KV memory, so it says nothing about long tool-calling contexts. This study measures exactly that.

***

## 2. Goals and non-goals

### Goals

1. Measure Code Mode against JSON tool calling across chaining, fan-out, large tool sets, and large tool outputs.
2. Measure what each interface costs per task on the Jetson: tokens, time, energy, and peak memory.
3. Measure the accuracy cost of TurboQuant against standard KV caches (q8\_0, q4\_0) on tool-calling tasks.
4. Measure the capacity gain from TurboQuant: the maximum context each configuration can run on the Jetson.
5. Measure the interaction between TurboQuant and the interface.
6. Measure the effect of model size (E2B vs E4B) and thinking mode on all of the above.
7. Produce reproducible, version-pinned results.

### Non-goals

* MCP as an experimental factor. MCP is a transport protocol and does not change what the model sees, so it is excluded.
* Raspberry Pi 5, iPhone, MLX, or any other runtime or device.
* Models other than Gemma 4 E2B and E4B.
* Timing or energy on the RTX 4090 server. It is shared with other work, so only its accuracy is used.
* Live MCP servers or external APIs. All tools are local stubs.
* Fine-tuning or training of any kind.
* An official BFCL v4 leaderboard score. Results are reported as **BFCL v4–derived**.

***

## 3. Research questions and hypotheses

**Research question.** For small Gemma models, when does Code Mode beat JSON tool calling, when does it lose, and does the answer hold on edge hardware?

| ID | Question                                                    | Hypothesis                                                                                                           |
| -- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| H1 | Does Code Mode beat JSON on long chains and large outputs?  | Yes, on T1-chaining and T3.                                                                                          |
| H2 | Where does Code Mode lose?                                  | On E2B fan-out, because of broken code. The failure breakdown (Section 10.1) separates code errors from wrong calls. |
| H3 | Does thinking help Code Mode more than JSON?                | Yes. Thinking gives the model room to plan the script before writing it.                                             |
| H4 | Is Code Mode cheaper per task on the Jetson?                | Yes: fewer tokens, less time and less energy per task, including the sandbox.                                        |
| H5 | Does TurboQuant reduce tool-calling accuracy?               | Non-inferior to q8\_0 within the margin (D5) on E2B. E4B may lose, as it did on MMLU-Pro in S8. Tested per model.    |
| H6 | Does TurboQuant increase usable context on the Jetson?      | Yes. It reaches at least one higher context level than q8\_0 for the same configuration.                             |
| H7 | Do TurboQuant and the interface interact?                   | Yes. TurboQuant helps JSON more than Code Mode, because JSON keeps tool outputs in context.                          |

Exploratory, not pre-registered: whether thinking increases TurboQuant's value (thinking adds tokens, and so KV memory), and per-task agreement between the Jetson and the RTX 4090 (Section 9.4).

***

## 4. Experimental design

### 4.1 Factors

| Factor    | Levels                         | Notes                                                                                     |
| --------- | ------------------------------ | ----------------------------------------------------------------------------------------- |
| Interface | JSON tool calling, Code Mode   | The main factor. Both are generated from the same function definitions.                   |
| Model     | Gemma 4 E2B-it, Gemma 4 E4B-it | Instruction-tuned checkpoints only.                                                       |
| Thinking  | off, on                        | Set only with the server's thinking switch, `-rea off\|on` (Section 8.2), never by prompt wording. |
| KV cache  | q8\_0, q4\_0, TurboQuant       | q4\_0 is the control for "any 4-bit KV cache." One TurboQuant setting for the whole study (D1). |

The full matrix is 2 × 2 × 2 × 3 = **24 configurations**, run in stages (Section 9).

Context length is **not** a factor in Part A. The `-c` value only reserves KV memory and does not change what the model computes, so it cannot change accuracy. What can is how many tokens a task actually puts in the context, which is recorded per task and used as a covariate (Section 11).

### 4.2 Two-part evaluation

| Part                 | Purpose                                         | Device    | Setup                                                                                  |
| -------------------- | ----------------------------------------------- | --------- | -------------------------------------------------------------------------------------- |
| **A. Quality and cost** | Accuracy and per-task cost of each factor    | Jetson    | Every configuration at one fixed context size per model, `C_A` (D9)                    |
| **B. Capacity**      | Maximum feasible context, memory, speed         | Jetson    | Each KV type × interface × model at 4K, 8K, 16K, 32K and 64K, up to the first that does not fit |

`C_A` is the largest context at which all three KV types load and finish a full-length prompt, for that model, measured at M1. Tasks longer than `C_A` are listed, recorded as **"does not fit on the Jetson"**, and left out of Part A's accuracy; they run later on the RTX 4090 (Section 9.4). An out-of-memory result in Part B is a capacity result, not missing data.

***

## 5. Workloads

### 5.1 Tiers

| Tier   | Source                                                                       | Size (approx.)       | Context pressure               | Purpose                                         |
| ------ | ---------------------------------------------------------------------------- | -------------------- | ------------------------------ | ----------------------------------------------- |
| **T0** | Bitter Lesson BFCL v4 main subset, rebuilt                                   | 301 tasks            | Low                            | Comparability with the paper                    |
| **T1** | Bitter Lesson chaining (chain length 2–20) and fan-out (7–48 parallel calls) | 52 + 32 tasks        | Medium                         | Code Mode advantage on composition              |
| **T2** | Bitter Lesson context-rot set, flooded with distractor schemas               | 31 tasks × 4 bands   | High, scaling                  | Large tool sets; TurboQuant capacity            |
| **T3** | New: chaining with large stub outputs                                        | \~50 tasks × 4 bands | High in JSON, low in Code Mode | Key interaction between TurboQuant and interface |

**T0–T2 are rebuilt, not copied.** The paper says its entry ID lists are "released with the evaluation harness" but gives no link, and none could be found (checked 2026-10-29). T0 is therefore sampled from BFCL v4 (`bfcl-eval` 2026.3.23) with the paper's per-category counts (Table 6) and a fixed seed, by `toolcall/build_t0.py`. One count cannot be met: `live_parallel` holds only 16 entries, not 24, so it is taken whole and T0 has **301 tasks, not 309**. The sample matches the paper's composition, not its exact entries. T1 and T2 are rebuilt the same way from the paper's descriptions. T2's larger levels and all of T3 are new and must be generated (Section 5.2).

**T2 and T3 are sized by tokens, not by item count.** A BFCL schema is roughly 100–250 tokens, so 512–1,024 schemas would need 50–250K tokens, and 20 tool outputs of 20 KB each exceed 100K tokens in JSON. Both overflow an 8 GB board. Instead, the generators choose the schema count (T2) and stub payload size (T3) so that each task lands in a target band: about **4K, 8K, 16K and 32K tokens**, plus 64K if M1 shows the Jetson can hold it. Token counts are measured with Gemma's own chat template, not estimated.

For T3, the same task falls in a different band per interface, because Code Mode keeps tool outputs out of the context. That is the effect under test, so the band is recorded per task × interface.

### 5.2 Stub design

* **T0–T2:** echo stubs that return their arguments, matching the paper.
* **T3:** stubs return realistic, deterministic payloads, generated from a seed. Later calls depend on values inside earlier outputs, so the model must actually read the tool results.
* Every stub is deterministic. The same input always gives the same output.
* **In T3, both interfaces see the same output description.** Code Mode's TypeScript API declares each tool's return type, and a single-turn script needs it to read earlier outputs it never sees. JSON tool schemas have no return type, so in T3 the same output description is added to each JSON tool's description text, generated from the same function definition. T0–T2 use echo stubs, so their JSON schemas stay exactly as BFCL gives them, keeping T0 comparable with the paper.

### 5.3 Scoring

* Use the paper's deterministic rule: every expected call present with correct arguments. Strings are compared with BFCL's own `standardize_string` (drop spaces and `,./-_*^`, lowercase), the "benchmark's normalized string comparison" the paper names. Numbers compare by value, booleans exactly, and an argument whose acceptable values include `""` or `None` may be left out. The primary score allows extra calls, as the paper's rule does; a strict score that also rejects extra calls (BFCL's rule) is reported beside it (`toolcall/score.py`).
* Score Code Mode from the calls the stubs recorded, not from the model's printed text.
* Syntax or runtime errors in Code Mode count as zero correct calls.
* For fan-out tasks, report **enumeration accuracy** (were all N calls actually made?) as the primary metric, as in the paper.
* No LLM-as-judge anywhere.

***

## 6. Interfaces

### 6.1 JSON tool calling

* Tool schemas are passed via llama-server's OpenAI-compatible `tools` parameter, rendered by the GGUF's chat template (`--jinja`).
* Multi-step tasks use the standard loop: model call → tool result → next model call.

### 6.2 Code Mode

* Tools are exposed as a **typed TypeScript API**, matching Cloudflare Code Mode. This differs from the paper's Python stubs and must be stated in the results.
* The model writes one script per turn. The script runs in a pinned sandbox **on the Jetson**, so its memory counts in the measurements.
* The turn rule must be fixed before Stage 1 (D3):
  * **(a)** one model turn per task, as in the paper, or
  * **(b)** multiple turns allowed, with turns counted for both interfaces.
* The TypeScript API, JSON schemas and stubs are all generated from one source of function definitions, so tool descriptions are identical.

***

## 7. Devices

|               | Jetson Orin Nano (now)                                                                | RTX 4090 server (later)                              |
| ------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Role          | Parts A and B: accuracy, per-task cost, capacity                                       | Accuracy only: a replication subset, and the tasks that do not fit on the Jetson |
| Backend       | TurboQuant fork of llama.cpp, CUDA build (`sm_87`)                                     | The same fork commit, CUDA build (`sm_89`)           |
| Memory        | 8 GB shared CPU/GPU (\~7.5 GB usable)                                                  | 24 GB VRAM                                           |
| Power/thermal | `nvpmodel` 0 (15 W), clocks locked with `jetson_clocks` (in place since 2026-10-07)   | Shared machine: no timing or energy claims           |
| Other load    | The voice agent's `systemd --user` units are stopped for every run                    | Recorded, not controlled                             |
| Monitoring    | `tegrastats` logged throughout; energy per task from the repo's telemetry              | Not needed                                           |

The 4090 server is not set up yet. It joins after the Jetson stages (Section 9.4).

***

## 8. Locked configuration

### 8.1 Software

* **One fork, one commit:** `TheTom/llama-cpp-turboquant` @ `bcb85fc`, the build S8 used. It serves all three KV types, so every comparison runs on the same binary. Only the CUDA architecture differs between devices, and the cmake flags are recorded.
* **One GGUF per model:** `gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf` and `gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf`, the files S1 and S8 used. The SHA256 is verified on each device before every stage.
* **Chat template:** taken from the GGUF via `--jinja`. The template hash is recorded.
* **Sandbox runtime:** one runtime at one pinned version, the same on both devices (D4).

### 8.2 Server launch (identical except for the variables under test)

```
llama-server -m <gguf> --jinja -c <C_A | Part B level> -ngl 99 \
  -ctk <q8_0|q4_0|turbo3> -ctv <q8_0|q4_0|turbo3> -fa on \
  -np 1 -b 512 -ub 512 --cache-ram 0 \
  -rea <off|on> --reasoning-budget <-1|B> [--reasoning-format <F>] \
  --temp 0 --top-k 1 --seed 42 -n <MAX_NEW_TOKENS>
```

* **`-rea` must always be given.** It is `--reasoning`, the thinking switch. Left out, it defaults to `auto` and Gemma thinks. This is the bug that cost the Jetson earlier runs (`AGENTS.md` on `main`).
* Thinking on sets `-rea on` and a budget `B` (D6). The reasoning format `F` is decided in the pilot (D10): `none` matches S8 but leaves the thoughts inline, where they may break JSON tool-call parsing.
* With `-ctk turbo3 -ctv turbo3` the fork raises K to `q8_0` by itself for Gemma 4's 8:1 GQA. The effective cache is **K = q8\_0, V = turbo3**, as in S8. Against the q8\_0 cache, only V is compressed; the results must say so.
* `-np 1` gives one slot the whole context. S1 and S8 ran with the default four slots, so their speeds are not directly comparable.

### 8.3 Run rules

* The TurboQuant types are fixed (D1) and never changed.
* No prompt-cache reuse **between** tasks: every request sends `cache_prompt: false` except those allowed by D8, and `--cache-ram 0` keeps the server from restoring old prompts. Every task starts with an empty cache.
* Reuse **within** a multi-turn task follows D8, the same for both interfaces.
* The server is restarted for every configuration. Its command line is captured from the running process after start-up, not from the launch script, and must match the configuration (the repo's `meta.json` lesson).
* No retries. A fixed per-task timeout applies (D7), and a timeout is logged as its own outcome.
* One warm-up task is run before timing starts.
* `MAX_NEW_TOKENS` is fixed per thinking mode, and thinking tokens count toward it.

### 8.4 Run manifest

Every run writes a manifest containing:

* fork commit hash and build flags
* model SHA256 and chat-template hash
* the full command line, as captured from the running server
* device, power mode, clock lock state, room temperature
* sandbox runtime and version
* harness version, and the task set and its version

Any change to these creates a new experiment version. Results from different versions are never pooled.

***

## 9. Execution plan

### 9.1 Jetson stages (Part A)

The full sweep is roughly 570 tasks × 24 configurations, about 13–14k task runs. Run it in stages so the main result arrives first:

| Stage           | Scope                                                         | Answers                                                 |
| --------------- | ------------------------------------------------------------- | ------------------------------------------------------- |
| **1. Core**     | Thinking off; q8\_0 and TurboQuant; JSON and Code Mode; T0–T3 | H1, H2, H4, H5, H7                                      |
| **2. Thinking** | Thinking on; T1–T3 in full; T0 sampled                        | H3, and H5 with thinking on (where S8 saw E4B lose)     |
| **3. Control**  | q4\_0 KV; T2 and T3 only                                      | Whether TurboQuant specifically beats generic 4-bit KV  |

The M4 pilot projects each stage's run time from measured speeds. If a projection exceeds the time budget (D11), T0 is sampled further before any tier is dropped.

### 9.2 Capacity sweep (Part B)

Answers H6.

* Every KV type × interface × model, thinking off, at 4K, 8K, 16K, 32K and 64K, stopping at the first level that does not fit.
* A fixed handful of T2 and T3 tasks per band, filled to the level, so each level is tested with real prompts and, for Code Mode, a live sandbox.
* Recorded per level: fits or not, peak memory (process plus sandbox), the KV buffer size from the server log, time-to-first-token, and generation speed.

### 9.3 Runner requirements

* Resumable: one log line per task; completed tasks are skipped on restart.
* Restarts the server automatically after a crash, and logs the crash.
* Runs unattended for days.
* Writes logs per task: input token count, output token count, thinking token count, time-to-first-token, generation speed, end-to-end time, energy, peak memory, outcome.
* The job queue on `main` (`benchmark/jobqueue/`) already does resumable runs, prechecks and server fingerprinting; whether to port it or build a smaller runner here is decided at M1.

### 9.4 RTX 4090 (later)

* Runs after the Jetson stages, with the same fork commit, GGUFs, task sets and launch line, at a `-c` large enough for every task.
* Two purposes: the accuracy of the tasks that did not fit on the Jetson, and a replication subset of about 150 tasks across all tiers, compared per task against the Jetson.
* Accuracy only. The server is shared, so none of its timings are reported.

### 9.5 Repetitions

* **Accuracy:** one run per configuration, since decoding is greedy.
* **Timing and energy:** taken from the accuracy run. A fixed timing subset (about 10% of each tier) is run twice more to estimate run-to-run variance; its median is reported.

***

## 10. Metrics

### 10.1 Quality

* Accuracy for each tier and configuration.
* Per-category accuracy for T0, following BFCL categories.
* Enumeration accuracy for fan-out tasks.
* Code Mode failure breakdown: syntax error, runtime error, wrong call, missing call.

### 10.2 Capacity and cost

* Largest context level that fits, per KV type × interface × model.
* Peak memory: process plus sandbox, with the sandbox also reported on its own.
* Time-to-first-token, generation tokens/s, end-to-end seconds per task.
* Energy per task (Wh).
* Tokens per task: input, output, and thinking.
* Derived metrics: accuracy per second, accuracy per Wh, and accuracy at a fixed memory budget.

### 10.3 Reliability

* Timeouts, crashes and out-of-memory events.
* Agreement between the Jetson and the RTX 4090 on the replication subset (later).

***

## 11. Analysis

* **Paired comparisons:** every configuration answers the same tasks, so pairwise differences use **McNemar's test** on per-task pass/fail.
* **Confidence intervals:** 95% Wilson intervals per cell; bootstrap intervals for differences.
* **Non-inferiority (H5):** TurboQuant vs q8\_0, per model, with the margin fixed before any data is collected.
* **Main model:** a mixed-effects logistic regression with main effects for interface, model, thinking and KV type, the pre-registered two-way terms, and context pressure as covariates: `pass ~ interface + model + thinking + kv + interface:thinking + interface:kv + interface:model + log(prompt_tokens) + tier + (1 | task)`. **interface × thinking** tests H3; **interface × kv** tests H7. Higher-order terms are exploratory.
* **Multiple comparisons:** Holm correction across H1–H7. Everything else is reported as exploratory.
* **Small cells:** T1 and T2 cells are small (31–52 tasks). Per-cell results are treated as directional, as in the paper, and conclusions rest on the pooled model.

***

## 12. Open decisions (resolve before Stage 1)

| #   | Decision                              | Options                                                    | Default / status                                                          |
| --- | ------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------- |
| D1  | TurboQuant K/V types                  | —                                                          | **Resolved:** `-ctk turbo3 -ctv turbo3`, effective K = q8\_0, V = turbo3, as in S8 |
| D2  | Weight quantization                   | —                                                          | **Resolved:** the QAT `UD-Q4_K_XL` GGUFs used by S1 and S8                 |
| D3  | Code Mode turn rule                   | (a) one turn, (b) multi-turn with turns counted            | (a), for comparability with the paper                                     |
| D4  | Sandbox runtime                       | workerd, Deno, or another JS runtime, pinned               | Whichever runs reliably on the Jetson's ARM64 and on x86-64               |
| D5  | Non-inferiority margin                | 1–3 percentage points                                      | 2 points                                                                  |
| D6  | `MAX_NEW_TOKENS` and thinking budget  | —                                                          | Set after a short pilot; S8 used a 320-token budget                       |
| D7  | Per-task timeout                      | —                                                          | Set after a short pilot                                                   |
| D8  | Prompt-cache reuse within a task      | Allowed within a task, or never                            | Allowed within a task, the same for both interfaces                       |
| D9  | Part A context `C_A` per model        | —                                                          | Measured at M1                                                            |
| D10 | Reasoning format with thinking on     | `none` (as S8), or a format that separates the thoughts    | Chosen in the pilot by whether JSON tool calls still parse                |
| D11 | Jetson time budget per stage          | —                                                          | Agree with the supervisor before M4                                       |

***

## 13. Risks and mitigations

| Risk                                                                                         | Impact                                               | Mitigation                                                                            |
| -------------------------------------------------------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------- |
| TurboQuant costs E4B accuracy, as it did on MMLU-Pro in S8                                   | H5 fails for E4B                                     | Test non-inferiority per model; report the E4B result either way                      |
| The Jetson's 8 GB cannot hold the longest tasks                                              | Long T2/T3 bands missing from Part A                 | Record "does not fit"; run those tasks on the RTX 4090 later                          |
| Thinking-on output breaks JSON tool-call parsing                                             | JSON penalized for a formatting reason               | Pick the reasoning format in the pilot (D10); log parse failures separately           |
| Code Mode loses because of formatting, not reasoning (e.g. broken newlines, as in the paper) | Code Mode is penalized for the wrong reason          | Log failure types separately; validate the prompt in a pilot                          |
| Run time too long for E4B with thinking on                                                   | Incomplete matrix                                    | Timeouts logged as outcomes; staged plan; time budget per stage (D11)                 |
| The voice agent's services share the Jetson                                                  | Memory and timing contaminated                       | Stop its units for every run; check the captured command line and memory at start     |
| T3 generator creates tasks that are easier in one interface by construction                  | Biased interaction estimate                          | Generate tasks from function definitions only; same output descriptions for both interfaces; review a sample by hand before Stage 1 |
| Errors in BFCL ground-truth labels                                                           | Noise in absolute scores                             | Rely on paired comparisons, not absolute scores                                       |
| Sandbox memory overhead                                                                      | Code Mode capacity looks worse                       | Report sandbox memory separately as well as combined                                  |

***

## 14. Deliverables

1. **Harness, in this repository on the `voice-agent` branch:** runner, scorer, stub and API generators, the T2 and T3 generators, launch scripts, manifest writer.
2. **Task sets:** T0–T3 with version tags and measured token counts per task × interface.
3. **Raw results:** per-task logs and manifests for every run.
4. **Analysis notebook:** tables, figures and statistical tests.
5. **Write-up:** results by hypothesis, the Code Mode vs JSON comparison by tier, per-task cost on the Jetson, capacity curves per KV type, and the TurboQuant × interface interaction plot.

***

## 15. Milestones

| #   | Milestone                 | Exit criterion                                                                                  |
| --- | ------------------------- | ----------------------------------------------------------------------------------------------- |
| M1  | Environment locked        | Fork builds on the Jetson; GGUF hashes match; manifest writer works; `C_A` measured per model   |
| M2  | Harness ready             | T0 rebuilt (done: 301 tasks); scorer passes BFCL's own answers on every T0 task (done); both interfaces run T0 end to end |
| M3  | Generators ready          | T2 and T3 generated to their token bands, counted with the chat template, and hand-reviewed     |
| M4  | Pilot                     | \~20 tasks per tier; D3, D6, D7, D8 and D10 resolved; each stage's run time projected against D11 |
| M5  | Stage 1 complete          | Core matrix on the Jetson                                                                       |
| M6  | Stages 2–3 complete       | Thinking and q4\_0 control runs                                                                 |
| M7  | Capacity sweep complete   | Part B at every reachable level                                                                 |
| M8  | Analysis and write-up     | H1–H7 reported for the Jetson                                                                   |
| M9  | RTX 4090 (later)          | Server set up; the tasks that did not fit and the replication subset run                        |

***

## 16. References

* Patel et al., *The Bitter Lesson of Tool Calling*, arXiv 2608.06370 (2026). Benchmark subsets, scorer, programmatic tool-calling design.
* Patil et al., *The Berkeley Function Calling Leaderboard (BFCL)*, ICML 2025. Source tasks.
* Google Research, *TurboQuant*, ICLR 2026. KV-cache compression method.
* Cloudflare, *Code Mode*, Agents documentation. Interface design.
* Wang et al., *CodeAct: Executable Code Actions Elicit Better LLM Agents*, ICML 2024. Background on code vs JSON actions.
* Vaghasiya et al., *Benchmarking the Benchmarks: A Validity Audit of Tool-Calling Evaluation*, arXiv 2607.02577 (2026). Benchmark validity caveats.
* This repository, `findings/RESULTS.md` §7.5 on `main`: S8, MMLU-Pro with the TurboQuant fork on the Pi 5 and the Jetson.
