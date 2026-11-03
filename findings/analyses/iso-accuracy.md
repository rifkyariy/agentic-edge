# Same accuracy, less energy — what works, what does not

The goal: hold the MMLU-Pro score and cut time and power. Everything below is
measured on runs already on disk, including the things that turned out not to
work.

## 1. The baseline your method has to beat

The accuracy–energy frontier across all 30 completed runs, per 100 questions:

| board | condition | model | n | score | Wh/100q | min |
|---|---|---|---|---|---|---|
| Orin | **little-gemma** | E2B | 300 | **53.0%** | **8.2** | 45 |
| Orin | llama.cpp | E2B | 300 | 52.7% | 10.9 | 50 |
| Orin | llama.cpp +think | E2B | 300 | 49.7% | 10.9 | 63 |
| Pi 5 | llama.cpp | E2B | 300 | 51.7% | 26.6 | 183 |
| Orin | **little-gemma** | E4B | 300 | **65.3%** | **15.9** | 83 |
| Orin | llama.cpp | E4B | 300 | 66.0% | 22.5 | 100 |
| Orin | llama.cpp +think | E4B | 300 | 66.7% | 22.5 | 125 |
| Pi 5 | llama.cpp | E4B | 300 | 65.7% | 50.4 | 368 |

Two things to be careful about here.

**These are comparison results, not contributions.** S3 measures two existing
engines against each other; nobody designed anything. little-gemma holding
accuracy within 0.3–0.7 points of llama.cpp for **25% less energy on E2B and
30% on E4B** is a fact about software someone else wrote. The same goes for
board choice: the Orin does the same work for **55–69% less energy** than the
Pi, which is a fact about hardware someone else built. Both belong in the
paper as measurements. Neither is a method.

**They set the bar, and they raise it.** A proposed method does not get to
claim "30% less energy than llama.cpp on the Pi" when an engine swap and a
board swap already deliver that for free. The honest comparison for anything
new is against **the best measured configuration**, which is currently
little-gemma on the Orin at 8.2 Wh (E2B) and 15.9 Wh (E4B) per 100 questions.
That is the number to beat, and it is a much harder number than the Pi
baseline it would be tempting to quote against.

## 2. Ruled out by measurement

### Budget capping — a bad trade, not a free one

An earlier draft of the quality proposal claimed cutting the long tail was
nearly free, on the grounds that questions hitting the 2,048-token cap score
4–7%. That reasoning does not survive a sweep, because **long answers are not
mostly runaways**:

| cap | questions cut | energy saved | accuracy | net |
|---|---|---|---|---|
| 1024 | 72 | 21% | 46.1% | **−5.6** |
| 768 | 93 | 31% | 42.8% | **−8.9** |
| 512 | 136 | 45% | 37.2% | −14.5 |

(Pi E2B; every other board/model combination behaves the same way.)

Only 25–27 questions actually hit the cap. A budget that saves meaningful
energy also truncates 60–90 answers that were going to land. The intervention
that is nearly free — cutting *only* the questions that hit the cap — saves
little, because those are already the minority of long generations.

### Early loop detection — catches almost nothing

If runaways looped, they would be detectable and could be aborted. They do not.
12-gram repeat fraction, Pi:

| | E2B | E4B |
|---|---|---|
| runaway (hit the cap) | 0.067 | 0.042 |
| long but correct | 0.006 | 0.002 |

The signal is real but weak: a threshold that never false-flags a correct long
answer still catches only **2 of 25** runaways on E2B and **1 of 27** on E4B.
Runaways are not repeating, they are being discursive and never committing.
Worth keeping as a free extra — zero false positives — but it is not a method.

### Thinking-on — a pure loss

20–26% more time on every board and model, and no accuracy: E2B is *worse* on
both boards, E4B moves inside noise. Settled; do not spend more device time.

## 3. What came of it

Measurement ruled out two of the three routes to cutting generation cost —
capping the budget (−5 to −11 points) and aborting on a detected loop (catches
4–8%). The third, deciding before generating at all, was then tested too:

- [`s4-letter-only.md`](s4-letter-only.md) — letter-only alone loses 15 points,
  but fails on different questions than CoT.
- [`permutation-ensemble.md`](permutation-ensemble.md) — agreement across
  permuted option orders predicts correctness, yet no cascade built on it
  reaches iso-accuracy at n=300.
- [`model-cascade.md`](model-cascade.md) — an E2B→E4B cascade lands below the
  line between the two models.

None holds accuracy, so the manuscript took the route that cannot change it:
exact-output speedups, where the replies stay byte-identical (CoPR, RESULTS §7.6).
