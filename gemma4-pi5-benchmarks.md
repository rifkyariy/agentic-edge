# Gemma 4 on a Raspberry Pi 5: little-gemma vs llama.cpp

> **Note:** this is the Sep-14 single-box engine comparison and it predates the
> MMLU-Pro subset protocol — its serving flags are whatever is recorded in the
> sections below, not the current baseline. The benchmark suite's baseline now
> serves with `-rea off --reasoning-budget -1 -c 8192 --cache-ram 0` on both
> boards; `-rea` is `--reasoning`, the thinking switch itself, and
> `--reasoning-format` is the separate flag that places the thoughts. See
> AGENTS.md §5.

Two engines × two models, measured on one box the same afternoon. The headline:
**little-gemma's README advantage over llama.cpp is real but CUDA-only, and does
not survive the trip to a CPU-only Pi.** On this hardware llama.cpp is ~6× faster
at decode and ~40× faster at prefill.

```
weights ──► prefill (TTFT) ──► decode ──► tokens/s
              ▲                    ▲
        llama.cpp 40× ahead   llama.cpp 6× ahead
```

## The machine

| | |
|---|---|
| board | Raspberry Pi 5 Model B Rev 1.0, 8GB |
| SoC | BCM2712, 4× Cortex-A76 @ 2.4GHz (`cortex-a76+crc+crypto`) |
| OS | Debian 13 trixie, aarch64, kernel 6.x |
| governor | `performance`, pinned for all runs; `throttled=0x0`, 56°C |
| threads | 4 |
| GPU | none usable — VideoCore VII, no CUDA |

Both engines built from source on the box. little-gemma is the CPU `run` target
(CUDA targets self-skip: *"CUDA not found — skipping run-cuda"*). llama.cpp is
`b661643e` with `GGML_NATIVE=ON`, so NEON is live.

## Decode (tokens/s, batch 1, greedy, speculation off)

The number that matters in use.

| model | params | size | little-gemma | llama.cpp | ratio |
|-------|-------:|-----:|-------------:|----------:|------:|
| E4B QAT UD-Q4_K_XL | 7.46 B | 3.91 GiB | 0.73 | **4.36** | **5.97×** |
| E2B QAT UD-Q4_K_XL | 4.63 B | 2.43 GiB | 1.48 | **8.57** | **5.79×** |

## Prefill (tokens/s) — the gap that actually hurts

| model | little-gemma | llama.cpp | ratio |
|-------|-------------:|----------:|------:|
| E4B QAT | 0.84 | **36.27** | **43.2×** |
| E2B QAT | 1.77 | **73.34** | **41.4×** |

Prefill is where little-gemma's CPU path falls apart, because it walks the prompt
token-by-token while llama.cpp batches it into a NEON GEMM. In wall-clock terms,
for a 13-token prompt:

| | time to first token |
|---|---:|
| little-gemma + E4B | **15.4 s** |
| llama.cpp + E4B | ~0.4 s |

A 500-token system prompt costs little-gemma **~10 minutes** per call and
llama.cpp ~14 seconds. This, not decode, is what makes the CPU backend feel
broken in interactive use.

## MTP speculative decoding — a GPU-only win

little-gemma's README reports large MTP gains. On this CPU, MTP is a **net loss**
at every content type, despite healthy draft acceptance:

| config (E4B QAT) | acceptance | decode | vs plain |
|------------------|-----------:|-------:|---------:|
| plain, prose | — | **0.73** | 1.00× |
| +MTP, prose | 54.2% | 0.70 | 0.96× |
| plain, structured | — | **0.73** | 1.00× |
| +MTP, structured | 54.0% | 0.71 | 0.97× |

Compare the README's Jetson Orin NX figures for the same model and head:

| device | plain | +MTP chat | +MTP structured |
|--------|------:|----------:|----------------:|
| Jetson Orin NX (README) | 20.7 | **29.9** (1.44×) | **48.6** (2.35×) |
| **Pi 5 CPU (measured)** | 0.73 | **0.70** (0.96×) | **0.71** (0.97×) |

