# Pi 5: the cost of a batched verify, and replayed lookup acceptance

Evidence for the paper's Pi prediction (§VII). Nothing here ran an n-gram
drafter on the Pi; it measures the two inputs a prediction needs.

- `verify-cost-llama-bench.md`: queue job `pi-verify-cost-e2b` (2026-10-05),
  `llama-bench -m ~/models/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf -t 3 -p 1,2,3,4
  -n 32 -r 5`, Pi build `661643e`. llama-bench reports this file as `Q4_0`
  because most of its tensors are q4_0. A batch of 4 prompt tokens takes about
  as long as one (pp4 28.56 tok/s vs pp1 7.57 tok/s: 140 vs 132 ms per pass);
  batches of 2 and 3 cost 1.30x and 1.58x. Why 4 is cheap is not verified.
- `replay-lookup.json`: queue job `replay-lookup-pi` (2026-10-05),
  `benchmark/replay_dirs.py` over the Pi's recorded llama.cpp replies (E2B
  and E4B MMLU-Pro, thinking on and off) and tinyGSM8k (E2B; 100 replies, which lm-eval logs twice, once per answer
  filter: the json's `replies: 200` counts both copies, and since every reply is
  doubled the ratios are unchanged; `replay_dirs.py` now counts each once). Per width:
  tokens per decode step, the share of steps with a lookup match, and accepted
  tokens per drafted step.

The Pi's build does have `--spec-type ngram-simple`, so the prediction is
testable on it as is; that run has not been made.
