# S4 letter-only: the result

**E2B, Pi 5, s1+s2+s3, n=300.** The probe behind
[`2026-09-27-RECOMMENDATION.md`](2026-09-27-RECOMMENDATION.md): can Gemma pick
the option without reasoning its way there?

## Headline

| | accuracy | energy | generated tokens |
|---|---|---|---|
| CoT baseline | **51.7%** ±5.7 | 64.16 Wh | 201,573 |
| **letter-only** | **35.7%** ±5.4 | **3.64 Wh** | **2,232** |
| | **−16.0 pts** | **18× less** | **90× fewer** |

Per subset: 40.0 / 29.0 / 38.0 against 56.0 / 51.0 / 48.0.

Alone, letter-only is not competitive. Paired over the same 300 questions the
gap is **McNemar exact p = 3.5 × 10⁻⁶** — real, not sampling. The pure form of
the method is **not** viable, and the decision rule set before the run
("within ~10 points → viable") is not met.

## But the two paths are complementary, which is the result that matters

Paired over the same 100 questions:

| | n=300 | per subset |
|---|---|---|
| both right | 78 | 30 / 24 / 24 |
| **letter-only right, CoT wrong** | **29** | **10 / 5 / 14** |
| CoT right, letter-only wrong | 77 | 26 / 27 / 24 |
| neither | 116 | 34 / 44 / 38 |

**Letter-only answers 29 of 300 questions that full chain-of-thought gets
wrong — 9.7%, and it held in all three subsets.** CoT is not strictly better;
it actively costs accuracy on roughly a tenth of the set, the behaviour arXiv
2409.12183 reports outside mathematical and symbolic problems. That this
survived pooling is the load-bearing fact: at n=100 it could have been noise.

That makes the cascade ceiling higher than either path alone:

| | accuracy | energy |
|---|---|---|
| letter-only | 35.7% | 3.64 Wh |
| CoT | 51.7% | 64.16 Wh |
| **oracle cascade** | **61.3%** | **44.9 Wh** |

**+9.7 points over CoT and 30% less energy**, if a gate can tell when
letter-only is right. (Cost assumes letter-only on all 300, then CoT on the 64%
it gets wrong.)

## What this changes

- **The pure letter-only path is dead** as a replacement for CoT. It is not a
  cheaper way to get the same answer.
- **The cascade is alive and better positioned than before.** Its ceiling rose
  from "match CoT more cheaply" to "beat CoT by 10 points while spending a
  third less energy", because the two paths fail on different questions.
- **The gate is now the entire problem**, and its target is sharper than it
  was: not "is this question hard" but "will the cheap path get this right".
  Those 10 questions are where the value is.

## What it cost to learn

10.7 minutes of Pi time, after two traps that each nearly wasted hours — see
[`02f5698`](../../commit/02f5698) for `--samples` silently running 5,980
questions instead of 14, and `--system_instruction` being prepended to a
"think step by step" description rather than replacing it.

## Caveats

- **n=300, pooled.** ±5.4/5.7 at 95%. Both predictions from the s1 write-up
  held: the deficit survived (16.0 points, unchanged) and so did the overlap
  (9.7%, present in every subset).
- **Confounded on purpose.** Letter-only changes both the instruction and the
  shot count (0-shot, because the 5-shot exemplars are chain-of-thought ones
  and would contradict the instruction). A cleaner ablation would separate
  them; this probe was built to answer "is the cheap path viable at all".
- **E2B only, Pi only.** E4B and the Orin are untested here.
- **The oracle is not a method.** 66.0% assumes perfect knowledge of when
  letter-only is right. Nothing here says a real gate gets close, and the
  previous attempt at a gate — escalating on model instability — failed for
  exactly this reason.
