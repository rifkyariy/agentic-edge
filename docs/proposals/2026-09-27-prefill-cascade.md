# Proposal: a decode-free first pass, with escalation

**Status:** proposal, nothing run yet. Condition slot `E` (`engine: proposed`)
already exists in `benchmark/conditions/`; this is a candidate for what goes in it.

## 1. The observation

Three numbers out of our own baseline grid (`findings/export/`, 1,200 answers,
both boards, matched serving flags) motivate this. None of them are from the
literature.

**Decode dominates, overwhelmingly.** Median per question:

| | prefill | decode | ratio |
|---|---|---|---|
| Pi 5, E2B | 5.2 s | 65.3 s | **12.6×** |
| Pi 5, E4B | 8.7 s | 151.2 s | **17.4×** |
| Orin, E2B | 0.4 s | 21.1 s | **49.1×** |
| Orin, E4B | 0.8 s | 44.7 s | **57.5×** |

Prefill is compute-bound and both boards are good at it — the Orin prefills at
~470 tok/s. Decode is memory-bandwidth-bound and both are bad at it: 3.4 tok/s
on the Pi for E4B. **The entire Pi-versus-Orin gap we measured is a decode
gap.** Anything that moves work from decode to prefill collapses it.

**Runaway generation is the single worst line item.** Questions that reach the
2,048-token answer cap, Pi, n=300 per model:

| | share of questions | share of energy | accuracy |
|---|---|---|---|
| E2B | 8% | **25%** | **4%** |
| E4B | 9% | **26%** | **7%** |

A twelfth of the questions eat a quarter of the energy budget and are wrong
~95% of the time. They cluster in chemistry, engineering and physics — the
model enters a loop and never emits `answer is (X)`. Separately, 7–8% of all
answers yield no extractable letter at all.

**The answer set is closed.** MMLU-Pro is 10-way multiple choice. We are paying
for open-ended generation to select one of ten tokens.

## 2. The method

A three-tier cascade in which **the default path never runs the decode loop**.

**Tier 0 — decode-free scoring.** One forward pass over the prompt; read the
answer distribution over the ten option letters directly from the head rather
than generating. Cost ≈ prefill, i.e. 0.4–8.7 s against 21–151 s. Emit the
argmax and the top-2 margin.

**Gate.** Accept Tier 0 when the margin exceeds τ. Otherwise escalate.

**Tier 1 — bounded chain of thought.** Generate with a hard budget well under
the cap (median generation today is 460–524 tokens, so ~512 covers most
questions that finish naturally). On budget exhaustion, do not truncate into a
non-answer — fall back to Tier 0 scoring conditioned on the partial reasoning.

**Tier 2 — full CoT.** Current baseline behaviour, reserved for whatever is
still ambiguous.

The design target is not accuracy. It is **accuracy per joule**, which our
harness already measures in the same run as accuracy. Tier 0 alone should not
beat full CoT on accuracy; the claim is that the cascade reaches comparable
accuracy at a fraction of the energy, and that the fraction is large enough to
change what is deployable on a Pi.

Two properties fall out for free:

- **Runaway generation becomes structurally impossible.** There is always a
  terminal scoring step, so the 25% of energy currently spent on 95%-wrong
  answers is recovered by construction, not by tuning.
- **Every answer has a letter.** The 7–8% extraction failures disappear, since
  Tier 0 selects from the allowed set rather than hoping the model formats its
  conclusion parseably.

## 3. Where this sits in the literature

**Jev** (arXiv 2609.24965; architecture analysis by Archer Hume) is the closest
precedent and the strongest evidence that Tier 0 is viable: not autoregressive,
a single forward pass with a classification head over the allowed answers,
shared context encoded once and reused via KV cache, question branches
evaluated in parallel, probabilities read from internal representations rather
than generated as text. Reported: ~1,500 questions over a shared context in a
few hundred milliseconds, and the lowest median latency among the twelve
configurations its evaluation compared. Our contribution would not be the
architecture — it would be *quantifying it on measured edge hardware against a
matched autoregressive baseline, in joules*, which that evaluation does not do.