**Why it inverts.** Acceptance is not the problem — 54% here is *better* than the
25% seen before the compiler-flag rebuild. The problem is verify cost: **1,427 ms
per round, flat**, against a draft costing 12 ms. On a GPU, verifying a block of N
draft tokens is nearly free — the tensor cores were idle anyway, so N positions
cost about what 1 costs, and every accepted draft is pure profit. On 4 saturated
CPU cores there is no idle width to hide in: verifying N tokens costs ~N× one
token, so you pay full freight for each token whether you guessed it or not, plus
the draft overhead. Speculation needs spare parallelism, and a CPU decode loop has
none.

## Why the README's claim doesn't transfer

The README is not wrong; it is scoped, and the scope excludes this machine.

- **Every README performance number is CUDA.** Jetson Orin NX and RTX A5000/PRO
  4500, running `run-cuda-i8` — int8 plus tensor-core flash-attention prefill.
  The 1.08–1.11× decode win over llama.cpp is *that* backend against llama.cpp's
  CUDA backend. A Pi 5 has no CUDA, so none of it applies.
- **The CPU backend is a teaching path, by design.** `docs/design-notes.md` is
  titled in part "why no SIMD" — little-gemma writes no SIMD intrinsics
  deliberately, to stay readable. The CPU target is 4,908 lines against 9,746 for
  the shipped int8-CUDA build.
- **The project's own CPU table already says so**, and is honest about it:
  little-gemma 1.3 tok/s vs llama.cpp 2.33 tok/s — but note that row is measured
  with **llama.cpp's SIMD switched off**, for a scalar-vs-scalar comparison. Turn
  NEON back on, which is how anyone actually runs it, and the gap widens to the
  ~6× measured here.

So the fair summary is: little-gemma is 1.08–1.11× *ahead* of llama.cpp where it
is meant to run, and ~6× behind where it is not.

### The paper is explicit about all of this

`paper/fluent_and_cohesive.pdf` (Tan & Tan, *Fluent and Cohesive: Sub-Second Voice
Interaction with General-Purpose Open-Weight Models on a 20-Watt Edge Device*,
July 2026) scopes the claims more tightly than the README does, and concedes its
losses:

- It calls little-gemma **"not a llama.cpp competitor"** (§2), and names llama.cpp
  the gold-standard general local runtime whose throughput is the reference they
  benchmark against.
- Every figure is qualified *on the same Orin* / *on the same board* — Jetson
  Orin NX 16GB, plus an RTX A5000 and a datacenter card. **"Raspberry" appears
  zero times in the paper.**
- It reports where it **loses**: 0.92× against llama.cpp's most-tuned q4_0 path on
  E2B, and 0.82–0.86× of llama.cpp's prefill.
- Its stated design point is *TTFB*, not tokens/s — explicitly a different race —
  won via an appendable conversation abstraction, speculation tuned for short
  structured replies, and a raw-token stream for downstream clause flushing.
- Architecturally it assumes CUDA: piper runs on the CPU precisely because the GPU
  is reserved for the LLM.

**Nothing in the repo's claims is contradicted by this report.** The claims are
CUDA-backend claims; this report measures the CPU backend, on a board the project
never targeted, where CMake itself prints *"CUDA not found — skipping run-cuda"*.
The two sets of numbers do not overlap in scope.

### What the paper implies for voice on a Pi 5

The paper's headline technique is **prefill-under-speech**: process the prompt
while the user is still talking, so prefill costs nothing by the time they stop.
That requires prefill to outrun speech. For a 30-second utterance (~100 tokens):

| engine | prefill 100 tokens | hides under 30s of speech? |
|--------|-------------------:|---|
| little-gemma (Pi 5 CPU) | ~119 s | **no** |
| llama.cpp (Pi 5 CPU) | ~2.8 s | yes |
| little-gemma (Orin, paper) | ~0.2 s | yes |

