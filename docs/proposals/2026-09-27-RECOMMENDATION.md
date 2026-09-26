# What to build, and why it does not compete with little-gemma

## The framing mistake to avoid

little-gemma makes **decode faster**. Every method proposed here makes the
system **decode less**. Those are different axes, so the target is not "beat
little-gemma" — it is *little-gemma + method* against *little-gemma alone*.
They multiply. A method that only matched little-gemma by doing the same thing
differently would not be worth the paper.

## The method

**Permutation-consistent constrained decoding, with selective escalation.**

```
question + 10 options
  |
  +-- K constrained passes (K~5), option order cyclically permuted
  |     each emits ONLY the answer letter: ~4 tokens, not ~500
  |     map each back to the original option identity
  |
  +-- marginalise over positions  ->  debiased answer
  |   agreement across the K passes  ->  confidence
  |
  +-- all K agree?  -> accept.  no chain of thought was ever generated
  |
  +-- they disagree -> escalate to one full CoT pass
```

Three measured facts make this the candidate rather than a guess:

1. **Decode is 92–98% of per-question time**, and prefill is 12.6× (Pi) to
   57.5× (Orin) cheaper. Constraining output to four tokens moves the work onto
   the cheap axis.
2. **The model is genuinely unstable**: E2B picks the same letter on only 71%
   of questions across two boards running identical weights greedily. That
   instability predicts error — 63.6% accurate when stable, 22.1% when not.
   So agreement across permutations is a real confidence signal, not a hope.
3. **Aggregating just two samples is worth +6.3 points on E2B** and +4.0 on
   E4B. Permutation is a cheaper way to get samples than sampling is.

## What it would cost

Per question, measured medians:

| | 1× full CoT | 1× letter-only | K=5 letter-only |
|---|---|---|---|
| Orin E2B | 21.5 s | 0.6 s | 3.0 s — **7.1× cheaper** |
| Orin E4B | 45.4 s | 1.1 s | 5.6 s — **8.1× cheaper** |
| Pi E2B | 70.5 s | 5.8 s | 28.9 s — 2.4× cheaper |
| Pi E4B | 159.9 s | 9.9 s | 49.3 s — 3.2× cheaper |

Energy per 100 questions, projected from measured watts:

| | today | K=5 letter-only |
|---|---|---|
| Orin E2B, llama.cpp | 10.9 Wh | ~1.5 Wh |
| **Orin E2B, little-gemma** | **8.2 Wh** | **~1.5 Wh** |
| Orin E4B, little-gemma | 15.9 Wh | ~2.8 Wh |

**Five passes still cost a fifth of one CoT pass.** The energy headroom is not
the constraint. Accuracy is the entire question.

## The honest risk, stated plainly

**MMLU-Pro is built to require reasoning, and roughly half of it is
mathematical or symbolic — exactly where arXiv 2409.12183 says chain of thought
earns its keep.** Letter-only could easily land at 30–40% for E2B against 53%
with CoT. Permutation would recover a few points of that, not fifteen.

If that happens, the pure form dies and the **cascade form is what survives**:
K cheap passes first, escalate the disagreements. Suppose half of questions are
settled cheaply —

- 50% at ~1.5 Wh → 0.75 Wh
- 50% escalated at 8.2 Wh → 4.1 Wh
- **total ≈ 4.9 Wh against little-gemma's 8.2 Wh — ~40% less, at iso-accuracy**

That is the realistic claim, and it is a good one: a **40% reduction on top of
the best engine already measured**, from a decoding strategy that composes with
any engine and any board.

## Why this and not the others

| candidate | verdict |
|---|---|
| more reasoning (thinking-on) | **tested — pure loss.** −1.7 to −3.0 on E2B, +20–26% time |
| cap the generation budget | **tested — bad trade.** −5.6 points for 21% energy |
| abort on detected loops | **tested — catches 2 of 25** |
| route E2B→E4B on instability | **tested — 59.0% vs E4B's 65.7%.** Instability finds hard questions, not rescuable ones |
| **constrained + permutation + escalate** | **untested — and the only one left** |

Four of five candidates were eliminated by measurement on data already on disk.
This is what remains, which is a stronger position than picking it out of the
literature would have been.

## The one experiment that decides it

**S4 letter-only, one subset, Orin, ~1 h.** Not the full grid — one subset
answers it. Constrain the model to emit only the letter, score against the
baseline's recorded answers on the same questions.

- **If letter-only lands within ~10 points of CoT**, the pure form is viable
  and the permutation ensemble is worth building.
- **If it lands 20+ points below**, the pure form is dead and the question
  becomes whether the confident subset is large enough for the cascade to pay.
  That is answerable from the same run: look at accuracy on the questions where
  K passes agree.

Either way one hour of Orin time decides between three outcomes, and no engine
patch is needed to get there. Everything else — the logit margin, the fork, the
full grid — waits behind it.
