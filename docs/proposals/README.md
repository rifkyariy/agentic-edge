# Proposals — how the pieces fit

Two earlier documents used confusingly similar labels ("Flow A/B" and
"Flow 1/2") for two *different* axes, which read as if they were alternatives.
They are not. There is **one primitive and three things built on it**.

```
                    THE PRIMITIVE
        constrained answer scoring: a distribution over
        the ten options WITHOUT a full generation
                           |
         +-----------------+-----------------+
         |                                   |
   (a) off Gemma itself              (b) off a separate encoder
       "Jev-like"                        "[MASK]-like"
   same weights, no training         ModernBERT-class, needs tuning
   RECOMMENDED                       fallback, and only as a router
                           |
                           v
        ============ WHAT YOU BUILD WITH IT ============
                           |
     +---------------------+---------------------+
     |                     |                     |
  USE 1: cascade      USE 2: permutation    USE 3: forced commit
  (efficiency)        ensemble (quality)    (quality)
     |                     |                     |
  cheap tier 0        score K permuted       terminal step when
  then escalate       option orders,         generation runs away
  on low margin       marginalise            or emits no letter
     |                     |                     |
  saves energy        +6.3 / +4.0 pts       +4.5 / +5.8 pts
  ~25% recovered      (E2B / E4B)           (E2B / E4B)
```

**(a) vs (b) is an implementation choice** — whose weights produce the
distribution. Recommendation is **(a)**: it keeps paper 1's scope (with (b) a
different model answers, so it stops being a Gemma-on-edge study), needs no
training, and adds nothing to a memory ceiling that already killed two runs.
(b) is held in reserve as a *router* if the confidence signal from (a) turns
out badly calibrated.

**Uses 1, 2 and 3 are not alternatives either** — they are three payoffs from
building the primitive once. Use 1 is the energy argument, Uses 2 and 3 are the
accuracy argument, and all three share the same implementation.

## Which document is which

| document | covers | in the old labels |
|---|---|---|
| [`2026-09-27-prefill-cascade.md`](2026-09-27-prefill-cascade.md) | the primitive, (a) vs (b), and Use 1 | "Flow A / Flow B" |
| [`2026-09-27-quality-flows.md`](2026-09-27-quality-flows.md) | Uses 2 and 3 | "Flow 1 / Flow 2" |
| [`EXPERIMENT-MATRIX.md`](EXPERIMENT-MATRIX.md) | every condition, done and proposed, with costs | — |

## Why this matters practically

Because the primitive is shared, **the cheapest test covers all three uses at
once.** Constraining the model to emit only the answer letter — no engine patch
needed — tells us whether Gemma can pick an answer without reasoning its way
there. If it can:

- Use 1 has a viable tier 0
- Use 3 has a viable terminal commit
- Use 2 has something cheap enough to run K times

If it cannot, all three fail together, and we learn that for about 3 hours of
device time rather than after an engine fork.

That is why `S4 letter-only` is first in the matrix. It is not a fourth idea —
it is the shared premise of the other three, tested on its own.

## Dependency order

```
S4 letter-only          <- tests the premise, no patch, ~3 h
   |
   +-- if accuracy holds
   |
   v
S5 needs real logits    <- llama.cpp fork (NOT little-gemma: its CPU
   |                       prefill is 41-43x slower, and this is a
   |                       prefill-bound method)
   |
   +-- Use 3 forced commit    cheapest, also saves ~25% energy   -> do first
   +-- Use 1 cascade          the efficiency claim
   +-- Use 2 permutation      the largest accuracy ceiling, but needs
                              marginalisation done correctly or it
                              amplifies positional bias instead
```
