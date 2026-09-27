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

## 4. K and the threshold: a frontier, not a single point

All five rotations exist, so K and the agreement threshold can be swept
offline. Cheapest rotation set shown per configuration:

| K | threshold | kept | kept accuracy | cascade | energy | saving | McNemar vs CoT |
|---|---|---|---|---|---|---|---|
| 4 | unanimous | 44 | 68.2% | 58.0% | 17.01 Wh | 20% | p = 0.688 |
| 4 | ≥3 of 4 | 61 | 57.4% | 56.0% | 14.87 Wh | 30% | p = 1.000 |
| 5 | ≥4 of 5 | 50 | 64.0% | 55.0% | 16.98 Wh | 21% | p = 1.000 |
| 5 | ≥3 of 5 | 71 | 53.5% | 54.0% | **12.50 Wh** | **42%** | p = 0.804 |
| 5 | unanimous | 40 | 70.0% | 58.0% | 19.12 Wh | 11% | p = 0.688 |

Two things fall out.

**More rotations is not better.** K=5 unanimous is strictly worse than K=4
unanimous — same accuracy, more energy — because a fifth vote makes unanimity
rarer (40% kept against 44%) and every question that drops out gets escalated
at full CoT cost. The extra pass is paid twice.

**Every row above reads as "tied with CoT", and that is a warning, not a
finding.** At n=100 the test cannot separate 54% from 58%; all it says is that
nothing here is *detectably* worse. Choosing K=5/≥3 for its 42% saving
*because* it happens to be both cheapest and non-significant would be
selecting an operating point on noise — the cherry-pick the methodology
invariants exist to prevent.

So the defensible statement from this run is the range, not a point:
**the cascade matches CoT within the resolution of n=100, somewhere between 11%
and 42% cheaper depending on a configuration this data cannot choose.**
Picking K and the threshold needs s2 and s3, and should be done once on the
pooled set rather than per subset.

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
- **K and the threshold are unchosen.** r8 has since finished and the sweep is
  in §4: K=5 unanimous is worse than K=4, and the cheapest tied configuration
  cannot be selected from this data without cherry-picking.
- **E2B only, Pi only.** The Orin's prefill is 13× cheaper relative to decode,
  so the same cascade should look considerably better there — untested.
- **The 44% kept fraction is what drives the saving.** If a harder subset
  pushes unanimity down, the cascade converges on plain CoT plus the cost of K
  wasted passes. That is the failure mode to watch, and it is why s2/s3 matter
  more than K=5 does.
