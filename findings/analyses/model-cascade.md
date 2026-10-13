# Model cascade (E2B → E4B): the oracle ceiling and the first real gate

**Offline analysis of the baseline grid — no new device time.** Both models
answered the same 300 MMLU-Pro questions on each board (S1), so a cascade that
answers with E2B and escalates to E4B can be scored exactly from what is
already recorded. Not used in the manuscript; reported because it was run.

**Reproduce:** `python3 benchmark/analyze_cascade.py --export
findings/export/experiment-full.json --board pi --wh 26.6 50.4` (gunzip the
export first); `analyze_cascade_pooled.py` gives the pooled form.

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

**+4.3 points and 13% less energy, simultaneously — for a perfect gate.** That
is the ceiling, not a result. The section below tests the first realisable gate
and it does not get there.

## Tested: the first realisable gate fails

The oracle above is not a method. The obvious first gate — escalate where E2B
is *numerically unstable*, i.e. where the two boards disagree on its answer —
is realisable and turns out to discriminate genuinely:

| E2B on a question | share | E2B accuracy | E4B accuracy | E4B uplift |
|---|---|---|---|---|
| stable (both boards agree) | 71% | 63.6% | 72.9% | +9.3 |
| unstable (boards disagree) | 29% | **22.1%** | 47.7% | **+25.6** |

A 41.5-point accuracy separation, and the uplift from escalating is nearly
three times larger on the flagged set. The signal is real.

**And the cascade built on it still loses.**

| | accuracy | Pi energy |
|---|---|---|
| E2B alone | 51.7% | 26.6 Wh |
| **instability cascade** | **59.0%** | **41.0 Wh** |
| E4B alone | **65.7%** | 50.4 Wh |
| oracle | 70.0% | 43.9 Wh |

−6.7 points against E4B for 19% less energy — and worse than that, it sits
*below* the straight line between E2B and E4B, so it is beaten by simply
running E4B on a random 60% of questions.

### Why, precisely

**E4B beats E2B on both splits.** Keeping 214 questions on E2B forfeits the
+9.3 uplift E4B would have delivered there, which costs 6.7 points overall —
almost exactly the deficit. Meanwhile the escalated set is one where E4B itself
only manages 47.7%.

**Instability finds questions that are hard, not questions E4B can rescue.** Of
the 55 questions the oracle escalates — E2B wrong *and* E4B right — instability
flags 29, or 53%, against a 29% base rate. Better than chance by 1.8×, nowhere
near enough.

**Conclusion.** The +4.3-point oracle rests entirely on the 4.3% of questions
where E2B beats E4B, and a gate built on board-to-board instability finds hard
questions, not rescuable ones: it lands below the straight line between the
two models. The cascade line stopped here.