**It's All in The [MASK]** (arXiv 2502.03793) supports the accuracy side: a
masked-LM head used for generative classification, with ModernBERT-Large-Instruct
reaching 93% of Llama3-1B's MMLU at 60% fewer parameters and beating similarly
sized LLMs. Direct option readout is not obviously a large accuracy sacrifice.

**To CoT or not to CoT** (arXiv 2409.12183) is the justification for routing
rather than abolishing CoT: chain of thought helps mainly on mathematical and
symbolic problems and much less on knowledge tasks. MMLU-Pro is a mixture of
both, so a fixed policy is the wrong shape and a per-question gate is the right
one.

**LLMs Are Not Robust Multiple Choice Selectors** (arXiv 2309.03882) is the
main *threat* to Tier 0, not support for it — see §5.

**General-Reasoner, Nemotron-CrossThink, RLPR, MAmmoTH2** are training-time
methods for improving reasoning. They are orthogonal to an inference-time
cascade and out of scope for paper 1, which changes no weights. Worth citing as
the complementary axis; worth resisting as scope creep.

**A discrepancy to resolve.** The LAYA reference does not line up. arXiv
2511.12723 is a layer-attention *output head for image classification*, whose
contribution is intrinsic interpretability through layer-attribution scores —
not the non-autoregressive decision model the dev.to article describes. Either
the arXiv ID is wrong, or the GitHub project and the paper are different work.
Resolve before citing, because the interpretability angle and the
non-autoregressive angle are separate claims.

## 3a. Jev-like or [MASK]-like — the two flows

Both remove the decode loop. They differ in *whose weights answer the question*,
and that difference decides whether this is still a Gemma-on-edge paper.

### Flow A — Jev-like: read the answer off Gemma itself

```
prompt (question + 10 options + "The answer is (")
  |
  +-- ONE prefill over Gemma 4 E2B/E4B                    ~0.4-8.7 s measured
  |
  +-- read the distribution over the ten letter tokens at the next position
  |     -> argmax = answer,  top-2 margin = confidence
  |
  +-- margin > tau ? ---- yes --> done. no decode loop ran.
         |
         no
         |
  +-- Tier 1: bounded CoT (<= 512 tok), then re-read the distribution
  +-- Tier 2: full CoT
```

Same weights we have already benchmarked. No second model, no training, no
change to what the paper is about. The cost is that Gemma is a decoder that was
never trained to be read this way — §5's central risk.

### Flow B — [MASK]-like: a separate encoder answers

```
prompt --> ModernBERT-Large-Instruct (~0.4 GB), MLM head
             -> distribution over the ten options, one forward pass
             -> escalate to Gemma + CoT when unsure
```

Cheaper still, and 2502.03793 reports this class beating similarly sized LLMs
on MMLU. But it is a **different model answering the question**, which breaks
paper 1's scope — "Gemma 4 E2B and E4B on a Pi 5 and an Orin Nano" becomes a
study of something else. It also needs instruction-tuning we have not done, and
a second model resident on a board where E4B already leaves 165 MB of headroom.

### Recommendation: Flow A, with B held in reserve as the *router*

Flow A for the answering path, on four grounds: it keeps the paper's scope, it
needs no training, it adds nothing to the memory ceiling that already killed two
runs, and a crude version of it is measurable today (below).

Flow B is the better *gate* if the top-2 margin turns out to be poorly
calibrated — a small encoder deciding "does this question need CoT?" is exactly
a classification task, it never answers anything, and it keeps Gemma as the only
thing producing answers. That is a fallback for a specific failure, not the
opening move.

## 3b. What the engines can actually do

Checked on the boards, 2026-09-27, rather than assumed.

**Neither engine exposes token probabilities today.**

- **llama.cpp** (Jetson build `a894dae`): `/v1/chat/completions` accepts
  `logprobs: true, top_logprobs: 10` and returns the field **absent**;
  `/completion` and `/v1/completions` are **not routed** in this build. So the
  full Flow A needs engine work regardless of which engine we pick.
- **little-gemma**: the socket returns decoded text only (`lg_openai_shim.ask`
  reads until `<turn|>` or a stop string). No probability channel either.