The technique transfers to a Pi 5 — but only on top of llama.cpp's prefill. At
0.84 tok/s there is nothing to hide.

## What did help little-gemma: compiler flags

Upstream applies `-ffast-math` only to `media.c` (the vision encoder), so the
q4_0 dot-product reductions in `src/cpu/model-cpu.c` never auto-vectorize — GCC
cannot reassociate an FP reduction without permission. Granting it:

```
cmake -S . -B build-fast -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_FLAGS="-mcpu=native -ffast-math -funroll-loops"
```

| build (E4B QAT) | prefill | decode |
|-----------------|--------:|-------:|
| stock `-O3` | 0.55 | 0.48 |
| `-mcpu=native -ffast-math -funroll-loops` | **0.84** | **0.73** |
| gain | 1.53× | **1.52×** |

Output was byte-identical on every prompt tried. Measured and rejected: `-flto=4`
(no change), `OMP_PROC_BIND`/`OMP_PLACES` pinning (no change), MTP (above).
"No SIMD intrinsics" turns out not to mean "no SIMD" — it means the vectorization
was left to the compiler, and the compiler needed the flags.

## Model choice: E2B vs E4B

Within either engine, E2B is ~2× E4B's speed for 1.6× fewer parameters:

| engine | E4B | E2B | speedup |
|--------|----:|----:|--------:|
| little-gemma | 0.73 | 1.48 | 2.03× |
| llama.cpp | 4.36 | 8.57 | 1.97× |

**Quality was not measured here** — this is a throughput report only. E2B is the
smaller model and should be expected to be weaker at reasoning, long-context work,
and code; whether that trade is acceptable is a per-application judgment, not
something these numbers answer.

## A third engine: LiteRT-LM

