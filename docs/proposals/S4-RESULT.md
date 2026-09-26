# S4 letter-only: the result

**E2B, subset s1, Pi 5, 100 questions.** The probe behind
[`2026-09-27-RECOMMENDATION.md`](2026-09-27-RECOMMENDATION.md): can Gemma pick
the option without reasoning its way there?

## Headline

| | accuracy | energy | wall clock | generated tokens |
|---|---|---|---|---|
| CoT baseline | **56.0%** | 21.37 Wh | 181 min | 65,257 |
| **letter-only** | **40.0%** | **1.26 Wh** | **10.7 min** | **746** |
| | −16.0 pts | **17× less** | **17× faster** | **87× fewer** |

Alone, letter-only is not competitive: 16 points is far outside the ±9.7
sampling interval at n=100. The pure form of the method is **not** viable, and
my own decision rule set before the run ("within ~10 points → viable") is not
met.

## But the two paths are complementary, which is the result that matters

Paired over the same 100 questions:

| | count |
|---|---|
| both right | 30 |
| **letter-only right, CoT wrong** | **10** |
| CoT right, letter-only wrong | 26 |
| neither | 34 |

**Letter-only answers 10 questions that full chain-of-thought gets wrong.** CoT
is not strictly better — it actively costs accuracy on a tenth of the set,
which is the behaviour arXiv 2409.12183 reports outside mathematical and
symbolic problems.

That makes the cascade ceiling higher than either path alone:

| | accuracy | energy |
|---|---|---|
| letter-only | 40.0% | 1.26 Wh |
| CoT | 56.0% | 21.37 Wh |
| **oracle cascade** | **66.0%** | **14.1 Wh** |

**+10 points over CoT and 34% less energy**, if a gate can tell when
letter-only is right. (Cost assumes letter-only on all 100, then CoT on the 60
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

- **n=100.** ±9.7 points at 95%. s2 and s3 are running for n=300; the 16-point
  deficit will survive that, the 10-question overlap may not.
- **Confounded on purpose.** Letter-only changes both the instruction and the
  shot count (0-shot, because the 5-shot exemplars are chain-of-thought ones
  and would contradict the instruction). A cleaner ablation would separate
  them; this probe was built to answer "is the cheap path viable at all".
- **E2B only, Pi only.** E4B and the Orin are untested here.
- **The oracle is not a method.** 66.0% assumes perfect knowledge of when
  letter-only is right. Nothing here says a real gate gets close, and the
  previous attempt at a gate — escalating on model instability — failed for
  exactly this reason.
