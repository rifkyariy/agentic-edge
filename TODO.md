# TODO

Working list, most-actionable first. Background and full data live in
[`findings/RESULTS.md`](findings/RESULTS.md) (§10 is the status) and [`docs/`](docs/);
this file is the short version — what to do next and why, not the evidence.

Both boards are idle as of 2026-09-29.

---

## Decide, don't just do

- [ ] **Authorize or reject the power-mode sweep.** See
      [`docs/proposals/README.md`](docs/proposals/README.md) update below —
      this needs `nvpmodel`/`cpufreq` changes on both boards, which is a
      system-setting change I won't make unilaterally. If yes: which board
      first (Jetson has `nvpmodel`, documented modes; Pi only has `cpufreq`
      governors — cheaper to test, already at `ondemand` per `RESULTS.md`).
- [ ] **Pick a paper framing for the negative results.** Three cascade
      constructions on the permutation gate all failed
      (`findings/analyses/permutation-ensemble.md`). That's a legitimate
      "ruled out with evidence" finding, not a stalled experiment — decide
      whether it's a subsection or an appendix before writing more code
      chasing a fourth variant.
- [ ] **Decide if capability (c) — safety/security — gets picked up at all
      before the manuscript**, or stays explicitly out of scope for paper 1.
      No benchmark chosen yet (candidates: XSTest, SimpleSafetyTests,
      AgentDojo).

## Ready to run (no new code, no new decisions)

- [ ] **IFEval / BFCL** — installed, unrun. Capability (b) currently rests
      only on the custom 10-case suite. This is the most overdue "should
      already be done" item — infra exists, nothing blocks it.
- [ ] **`mmlupro-lg-e4b-s3`** — confirm it's the completed one, not the earlier
      incomplete run; S3 baseline should be n=300 on both models. Verify
      before citing 65.3%/65.5% either way (there were two conflicting reads
      of this earlier in the project).
- [ ] Clean up the two `blocked` queue jobs on the Jetson (`states:
      {'blocked': 2}` — stale from an earlier interrupted run) so
      `queue_ctl.py --status` stops carrying dead entries.

## Needs new code or device time

- [ ] **Bounded-budget CoT escalation.** The one cascade lever not yet tried:
      replace "escalate to full CoT" with "escalate to CoT capped at N
      tokens" for the ~40–60% of questions that don't resolve at the cheap
      tier. Full CoT escalation is what ate the savings in every construction
      tried so far — this changes the cost side without touching the gate.
      Cheap to test (reuse existing subset + telemetry harness, new
      `max_tokens` only).
- [ ] **Cross-model gate (E2B/E4B disagreement) as an alternative to
      within-model permutation.** Different failure surface, genuinely
      untested — flagged in `2026-09-27-model-cascade.md`, never executed.
- [ ] Given the run above: **if bounded-budget escalation also fails**,
      write up the permutation-gate line as closed (3 constructions tried,
      1 more with a different cost model, then stop) rather than open-ended.

## Housekeeping

- [x] `AGENTS.md` §6 was stale — it now points at `findings/RESULTS.md` §10
      instead of keeping its own copy of the state (2026-10-08).
- [x] The two permutation write-ups are one file now,
      `findings/analyses/permutation-ensemble.md`: the pooled n=300 result
      first, the superseded n=100 read as an appendix (2026-10-08).

## Explicitly not doing (parking, not forgetting)

- LiteRT-LM (condition C) — dropped.
- Further GSM8K runs — results stay as a methodological appendix only.
- little-gemma on the Pi for the full S3 grid — would cost ~110h to confirm
  what the Jetson already answered (~6× slower decode, ~40× slower prefill
  on Pi CPU per `findings/early-engine-benchmarks/README.md`). One smoke-test run is enough
  evidence; don't scale it up.
- Cassandra / PELM-style speculative decoding — Cassandra has no CPU
  results and needs custom weight/KV compression infra; PELM's speculative
  half needs a separate draft model, which is the same shape as MTP
  (already tested, already a net loss on Pi CPU). Neither is worth building
  unless the power-mode sweep above also disappoints.
