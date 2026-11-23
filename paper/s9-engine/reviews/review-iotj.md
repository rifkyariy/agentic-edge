# Referee report: IEEE Internet of Things Journal version (`iotj.tex`)

**Manuscript:** *Never Compute Twice: Exact-Output Speedups for Gemma 4 on IoT Edge GPUs*
**Recommendation:** Major revision. There is a risk of desk rejection on scope.

The numbers are consistent: `benchmark/paper_tables.py` reports that every number matches, and the
derived percentages and ratios in the text recompute correctly. The problems below concern framing,
attribution and claims that go further than the data.

---

## A. Relationship to little-gemma (CoPR is a patch on someone else's engine)

The paper does say CoPR is "little-gemma at a pinned commit plus one patch". But it understates how much
of the mechanism is upstream, and it calls a patched baseline "stock". Reviewers who know little-gemma
will find this, so the paper should say it first.

1. **The "stock" little-gemma baseline is not stock.** Sec. V calls it "*little-gemma* (stock, behind an
   OpenAI-compatible shim)". In fact the baseline binary also carries `agentic-edge.patch`, which changes
   `run.c`:
   - it raises `SERVE_GEN` from 1024 to 2048;
   - it adds `-raw` prompts, tokenised once and whole, where upstream tokenises space-split dictation pieces;
   - it counts the context budget in tokens rather than characters;
   - it enlarges the chat buffer from 8,704 to 32,768.

   None of this touches the forward pass, and the prompt-token match with llama.cpp (1,097 = 1,097)
   supports that. Still, "stock" is inaccurate. Call it "little-gemma with a serving patch (no kernel
   changes)", list the four changes, and cite the token-count check.
2. **Prefix save and restore already exist upstream.** `kvcache_save_prefix` and `kvcache_restore_prefix`
   are little-gemma's own routines for its `-sys` system prompt. `ae.patch` makes three changes:
   - it calls them per request, keyed on the raw prompt (`run.c`);
   - it allocates the buffers once at 4,096 rows instead of on every call, which fixes a per-call leak
     upstream;
   - it adds error exits.

   Upstream already copies `min(n, seq[L])` rows of every layer, which for a ring layer is the whole ring
   whenever the prefix is longer than the window. As far as the patch context shows, the ring-exact
   snapshot (contribution 1, Fig. 2) is therefore upstream behaviour, and CoPR's part is *when* the
   snapshot is taken and *reused*. Rewrite contribution 1 and Sec. IV-B to credit upstream for the routine
   and claim only the per-request keying and buffer reuse. *(Before rewriting, check this against the
   upstream source at `aee759d`.)*