[LiteRT-LM](https://github.com/google-ai-edge/LiteRT-LM) is Google's own
production edge runtime — the one behind Gemini Nano in Chrome and Pixel Watch —
and Gemma 4's E-series was co-designed with it. It runs on Pi 5 aarch64, and
install is two pip packages, no Bazel:

```
python3 -m venv ~/litert-venv
~/litert-venv/bin/pip install litert-cli litert-lm
litert-lm benchmark --from-huggingface-repo litert-community/gemma-4-E4B-it-litert-lm \
  gemma-4-E4B-it.litertlm -p 256 -d 256 --cpu-thread-count 4
```

Models ship as `.litertlm` bundles from the `litert-community` org, with per-SoC
variants (Tensor G5/G6, Intel LNL/PTL, Qualcomm); the unsuffixed file is the
portable CPU one. **Note the PyPI package is `litert-lm`** — the CLI's own error
message tells you to install `litert-lm-cli`, which does not exist.

### All three engines, matched at 256/256

| engine | model | prefill t/s | decode t/s |
|--------|-------|------------:|-----------:|
| little-gemma | E4B | 0.85 | 0.73 |
| llama.cpp | E4B | 31.69 | 3.67 |
| **LiteRT-LM** | E4B | **48.78** | **3.73** |
| little-gemma | E2B | 1.77 | 1.48 |
| llama.cpp | E2B | 66.55 | 8.22 |
| **LiteRT-LM** | E2B | **118.84** | **8.30** |

LiteRT-LM vs llama.cpp: **1.54× prefill on E4B, 1.79× on E2B, and a dead tie on
decode** (1.02× / 1.01×). Google's marketing claims 1.8–3.7× over llama.cpp; the
prefill half of that reproduces here almost exactly, the decode half does not.

Decode parity is unsurprising — decode is memory-bound, both engines read the same
quantized weights through the same LPDDR4X, and neither can conjure bandwidth.
Prefill is compute-bound and therefore winnable, which is where LiteRT's XNNPACK
kernels pull ahead.

> **Methodology note.** Prefill throughput rises steeply with prompt length,
> because batching amortizes the weight loads. LiteRT-LM E2B measured 26.95 t/s at
> `-p 32` and 118.84 t/s at `-p 256` — the *same engine and model*, 4.4× apart.
> Any prefill number quoted without its prompt length is meaningless. The earlier
> sections of this report used 32-token prefill; this section re-measures
> everything at 256 for comparability.

### Speculative decoding loses on CPU — on every engine tested

| engine | model | spec off | spec on | effect |
|--------|-------|---------:|--------:|-------:|
| little-gemma (MTP) | E4B | 0.73 | 0.70 | 0.96× |
| LiteRT-LM | E4B | 3.73 | 2.58 | **0.69×** |
| LiteRT-LM | E2B | 8.30 | 4.53 | **0.55×** |

Three independent implementations, same direction. Google advertises MTP at 1.6×
(E2B) and 2.2× (E4B); on this CPU it *halves* throughput. The structural reason
given earlier holds generally: speculation trades spare parallel width for
latency, and a CPU with all four cores already saturated by a single token's
matmul has no spare width to trade. **Turn speculative decoding off on Pi-class
CPU hardware regardless of engine.**

## Verdict

| want | use |
|------|-----|
| fastest local text on this Pi | **LiteRT-LM + E2B** — 8.30 decode, 119 prefill |
| best voice responsiveness (TTFB) | **LiteRT-LM** — prefill is the TTFB lever, and it wins it 1.5–1.8× |
| E4B quality at best speed | **LiteRT-LM + E4B** — 3.73 decode, 48.8 prefill |
| maximum flexibility / quant choice | **llama.cpp** — decode-tied, far more knobs and formats |
| to run little-gemma specifically | **E2B + the tuned build** — 1.48 tok/s, speculation off |
| little-gemma's actual advantage | **a CUDA box** — Jetson/RTX, where it is 1.08–1.11× ahead |

For conversational voice, ~10 tok/s is where streaming TTS stops feeling broken.
**LiteRT-LM + E2B (8.30)** and llama.cpp + E2B (8.22) both sit just under it;
clause-splitting and streaming TTS close the rest of the perceptual gap. E4B on
either engine (~3.7) is workable only with aggressive clause flushing.

The deciding factor for voice is **prefill, not decode**, because prefill-under-
speech hides the prompt cost entirely — and only if prefill outruns speech. A
30-second utterance (~100 tokens):

| engine + model | prefill 100 tokens | hides under speech? |
|---|---:|---|
| LiteRT-LM E2B | 0.84 s | yes, comfortably |
| llama.cpp E2B | 1.50 s | yes |
| LiteRT-LM E4B | 2.05 s | yes |
| llama.cpp E4B | 3.16 s | yes |
| little-gemma E4B | 118 s | no |

## Response quality

Speed is only half the trade. All configs run greedy (`temperature 0`), thinking
disabled (`--reasoning off`), same prompts, scored by hand.

### General set (10 prompts: arithmetic, logic, factual, code, JSON, refusal, translation, summary)

| config | score | what it got wrong |
|--------|------:|-------------------|
| llama.cpp + E4B (GGUF Q4_K_XL) | **9.5/10** | over-answered a translation with options + breakdown |
| LiteRT-LM + E4B (`.litertlm`) | 8.5/10 | one arithmetic slip (31 vs 29); same verbosity |
| llama.cpp + E2B (GGUF Q4_K_XL) | 6.5/10 | **both** arithmetic items; wrapped "JSON only" in a code fence |

### Arithmetic set (10 short multi-step problems, answer-only)

| model | score | failures |
|-------|------:|----------|
| E4B | **9/10** | inverse proportion (said 24, correct 20) |
| E2B | 7/10 | 50−(7×3) → said 25; 36−17 → said 29; 24+23 → said 55 |

Across 20 prompts the pattern is consistent and the failure *modes* differ:

- **E2B's errors are basic computation slips** — it sets the problem up correctly
  then drops or miscomputes a step. It is fine on knowledge, formatting, code, and
  refusal.
- **E4B's single error was a reasoning error** (inverse vs direct proportion), not
  an arithmetic one.
- **Quantization changes answers.** LiteRT-LM's `.litertlm` (3.4GB) and the GGUF
  `UD-Q4_K_XL` (3.91GiB) are the *same model* and disagreed on one arithmetic
  item, with GGUF correct. LiteRT was cleaner on instruction-following though —
  it alone emitted bare JSON with no code fence, and gave the tersest refusal.
- **Nobody followed the translation instruction.** All three answered a
  "translate this" prompt with multiple options plus a vocabulary breakdown.
  Budget for strict output shaping in the system prompt.

> **Statistical caveat.** n=20, single greedy run per config. This is a smoke test,
> not an eval — a one-item difference is inside the noise. The E2B/E4B arithmetic
> gap (3 failures vs 1 across the same items) is the only difference here large
> enough to act on. A real MMLU/GSM8K run would take days at 3.7 t/s on this board.

### Bonus finding: E-series *does* think

little-gemma's `docs/serving.md` states the E4B never opens a reasoning channel.
Through llama.cpp's Jinja template it plainly does — the server returns populated
`reasoning_content`, and an E2B reply consumed its entire 20-token budget on
"Thinking Process: 1. Analyze the Request…" before emitting any answer. llama.cpp
exposes real controls (`--reasoning on|off|auto`, `--reasoning-budget N`) that
work where little-gemma's `-think` is a documented no-op. If you want reasoning
mode on Gemma 4, llama.cpp or LiteRT-LM is how you get it — but note thinking
tokens are decoded at the same 3.7 t/s, so a 200-token thought costs ~54 seconds
before the answer starts.

## Is there a better model for this board?

Checked against [Artificial Analysis](https://artificialanalysis.ai)' Intelligence
Index, restricted to what fits ~5GB at Q4 on an 8GB Pi:

| model | AA Intelligence Index | params |
|-------|----------------------:|--------|
| **Gemma 4 E4B** | **9** | 8B total / 4.5B active |
| Gemma 4 E2B (Reasoning) | 8 | 5.1B / 2.3B active |
| Qwen3 8B (Reasoning) | 8 | 8.19B dense |
| Qwen3 4B 2507 | 7 (est) | 4.02B dense |
| Qwen3 8B (Non-reasoning) | 6 (est) | 8.19B dense |
| Phi-4 Mini | 6 | 3.8B |
| Granite 4.0 H Small | 5 | — |

**Gemma 4 E4B is the highest-scoring model that fits this board.** It beats
Qwen3 8B (Reasoning) while being smaller and faster, and E2B *ties* Qwen3 8B on
a third of the active parameters.

**Qwen3.8 is 27B-only** (released 2026-08-14, ~28B with a vision encoder). At Q4
that is ~16GB — it does not fit in 8GB, and even a 1-bit build would read far too
many bytes per token to be usable here. Qwen3.6's small tier is 35B-A3B, also too
large in total weights. Neither is a candidate.

### Measured: Qwen3-4B-Instruct-2507 vs Gemma 4 E2B

Near-identical file size, so a fair architecture test:

| model | size | prefill | decode | math (10) |
|-------|-----:|--------:|-------:|----------:|
| Gemma 4 E2B | 2.43 GiB | **66.55** | **8.22** | 7/10 no-think, **10/10 +think** |
| Qwen3-4B-2507 | 2.32 GiB | 22.35 | 4.68 | ~6/7 verifiable, 1 clear miss |

E2B wins decode 1.76× and prefill 3.0× at the same footprint, because it activates
2.3B params per token against Qwen3-4B's 4.02B dense. Qwen3-4B also ignored
"reply with the number only" on 4 of 10 prompts and answered 36 where 19 was
correct. **Gemma 4 E2B dominates it on every axis measured.**

### The most useful finding: reasoning is cheap on E2B, expensive on E4B

My earlier quality run disabled thinking, which was unfair to E2B — AA scores it
in *reasoning* mode. Re-run with `--reasoning on`:

| config | math score | output tokens/problem | time/problem |
|--------|-----------:|----------------------:|-------------:|
| E2B, thinking off | 7/10 | ~5 | ~2 s |
| **E2B, thinking on** | **10/10** | ~250 | ~31 s |
| E4B, thinking off | 9/10 | ~5 | ~5 s |

Thinking fixed **precisely** the three items E2B failed (50−7×3 → 29, 36−17 → 19,
24+23 → 47). So on accuracy, **E2B with reasoning beats E4B without it** — and
because E2B decodes 2.24× faster, the ~250 thinking tokens are affordable there in
a way they are not on E4B (the same budget costs ~68s on E4B).

The practical split:

| priority | config |
|----------|--------|
| accuracy, latency irrelevant | **E2B + `--reasoning on`** — 10/10 |
| balanced / interactive | **E4B, thinking off** — 9/10 at ~5s |
| voice (TTFB-bound) | **E2B, thinking off** — 8.22 t/s decode, 66 t/s prefill |

Reasoning is not viable for voice on either model: 250 tokens before the first
speakable word is 30s on E2B, 68s on E4B.

## Untested alternatives worth knowing about

Not benchmarked here — listed so the search is not repeated from scratch:

- **[ik_llama.cpp](https://github.com/ikawrakow/ik_llama.cpp)** — a llama.cpp fork
  focused specifically on CPU prompt-processing throughput. The most likely
  candidate to beat mainline llama.cpp's prefill on ARM.
- **[llamafile](https://github.com/mozilla-ai/llamafile)** — Mozilla's llama.cpp
  wrapper with Justine Tunney's [tinyBLAS matmul kernels](https://justine.lol/matmul/).
  Published gains are mostly x86; an open issue reports *worse* prompt processing
  in some configs, so treat as unproven on ARM.
- **ExecuTorch / ONNX Runtime GenAI** — both have ARM64 quantized paths; neither is
  a natural fit for a `.gguf`-centric workflow.
- **MLC-LLM** — could in principle target the Pi 5's VideoCore VII via Vulkan.
  Unlikely to win: that iGPU shares the same LPDDR4X that already bounds decode.
- **Cactus** — appears in Google's own comparison set; little independent data.

The honest expectation for all of these is that they contest *prefill*, not
decode. Decode on this board is memory-bound at ~8 t/s for E2B and ~3.7 t/s for
E4B, and no engine gets past that without a smaller model or a smaller quant.

## Methodology and caveats

- **llama.cpp**: `llama-bench -p 32 -n 32 -t 4 -r 2`, mean ± stddev over 2 reps.
  Reported as `pp32` (prefill) and `tg32` (decode).
- **little-gemma**: no bench harness exists, so figures are the engine's own
  per-run `prompt:` / `gen:` stats from the `-p` one-shot path, 13–23 token prompts
  and 23–51 token generations.
- **The two workloads are therefore not identical** — 32 tokens vs 13–23 — so
  treat the ratios as order-of-magnitude, not three-significant-digit. Both
  engines' rates were stable across repeats (little-gemma reproduced 0.73 on
  every E4B run), and a ~6× and ~40× gap is far outside that noise.
- Single-turn sessions. little-gemma's `docs/benchmarks.md` warns against reading
  its numbers from one-question sessions, but that caveat is about GPU clock ramp;
  with a pinned CPU governor and no GPU there is no ramp to fall inside of.
- Greedy decoding throughout, `-think 0` on little-gemma (a documented no-op on
  E4B, which never opens a reasoning channel).
- Quantization is matched: both engines ran the same unsloth QAT `UD-Q4_K_XL`
  GGUF files, so this is an engine comparison, not a quantization one.
