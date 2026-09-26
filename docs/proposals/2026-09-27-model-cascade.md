# Proposal: a confidence-gated model cascade

**Reproduce:** `python3 benchmark/analyze_cascade.py --export
findings/export/experiment-full.json --board pi --wh 26.6 50.4`

## Why this one and not the others

little-gemma is the shape of method worth copying: it improves what an edge
device can do, and it does so at the *engine* level. This proposal works one
level up, at orchestration — which is the slot condition `E` was always for —
and it is the only candidate whose ceiling can be measured before building it,
because the project already ran both models over identical questions.

## The result

Pairing E2B and E4B on the same 300 questions per board:

| | Pi 5 | Orin |
|---|---|---|
| E2B alone | 51.7% | 52.7% |
| E4B alone | 65.7% | 66.0% |
| both right | 47.3% | 49.0% |
| **E2B only** | **4.3%** | **3.7%** |
| E4B only | 18.3% | 17.0% |
| neither | 30.0% | 30.3% |
| **oracle cascade** | **70.0%** | **69.7%** |

The models are **not nested**. E2B answers 4.3% of questions that E4B gets
wrong, so a perfect router beats *both* models — 70.0% against E4B's 65.7%, and
above Google's published E4B figure of 69.4%.

And it is cheaper, because escalation is conditional:

| | E2B | E4B | oracle cascade |
|---|---|---|---|
| Pi 5 | 26.6 Wh | 50.4 Wh | **43.9 Wh — 13% less than E4B alone** |
| Orin | 10.9 Wh | 22.5 Wh | **18.6 Wh — 17% less** |
| Orin + little-gemma | 8.2 Wh | 15.9 Wh | **13.7 Wh — 14% less** |

*(Wh per 100 questions, measured. The cascade pays E2B on every question plus
E4B on the 34% a perfect gate escalates.)*

**+4.3 points and 13% less energy, simultaneously.** Most efficiency work
trades one for the other; this does not, because it spends the large model only
where the small one fails.

## The contribution is the gate, not the cascade

Cascading is not new. What the numbers make unavoidable is that **the routing
decision is the entire method**:

| gate | Pi accuracy at the same escalation rate |
|---|---|
| random | **58.3%** |
| oracle | **70.0%** |

An 11.7-point spread. A cascade with a bad gate is worse than just running E4B;
with a good one it beats E4B on both axes. Nothing else about the architecture
matters by comparison, so the paper is about the gate and everything else is
scaffolding.

Two properties make the gate tractable here rather than speculative:

- **It runs on E2B's own output.** The top-2 margin over the ten options is
  exactly the answer-scoring primitive in
  [`2026-09-27-prefill-cascade.md`](2026-09-27-prefill-cascade.md) — so this
  proposal does not need a new mechanism, it needs the one already proposed.
- **It only has to be better than random, not perfect.** The operating window
  is wide: on the Pi the cascade stays cheaper than E4B alone while escalating
  anything under 47% of questions, on the Orin under 52%.

## What makes it an *edge* result

On a server this is a scheduling detail. Here it is a memory problem:

- The Orin holds E4B at a peak of **6,874 MB of 7,485**, with no swap. It
  cannot hold both models resident.
- So a cascade must **swap models**, and load time enters the cost function.
  The Orin's E4B load is seconds; whether that survives a 34% escalation rate
  interleaved question-by-question is an open question, and batching the
  escalated set to amortise one load is the obvious answer.
- Which turns the gate into a **two-pass design**: score everything with E2B,
  collect the escalations, swap once, run E4B over the batch. That is a
  genuinely different system from the request-at-a-time cascades in the
  literature, and the difference is forced by 7.5 GB of shared memory.

## Risks

- **The oracle is not reachable.** 70.0% assumes perfect knowledge of E2B's
  errors. The real question is what fraction of that gap a margin-based gate
  closes, and nothing here answers it. If the margin is uncalibrated the whole
  thing collapses to the random row.
- **The gate's own cost is not free.** If it needs a full E2B generation to
  produce a confidence signal, the cascade pays E2B in full on every question —
  which is what the table above already assumes, so this is priced in. If it
  needs *more* than that, the margin erodes.
- **30% of questions are wrong on both models** and no gate reaches them. The
  cascade's ceiling is bounded well below 100% regardless of how good the
  router is.
- **Swap cost is unmeasured.** Every figure here assumes model loading is free,
  and on the Orin it is not.

## Next step

The ceiling is established. What is missing is a gate, and the cheapest probe of
whether one can exist is to check whether E2B's answer confidence separates its
own correct answers from its errors at all — computable offline from the
exported answers, no device time, no engine patch. If it does not separate,
this proposal reduces to "run E4B" and dies cheaply.
