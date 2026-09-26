# Two accuracy uses of the answer-scoring primitive

> These are **Use 2** and **Use 3** of the primitive described in
> [`2026-09-27-prefill-cascade.md`](2026-09-27-prefill-cascade.md) — not
> alternatives to it, and not alternatives to each other. See
> [`README.md`](README.md) for the whole structure.

The prefill-cascade proposal targets *accuracy per joule*. These two target
**accuracy**, and both are inference-only — no training, no new model, same
Gemma 4 weights. Each has a ceiling measured from runs already on disk, so
neither is a guess about how much there is to win.

Context: we sit at **E2B 51.7% / E4B 65.7%** against Google's published
**60.0 / 69.4**. The interesting part is that the gap is not obviously
quantization. Most of it is reachable without changing the model at all.

## Use 2 — permutation ensemble: harvest the variance

### The observation

The two boards run identical weights with greedy decoding and score the same
(McNemar p = 0.76 / 1.00). But they pick the **same answer letter on only 71%
of E2B questions and 85% of E4B**. CPU and CUDA arithmetic tip near-ties to
different tokens, which means a large fraction of questions sit on a knife
edge: the model is close to indifferent, and which option wins is close to
arbitrary.

Anything that arbitrary is recoverable. Treating the two boards as two samples
of one model:

| | one board | at least one right | headroom |
|---|---|---|---|
| E2B | 51.7 / 52.7% | **59.0%** | **+6.3 pts** |
| E4B | 65.7 / 66.0% | **70.0%** | **+4.0 pts** |

Two samples. Not five, not ten — two, and they differ only by floating-point
associativity. **E2B's 59.0% ceiling nearly closes the whole gap to Google's
published 60.0%.**

### The flow

```
question + 10 options
  |
  +-- K cyclic permutations of the option order       (K ~ 5)
  |     perm 1: A B C D E F G H I J
  |     perm 2: C D E F G H I J A B   ... etc
  |
  +-- score each permutation                          K prefills
  |     map each result back to the ORIGINAL option identity
  |
  +-- marginalise over positions, not majority-vote
  |     -> debiased distribution over the ten options
  |
  +-- argmax = answer;  agreement across permutations = confidence
```

### Why this is affordable *here* specifically

Permutation multiplies **prefill**, and prefill is the cheap axis on both
boards — 12.6× cheaper than decode on the Pi, 57.5× on the Orin. Five
permutations of a prefill-only pass still cost less than one full CoT
generation. The same trick over full CoT would cost 5× the baseline and be
unaffordable; over prefill it is nearly free. This flow only makes sense if
answer selection has already been moved into prefill — it is the quality
dividend of the efficiency proposal, not an independent idea.

### The literature

arXiv 2309.03882 is the direct support: LLMs carry a positional prior over
option IDs, and permutation with marginalisation (PriDe) is its established
fix. That paper frames it as a bias correction; our data says it is *also* a
variance correction, which is a second reason to expect a gain.

### Risk

**Naive majority voting can amplify the bias rather than cancel it.** If the
model favours position C, permuting and voting elects whatever keeps landing
in C. Marginalising over the position→option mapping is the correct
aggregation and the paper's actual proposal; voting is the trap. This is the
one place the flow can silently do nothing while appearing to work, so the
evaluation must include a permutation-invariance check, not just a score.

## Use 3 — bounded generation with guaranteed extraction: cut the tail

### The observation

On the Pi baseline, a tail of questions produces either a runaway generation
that hits the 2,048-token cap, or output with no extractable answer letter:

| | tail size | tail scores | rest scores | if the tail merely scored like the rest |
|---|---|---|---|---|
| E2B | 26 q (9%) | **4%** | 56% | 56.2% — **+4.5 pts** |
| E4B | 27 q (9%) | **7%** | 71% | 71.4% — **+5.8 pts** |

These are not hard questions the model gets wrong. They are questions where it
enters a loop and never commits, and they are concentrated in chemistry,
engineering and physics. They also burn **25–26% of the total energy budget**,
so this flow pays twice.

### The flow

```
question
  |
  +-- generate with a HARD budget (~768 tok; median today is 460-524)
  |
  +-- did it emit "answer is (X)"?
  |     yes -> done
  |     no  -> do NOT return an unparseable answer
  |            force a constrained choice over the ten options,
  |            conditioned on the partial reasoning already generated
  |
  +-- optional second pass: re-ask the forced ones once, fresh
```

The key move is that **there is always a terminal commit step**. Today a
runaway simply runs out of budget and scores zero; here it is always converted
into a choice, using reasoning the model has already paid for.

### The literature

arXiv 2409.12183 (*To CoT or not to CoT*) is the justification for bounding
rather than extending: chain of thought has sharply diminishing returns
outside maths and symbolic problems, so a long tail of generation is not
buying accuracy. Our own S2 result is stronger evidence than the paper for our
setting — thinking-on cost 20–26% more time and made E2B **worse** on both
boards. Reasoning length is not the lever.

### Risk

**Some of that tail may be genuinely hard questions that would have landed
with more budget.** The 4–7% tail accuracy argues against it, but the forced
answer could also just be a coin flip over ten options — which would still beat
4%, but by luck rather than by reasoning. The honest test is whether the forced
answers beat 10% chance materially, not whether the total goes up.

## How the two relate

They attack different failures and should compose:

| | attacks | ceiling E2B | ceiling E4B | costs |
|---|---|---|---|---|
| Use 2 | near-indifferent answers | +6.3 | +4.0 | K× prefill |
| Use 3 | runaway / no-commit tail | +4.5 | +5.8 | *saves* 25% energy |

They are not additive — some tail questions are also in the disagreement set —
so the combined ceiling has to be measured rather than summed. Use 3 is the
cheaper and more certain of the two, and it is the one that also pays for
itself in energy. **Run Use 3 first.**

## Evaluating both

Same apparatus as everything else: same subsets, same weights, paired McNemar
against the S1 baseline already on disk, accuracy and joules from the same run.

Both can be *estimated offline before any device time*, from the 1,200 answers
already exported:

- **Use 2**: re-score the existing answers under permuted option orders to
  measure how much of the letter disagreement is positional. If the model turns
  out to be permutation-stable, the flow's premise is wrong and it dies free.
- **Use 3**: the tail is already identified in `findings/export/`. The only
  open question is what a forced choice on those 26–27 questions actually
  scores, which needs one cheap pass over them — not a full run.