**little-gemma is nonetheless the better host for it.** We already carry
`little_gemma/agentic-edge.patch` against its `src/run.c` — we have changed
`SERVE_GEN`, added a `-raw` prompt path, and moved it to whole-prompt
tokenisation. Adding a frame that emits the top-k logits at the final position
is the same kind of change, in a small C codebase we already own, with a patch
pipeline and a byte-for-byte template test (`tests/test_lg_shim.py`) already
guarding it. Patching llama.cpp means carrying a fork of a much larger upstream.

**And a crude Flow A needs no engine work at all.** Constraining the model to
emit only the letter is decode-free in every way that matters — 3 tokens instead
of ~500. Measured on the Jetson, E2B, one chemistry question from the suite:

| | wall time | output | answer |
|---|---|---|---|
| letter-only | **11.0 s** | 3 chars | `(C)` — correct |
| full CoT | **148.7 s** | 5,372 chars | `The answer is (C).` — correct |

**13.5× faster, same answer, on the faster board.** This is not the method — it
has no confidence signal, so there is nothing to gate on, and one question is an
anecdote rather than a result. But it means the expensive half of the hypothesis
is testable on the existing harness this week, with no patch: run the full grid
letter-only, and compare accuracy and joules against the baseline we already
have. If letter-only holds accuracy within a few points, the logit work is
justified. If it collapses, we learn that cheaply.

## 4. How to evaluate it here

The harness needs no new measurement apparatus — accuracy and device cost
already come out of the same run.

- Same subsets (`s1`/`s2`/`s3`), same weights, same boards. Only the decode
  policy changes, which keeps AGENTS §5's "only the device differs" invariant
  intact in spirit: only the condition differs.
- Baseline is the grid we already have. The comparison is **paired over the
  same 600 questions per model**, McNemar for accuracy, as in `findings/RESULTS.md` §7.1.
- Primary metric: **J per correct answer**, and accuracy at matched energy.
  Secondary: tier-hit distribution, and the τ sweep as an accuracy/energy curve.
- Report the τ=∞ point (always escalate, i.e. the baseline) and τ=0 (never
  escalate, pure Tier 0) as the two ends, so the curve is bounded by measured
  facts rather than a single chosen operating point.

Cheapest falsification first, before any implementation: **run Tier 0 offline on
the 1,200 answers we already have.** Score the ten options for every question
with the existing GGUFs and compare against the recorded correctness. If pure
Tier 0 accuracy is catastrophic, the cascade cannot be rescued by gating and the
proposal dies for the cost of an afternoon.

## 5. What would sink it, stated up front

- **Selection bias.** arXiv 2309.03882 shows models carry a positional/token
  prior over option IDs, which direct scoring exposes far more than generation
  does. Mitigation is cyclic permutation of the options and averaging, which
  multiplies prefill cost — affordable at 12–57× headroom, but it must be
  measured, not assumed, and it partly erodes the saving.
- **The short-answer evidence is confounded.** Short answers correlate with
  equal or better accuracy on knowledge subjects in our data (psychology 68%
  vs 50%, health 83% vs 57%, economics 88% vs 65%), but the model writes short
  answers *when it is already confident*. This is not evidence that forcing
  brevity preserves accuracy. Only the Tier 0 offline test settles it.
- **llama.cpp may not expose what Tier 0 needs.** Reading a calibrated
  distribution over specific continuation tokens may require logit access the
  server does not offer, pushing this to `little-gemma` or the shim — which is
  an engine change, and the engine axis is already undecided.
- **Gemma 4 is not Jev.** Jev appears purpose-built with a trained prediction
  head. Reading option probabilities off a decoder-only model not trained for it
  is a weaker proposition, and the gap between those two is the real risk.
- **Calibration.** The whole cascade rests on the top-2 margin meaning
  something. If the margin is uncalibrated the gate routes randomly and the
  method degenerates to either the baseline or Tier 0.

## 6. If it works, the claim

Not "our method is more accurate". The defensible claim, and the one our
apparatus can actually support, is:

> On memory-bandwidth-bound edge hardware, the autoregressive decode loop — not
> the model — is what makes on-device reasoning expensive. Moving answer
> selection into prefill recovers most of that cost at comparable accuracy, and
> the effect is larger on the accelerator (57× prefill:decode) than on the CPU
> board (13×), which inverts the usual assumption that a GPU is what you add
> when you want to generate faster.
