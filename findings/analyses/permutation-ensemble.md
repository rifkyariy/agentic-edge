# Permutation ensemble at n=300: the s1 result does not replicate

**E2B, Pi 5, all three subsets pooled, K∈{2,3,4}, four rotation sets.**
Supersedes the single-subset read (n=100, s1), kept unchanged as the
[appendix](#appendix-the-s1-only-read-n100-superseded) below, which was
explicitly flagged as unpooled and not yet decision-grade. **Cite this pooled
result, not the appendix's +2.0 points.**

## The full sweep

| rotations | thr | kept | kept acc | cascade | Wh | Δ energy | p vs CoT |
|---|---|---|---|---|---|---|---|
| r0+r2 | 2 | 60% | 46.9% | 46.7% | 11.14 | 48% less | **0.036 — worse** |
| r0+r4 | 2 | 51% | 51.3% | 52.3% | 13.06 | 39% less | 0.851 |
| r0+r6 | 2 | 51% | 52.6% | 51.3% | 13.06 | 39% less | 1.000 |
| r0+r2+r4 | 2 | 78% | 41.6% | 45.0% | 8.55 | 60% less | **0.015 — worse** |
| r0+r2+r4 | 3 | 43% | 55.8% | 52.3% | 15.96 | 25% less | 0.832 |
| r0+r2+r6 | 2 | 76% | 45.0% | 46.7% | 8.84 | 59% less | 0.082 |
| r0+r2+r6 | 3 | 44% | 55.0% | 51.7% | 15.82 | 26% less | 1.000 |
| r0+r4+r6 | 2 | 75% | 46.0% | 50.3% | 9.05 | 58% less | 0.694 |
| **r0+r4+r6** | **3** | 40% | 59.2% | **53.7%** | 16.60 | 22% less | 0.263 |
| r0+r2+r4+r6 | 3 | 54% | 50.9% | 51.0% | 14.80 | 31% less | 0.860 |
| r0+r2+r4+r6 | 4 | 38% | 59.6% | 53.3% | 18.29 | 14% less | 0.359 |

CoT baseline: **51.7%**, 21.37 Wh per 100 questions.

## What changed from the s1-only read

The s1 sweep (n=100) showed every configuration reading as "tied" — cascade
accuracy 45–58% against a 56% baseline, all p>0.05. Pooling to n=300 does two
things at once: it sharpens the estimate, and it moves the point estimates
themselves, because s1's 56% baseline was itself high (s2 was 51%, s3 was 48%,
pooled 51.7%).

**Two low-threshold configurations are now significantly worse than CoT.**
`r0+r2` and `r0+r2+r4` at threshold 2 both lose to the baseline at p<0.05.
Threshold 2 means "any 2 of the rotations agree, even out of 3 or 4" — a weak
bar that lets a lot of wrong-but-lucky pairs through, and at n=300 that
weakness is now visible rather than lost in sampling noise.

**No configuration beats CoT.** The best point estimate, r0+r4+r6 at
threshold 3, reaches 53.7% against 51.7% — a 2-point edge that is not
significant (p=0.263) and is exactly the kind of small favorable-looking gap
that a single subset (s1, K=4 unanimous) inflated to "+2.0 points" before
pooling.

## The honest conclusion

**The permutation-ensemble cascade, as tested here, does not demonstrate an
accuracy-preserving efficiency win.** What survives:

- The energy savings are real and large (14–60% depending on configuration) —
  those are measured costs, not statistical claims.
- Whether accuracy is preserved at those savings is genuinely unresolved: most
  configurations are statistically indistinguishable from CoT, which is
  consistent with either "works fine" or "too few questions to tell."
- Two specific configurations (loose thresholds, K≤3) are now positively
  contraindicated — pick threshold ≥ K−1, not a bare majority.

**This is the negative-leaning result to report**, not the s1 "K=4 unanimous:
+2.0 points, 20% less energy" framing, which was flagged as provisional and
did not survive n=300.

## The gate itself, checked separately, pooled

Cascade net accuracy and gate quality are different questions. Pooled at
n=300 (K=4, unanimous-only, matching the r0+r2+r4+r6 / thr=4 row above):

| | n | accuracy |
|---|---|---|
| all 4 rotations agree | 114 | **59.6%** |
| rotations disagree | 186 | **24.2%** |
| separation | | **35.5 points** |

This is smaller than the single-subset read (43–45 points at n=100) but still
large, and now measured on three times the data. **The gate is real and
holds.** Agreement across permuted option orders does predict correctness.

**The bottleneck is downstream of the gate, not the gate itself.** Only 38% of
questions land in the cheap, high-confidence bucket; the other 62% get
escalated to full CoT cost. That is what erases most of the energy saving
(14% left at thr=4) for a 2-point, non-significant accuracy edge — the
escalated set is simply large and expensive under this construction, not that
the gate mis-routes badly.

