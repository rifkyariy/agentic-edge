# Permutation ensemble: the gate works

**E2B, Pi 5, subset s1, n=100.** K=4 rotations of the option order
(r0/r2/r4/r6), letter-only, majority vote, escalate to full CoT where the
rotations disagree. **No ground truth is used to route** — unlike the oracle,
this is deployable.

## 1. Option order alone moves the score 8 points

| rotation | accuracy |
|---|---|
| r0 | 39.0% |
| r2 | 38.0% |
| r4 | **46.0%** |
| r6 | 43.0% |

Same model, same questions, same greedy decoding — only the order the options
are listed in. That is the selection bias arXiv 2309.03882 describes, and it
is large enough here to be worth correcting on its own.

Majority vote over the four: **44.0%**, against 39.0% for a single pass
(**+5.0**).

## 2. Agreement is a usable gate

| | questions | accuracy |
|---|---|---|
| all 4 rotations agree | 44 (44%) | **68.2%** |
| they differ | 56 (56%) | **25.0%** |
| | | **43.2 point separation** |

This is the signal the cascade needed and the two earlier attempts failed to
find. Instability routing separated *hard* from *easy*, which defeats both
paths. Agreement separates **"the cheap path has this right"** from "it does
not", which is the question that actually matters.

Vote distribution over the 4: unanimous 44, three-way 10, two-way 32, split 14.

## 3. The cascade

Keep the 44 unanimous (ensemble answer, 68.2% right), escalate the other 56 to
CoT (which gets 50.0% of them):

| | accuracy | energy | wall clock |
|---|---|---|---|
| CoT baseline | 56.0% | 21.37 Wh | 181.1 min |
| letter-only, single pass | 39.0% | 1.26 Wh | 9.3 min |
| **cascade, K=4 + escalate** | **58.0%** | **17.01 Wh** | **138.6 min** |
| | +2.0 pts | **−20%** | **−23%** |

**The honest claim is iso-accuracy, not +2 points.** Paired against CoT the
cascade wins 4 questions and loses 2 — McNemar **p = 0.688**. Six discordant
pairs at n=100 says nothing. What the run does support is **matching the
baseline's accuracy for a fifth less energy and a quarter less time**, with a
gate that needs no ground truth.

## What this changes

Three gates have now been tried. This is the first that survives contact:

| gate | result |
|---|---|
| escalate on model instability | 59.0% against E4B's 65.7% — **lost** |
| letter-only alone, no gate | 36.3% against 51.7% — **lost** |
| **agreement across K rotations** | **58.0% against 56.0% at −20% energy** |

The difference is what each one measures. The first two asked how hard a
question is. This one asks whether the cheap answer is stable under a
perturbation that should not change it — and instability there is a property of
the *answer*, not the question.

## Caveats, in order of how much they matter

- **n=100, one subset.** The accuracy claim is a tie, not a win, and the energy
  claim rests on a single 44/56 split that could move. s2 and s3 are needed.
- **K=4, not 5.** r8 was still running; adding it can only help the gate (more
  votes to agree) but will cost another 1.26 Wh per 100 questions.
- **E2B only, Pi only.** The Orin's prefill is 13× cheaper relative to decode,
  so the same cascade should look considerably better there — untested.
- **The 44% kept fraction is what drives the saving.** If a harder subset
  pushes unanimity down, the cascade converges on plain CoT plus the cost of K
  wasted passes. That is the failure mode to watch, and it is why s2/s3 matter
  more than K=5 does.