3. **[WAIVED: MTP is out of scope by the author's decision. The paper notes the verify was built for draft heads and says in one sentence that draft-head drafting is out of scope. No MTP runs are planned.]**
   ~~**The "existing batched verify" is little-gemma's MTP verify, and MTP is never mentioned.**~~ little-gemma
   ships speculative decoding with Gemma 4's multi-token-prediction heads, and its authors report about a
   1.0-step cost for a width-2 verify on the Orin NX (cited in Sec. VI-F). That leads to the most obvious
   reviewer question: **how does CoPR compare with little-gemma's own exact MTP drafting, and do the two
   combine?** RESULTS.md shows `-reuse -ngram -mtp … -block 4` passed a 42/42 gate, so the combination
   runs. Add little-gemma+MTP as a baseline, and CoPR+MTP if possible. At minimum, explain why MTP is
   excluded. The current reason in RESULTS ("neither baseline ran speculative decoding") will not satisfy
   a reviewer, because llama.cpp+n-gram is already a speculative baseline in the paper.
4. **The patch scope is described too narrowly.** The text says "one patch to its socket server and
   prefix-save routine". The patch touches `run.c`, `src/cuda/model-cuda.cuh` and `src/cpu/model-cpu.c`
   (the prefix-save functions of both backends; host code only, no kernels). State the size, about 144
   added lines in `ae.patch` and 22 in the serving patch. The small size helps the paper's argument.
5. **Name the pin and the licence.** Give the upstream commit (`aee759d`) in the paper, not only in the
   repository. Confirm in one line that little-gemma's licence allows redistributing a patch.
6. **Credit is split across a preprint and a repository.** `littlegemma` is a non-peer-reviewed PDF hosted
   on GitHub. That is fine to cite, but the Background paragraph should state plainly which features are
   theirs (CUDA graphs, fused kernels, ring caches, MTP verify, prefix save) and which are yours (the n-gram
   drafter feeding the verify, per-request snapshot keying, `-block` on the command line, buffer reuse).
   Since the patch fixes an upstream leak, consider offering that fix upstream. Otherwise "not submitted
   upstream" reads as a choice not to.

## B. Major

1. **The IoT framing is added on top, not built in.** The IoT angle appears only in a few sentences in the
   abstract and introduction, and Sec. IX says "we did not test a fielded IoT system". The workload is
   MMLU-Pro. The title says "IoT Edge GPUs", plural, but one board was tested. Either:
   - add an IoT-shaped workload and metric, such as energy per request or battery life on a tool-calling
     agent (BFCL is halfway there), or
   - rely on the ESL version instead.

   At minimum, use the singular, "an Edge GPU".
2. **The headline speedup credits the method with the engine's gain.** The abstract reports 1.28× and 1.52×
   over llama.cpp, but little-gemma alone is already 1.11× and 1.30× faster than llama.cpp. CoPR's own
   gain is **1.15× and 1.17×** over little-gemma. Lead with that figure. Together with A.1–A.3, this
   decides how much of the result counts as your contribution.
3. **The argument for byte identity uses the wrong comparison.** CoPR shares every kernel with
   little-gemma, so the 10% agreement rate between two different engines says nothing about it.
   - Use the comparison your own data gives: llama.cpp's own drafting changed 91% of replies.
   - Say that "2,100" counts repeats; there are only 500 distinct prompts.
   - Identical greedy text only shows that the top-ranked token matched. Hash logits on a sample of steps.
4. **The llama.cpp n-gram comparison is unfinished at its fairest point.** The matched setting (width 3)
   never drafted, and the text says "we have not yet found why". The non-exactness is put down to an
   "unverified likely cause". Test it, or soften the claim in the abstract. Also, "fastest setting" should
   read "fastest of the three settings tried".
5. **Pinned-clock runs are compared with unpinned baselines.** The paper says pinning moves speed by "±3%",
   but your own data show a 3.3% shift: the width-3 llama.cpp row never drafted yet came out 3.3% faster
   than the plain run. That affects:
   - the n-gram speed gains of 17% and 9%;
   - reuse-only's "4% shorter on E2B";
   - the 2.8% E4B decode rise described as "essentially unchanged".

   Rerun these unpinned, or bound the effect explicitly.
6. **Speed and energy have no uncertainty.** Each is a single run per configuration, and the one repeat is
   on a single subset. Report the spread across subsets, or bootstrap confidence intervals.
7. **The Pi result is a prediction but is listed as a contribution.** It rests on one `llama-bench`
   anomaly: a batch of 4 costs 1.06×, while batches of 2 and 3 cost 1.30× and 1.58×. My unverified
   hypothesis is that llama.cpp's ARM Q4_0 4-wide kernels switch on at batch 4. `llama-bench` also times
   a 4-token prompt with an empty cache, not decoding at a 2,000-token context. Run it on the Pi, or move
   it out of the contributions.

## C. Moderate

- **Write the prediction formula as an equation.** Speedup ≈ (1 + m·a) / (1 + m·(c − 1)), where m is the
  match rate, a the accepted tokens per drafted step and c the cost of one verify pass in plain decode
  steps. It reproduces Table VI within 0.3%. Validate it on the same 28 questions, not 300 replayed
  against 28 measured.
- **Prefix reuse depends on request order** (subject-grouped). Report the restore hit rate and what happens
  when subjects interleave.
- **Related work is thin for IoT Journal:** 26 references in 7 pages. Missing are edge and mobile inference
  systems (PowerInfer-2, MLC-LLM, llm.npu), Jetson LLM benchmarks and batch-invariant inference.
- **Why the 15 W mode?** The board supports the 25 W "Super" mode, so would the verify cost curve and the
  best width change there?
- **"Negligible for free-form text" in the abstract comes from IFEval replay only.** Label it as a
  prediction, or run it.

## D. Minor and editorial

- Table V caption: the internal run name "(S3)" leaks, and "14- and 28-question gates" is never defined.
- Sec. V: the parenthesis "(CoPR 0.363 vs. llama.cpp 0.458 J …)" quotes the comparison between engines,
  but the sentence claims a 1–2% change. Give the before and after values for each engine.
- Table III bolds the lowest *power* as "best". Remove that bolding.
- Sec. VIII: say plainly that the McNemar test is iPhone vs. CoPR, and that MLX 4-bit is a different
  quantization from Q4_K_XL.
- Prompt tokens per question for little-gemma on E4B are 1,446, but 1,444 for lookup-only, on identical
  prompts. Check this against footnote d.
- The lab-notebook tone ("runs we already had", "we did not investigate", the story of the argument-parser
  bug in the appendix): keep the disclosure but shorten it.
- The 224 identical replies from the width sweep are not counted in "2,100".
- Left before submission: the `TODO(author)` lines for IEEE memberships, funding and biographies.

## E. Strengths to keep

- Measurement discipline: the serving command line is captured while each run is live, clock faults are
  disclosed, and failed runs are kept.
- The replay that predicts acceptance matches live measurement within 0.04 tokens.
- An honest limitations section.