## What would actually move this forward

Not more pooling — the gate signal is now well-measured. Two real levers,
untested here:

1. **A cheaper escalation path than full CoT.** The construction escalates to
   the *most* expensive option available. A bounded-budget CoT pass (as in
   `2026-09-27-quality-flows.md` Use 3) on just the disagreement set would cut
   the 62%-at-full-price cost without touching the gate.
2. **A threshold that trades kept-accuracy for kept-fraction more favorably.**
   thr=4/K=4 buys the highest separation but the smallest kept bucket (38%).
   thr=3 configurations keep 40–54% at a smaller but still real accuracy edge
   (55–59% vs 51.7% baseline) — worth checking whether *those* pooled
   McNemar numbers (already in the table above: p=0.832, 0.263, 0.860) move
   toward significance with a cheaper escalation cost, since a smaller Δenergy
   requirement is easier to clear.

## A third construction, tested and rejected: adaptive early-stop

**Hypothesis:** most of the K=4 rotation cost is wasted on questions that
would have agreed after just 2 rotations. Run rotations sequentially, stop
and accept as soon as the first 2 agree; only pay for all 4 (and escalate to
CoT) on the harder 40% that don't resolve early.

**Checked first, before committing device time:** whether "majority ∈
{top-2 candidates}" holds for 3-1 splits, since a cheaper binary adjudication
between just the top-2 votes was the natural next idea. It doesn't — **45.8%
of 3-1 splits have the true answer outside both the majority and minority
pick** (n=48). Binary adjudication would miss nearly half its targets, so
this variant was dropped before testing.

**Adaptive early-stop, tested (n=300, pooled):**

| | n | share | accuracy |
|---|---|---|---|
| stopped after 2 (agree) | 179 | 59.7% | 46.9% |
| escalated to CoT (didn't agree) | 121 | 40.3% | 46.3% (CoT's own accuracy on this subset) |
| **cascade overall** | 300 | | **46.7%** |
| CoT baseline (same 300) | 300 | | **51.7%** |

Cost: 36.47 Wh / 297.4 min vs CoT's 64.11 Wh / 543.3 min — **43% less energy,
45% less time**. But:

**Paired McNemar: p = 0.036 — significantly worse than CoT**, not tied. 15
questions the cascade gets right that CoT doesn't; 30 where CoT is right and
the cascade isn't.

**Why it fails:** 2-rotation agreement is a weak signal. The "stopped at 2"
bucket's accuracy (46.9%) is *lower* than CoT's own baseline (51.7%) — so
accepting those answers as final, rather than escalating, actively throws
away accuracy on the majority of questions. The vote-count/accuracy table
above (59.6% / 30.6% / 25.3% / 14.3% for 4/3/2/1-way agreement) already
implied this: only the *unanimous* (4/4) bucket clears baseline accuracy.
Anything short of unanimity is not a reliable accept signal on its own.

## Where this leaves the permutation-gate line of work

Three constructions tried on top of the same real gate signal
(agreement-predicts-correctness, 35.5 points at n=300):

| construction | result |
|---|---|
| unanimous-only cascade, escalate the rest to full CoT | tied with CoT, no config significant either way |
| binary top-2 adjudication on near-unanimous splits | rejected before testing — 45.8% miss rate |
| adaptive early-stop at 2, escalate the rest | **significantly worse than CoT (p=0.036)** |

**None of the three achieves iso-accuracy.** The gate signal is real, but
every cheap decision rule built to exploit it either ties or loses. The
common failure mode: any threshold below full unanimity accepts answers at
an accuracy below the CoT baseline, so "cheap acceptance" is only safe at the
one operating point (K=4 unanimous) that also has the smallest kept-fraction
and the largest escalated cost — which is what erased its savings in the
first construction.

**This is a coherent negative result, not a dead end from lack of trying.**
The paper-worthy conclusion from this line of work: for MMLU-Pro on Gemma 4
E2B, letter-level agreement across permuted option orders is diagnostic but
not actionable as a cheap accept/reject gate at any threshold weaker than
unanimity, and unanimity alone is too rare (38% of questions) to make the
escalation-cost economics work with full CoT as the fallback.

---

## Appendix: the s1-only read (n=100, superseded)

> Kept as it was written before pooling, per the report-every-run rule. Its
> headline ("the gate works", K=4 unanimous at +2.0 points) did not replicate
> at n=300 — see above.

**E2B, Pi 5, subset s1, n=100.** K=4 rotations of the option order
(r0/r2/r4/r6), letter-only, majority vote, escalate to full CoT where the
rotations disagree. **No ground truth is used to route** — unlike the oracle,
this is deployable.

### 1. Option order alone moves the score 8 points

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

### 2. Agreement is a usable gate

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

### 3. The cascade

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

### 4. K and the threshold: a frontier, not a single point

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

### What this changes

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

### Caveats, in order of how much they matter

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
