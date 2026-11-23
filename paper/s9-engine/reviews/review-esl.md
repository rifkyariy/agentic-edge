# Referee report: IEEE Embedded Systems Letters version (`esl.tex`)

**Manuscript:** *Never Compute Twice: Exact-Output Speedups for Gemma 4 on an Edge GPU* (3 pages)
**Recommendation:** Minor-to-major revision. This version fits ESL's scope better than the IoT Journal one,
because there is no IoT framing to defend and the title is already singular. But a letter has no room to
hide the attribution and baseline gaps, and ESL reviewers will check them first.

Its numbers come from the same `numbers.tex`, which passes `paper_tables.py`.

> **Submission order:** the ESL and IoT Journal versions are the same work. Submit to ESL only after an IoT
> Journal decision, never at the same time (IEEE duplicate-submission policy).

---

## A. Relationship to little-gemma (more pressing in a letter)

In three pages, a reader decides from the Design paragraph what is new. As written, it implies that the
ring-exact snapshot and the batched verify are CoPR's. The patch shows otherwise.

1. **Prefix save and restore are upstream routines** (`kvcache_save_prefix` / `kvcache_restore_prefix`,
   used by little-gemma's `-sys`). CoPR keys them per request on the raw prompt and allocates the buffers
   once, which also fixes an upstream per-call leak. Upstream already copies `min(n, seq[L])` rows, so for
   a ring layer it already saves the whole ring. The sentence "each ring is stored whole and rewritten on
   restore" therefore describes upstream behaviour. Credit it, and claim the keying and the buffer reuse.
   *(Check against upstream `aee759d` before rewriting.)*
2. **[WAIVED: MTP is out of scope by the author's decision. The paper notes the verify was built for draft heads and says in one sentence that draft-head drafting is out of scope. No MTP runs are planned.]**
   ~~**The verify is little-gemma's MTP verify, and its MTP drafting is never mentioned.**~~ little-gemma
   already does exact speculative decoding with Gemma 4's MTP heads. A reviewer will ask why CoPR is not
   compared with little-gemma+MTP, and whether the two combine; `-ngram -mtp` passed a 42/42 gate. Add one
   row, or one sentence explaining the exclusion.
3. **The baseline also carries a serving patch.** It raises `SERVE_GEN` from 1024 to 2048 and adds
   whole-prompt `-raw` tokenisation. The ESL text does not call it "stock" (good), but it doesn't disclose
   the patch either. Add half a sentence: "both little-gemma rows carry a serving patch (answer cap,
   whole-prompt tokenization); no kernel changes".
4. **State the pin and the patch size in the paper.** The pin is `aee759d`. The patch adds about 144 lines
   of host code across `run.c` and the two backends' prefix-save functions; that size is a selling point.
   Also confirm in one line that little-gemma's licence allows redistributing the patch.

## B. Major

1. **The headline speedup credits the method with the engine's gain.** The abstract and the conclusion
   both lead with 1.28× and 1.52× over llama.cpp. CoPR's own gain over little-gemma is **1.15× and 1.17×**.
   In a letter, the conclusion is the claim, so put the gain over little-gemma first.
2. **The byte-identity argument** ("two engines agree on only 32 of 300") uses the wrong comparison,
   because CoPR shares little-gemma's kernels. Use the llama.cpp drafting result instead, where 91% of
   replies changed, and note that 2,100 replies cover only 500 distinct prompts.
3. **Admissions of unfinished work** ("for a reason we have not found"; "we have not verified it"). In a
   three-page letter these stand out more than in a journal paper. Resolve them, or cut the width-3
   sentence; Table II's footnote already covers it.
4. **Pinned clocks.** "±3%" is contradicted by the 3.3% shift in Table II's width-3 row. "Reuse alone
   leaves decode essentially unchanged" also rests on a pinned run.
5. **Claims made without the data shown.** A letter can cite rather than show, but these are now
   unsupported on the page:
   - "about 97% of request time is decode" (the anatomy table was cut);
   - "width 3 was fastest by 1.0% and 0.8%" (the sweep table was cut);
   - "the accepted counts match the offline replay" (the replay table was cut).

   Either keep a small combined table (sweep: width, tok/s, accepted, cost), or point to the repository's
   `findings/TABLES.md` for each.
6. **[RESOLVED: removed from the manuscript; the author declares AI use on the submission form.]** ~~**The AI-disclosure placeholder** "[describe role: drafting, editing, figures, coding, verification]" in
   the Acknowledgment. ESL desk-rejects papers with an unfilled disclosure, and a bracketed placeholder is
   worse than none. Fill it in.~~

## C. Moderate

- Add the prediction equation, speedup ≈ (1 + m·a) / (1 + m·(c − 1)). It is one line and turns "logged
  replies predict the gain" into a checkable claim.
- No uncertainty is given on speed or energy. One phrase, such as "spread across the three subsets ≤ x%",
  is enough in a letter.
- Prefix reuse depends on subject-grouped request order. Say so in the Design paragraph.
- Tool calls: "reach 1.24 tokens per decode step" is the *replayed* figure, placed next to *measured*
  decode +12%. Label which is which.

## D. Minor and editorial

- Table III caption: "(S3)" and "14- and 28-question gates" are internal terms, the same issue as the
  IoT Journal version.
- Table I bolds the lowest power as "best".
- Table I footnote a points to Sec. `results` for the tie, but the McNemar values for E4B are not given
  there. Add p for E4B.
- A full-width table, two figures and three tables in three pages: check against ESL's 4-page limit after
  adding the little-gemma and MTP sentences. Fig. 2 is the best candidate to shrink.
- Prompt tokens per question for little-gemma on E4B are 1,446, but 1,444 for lookup-only. Check this.
- Left before submission: the `TODO(author)` lines for IEEE memberships and funding.

## E. Strengths

- Tight and readable, and the title and scope match what was tested.
- The exactness conditions (i) and (ii) are stated precisely and checked empirically, which is the right
  framing.
- Everything can be reproduced from the repository.
