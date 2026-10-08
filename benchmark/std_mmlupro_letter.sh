#!/bin/bash
# S4: MMLU-Pro with the answer constrained to a letter — no chain of thought.
#
#   SUBSET=s1 ./std_mmlupro_letter.sh e2b
#   SUBSET=s1 ROT=2 ./std_mmlupro_letter.sh e2b   # options rotated 2 places
#
# The probe behind docs/proposals/2026-09-27-RECOMMENDATION.md: can Gemma pick
# the right option without reasoning its way there? Decode is 92-98% of
# per-question time, so if it can, almost all of that is avoidable.
#
# Runs the `mmlu_pro_letter` task built by make_letter_task.py. A flag will not
# do it: --system_instruction PREPENDS to the task's own description, which
# says "Think step by step", so the two contradict and the task's wins —
# measured, the model opened with "Step 1: Analyze the question." and scored
# 0/14. The task variant changes the description itself, plus num_fewshot 0
# (the exemplars are chain-of-thought ones) and a small max_gen_toks.
# Everything else is held: same subset ids, same server flags, same greedy
# decoding, same extraction. Output goes to mmlupro100-<model>-<subset>-letter
# so it cannot collide with the baseline.
#
# ROT=N rotates every question's option order by N places, gold included
# (make_letter_task.py --rotate): the permutation-ensemble runs that
# analyze_permutation.py reads. Each rotation is its own task
# (mmlu_pro_letter_rN) and its own directory (...-letter-rN).
set -uo pipefail
MODEL_KEY="${1:?usage: $0 e2b|e4b}"
SUBSET="${SUBSET:-s1}"
GEN="${GEN:-16}"                     # "the answer is (X)" with slack
ROT="${ROT:-0}"
RT=/etc/voice-agent/runtime.env
S=~/Research/stdbench

case "$MODEL_KEY" in
  e2b) M=/home/mitlab/models/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf; TAG=E2B ;;
  e4b) M=/home/mitlab/models/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf; TAG=E4B ;;
  *) echo "unknown model key: $MODEL_KEY" >&2; exit 1 ;;
esac
OUT=$S/mmlupro100-$MODEL_KEY-$SUBSET-letter
NAME=mmlu_pro_letter
SAMPLES=$S/mmlupro_subset100_${SUBSET}_letter_samples.json
if [ "$ROT" != 0 ]; then
  OUT=$OUT-r$ROT
  NAME=mmlu_pro_letter_r$ROT
  SAMPLES=$S/mmlupro_subset100_${SUBSET}_letter_r${ROT}_samples.json
fi
mkdir -p "$OUT"

# Same server the baseline uses: thinking off, 8192 context, no host cache,
# and the budget written out (-1) as std_mmlupro.sh does, so the queue's
# fingerprint sees exactly the mmlupro-baseline flags.
sudo -n sed -i -e "s|^VA_LLM_MODEL_PATH=.*|VA_LLM_MODEL_PATH=$M|" \
               -e 's|^VA_LLM_SPEC_ARGS=.*|VA_LLM_SPEC_ARGS=--cache-ram 0|' \
               -e "s|^VA_LLM_REASONING=.*|VA_LLM_REASONING=off|" \
               -e '/^VA_LLM_CTX=/d' -e '/^VA_LLM_REASONING_BUDGET=/d' "$RT"
printf 'VA_LLM_CTX=8192\nVA_LLM_REASONING_BUDGET=-1\n' | sudo -n tee -a "$RT" >/dev/null
sudo -n systemctl restart va-llm
for _ in $(seq 150); do
  curl -s -m 3 localhost:8080/props | grep -q "\"model_path\":\"$M\"" && break
  sleep 2
done
ps -o args= -C llama-server

TASKS=~/Research/lm_eval_tasks
python3 "$(dirname "$0")/make_letter_task.py" --gen-toks "$GEN" --rotate "$ROT" >/dev/null

echo "$(date) start MMLU-Pro subset100/$SUBSET model=$TAG LETTER-ONLY gen=$GEN rotate=$ROT"
~/Research/eval-venv/bin/lm_eval run --model local-chat-completions \
  --model_args "model=gemma4-$TAG,base_url=http://127.0.0.1:8080/v1/chat/completions,num_concurrent=1,max_retries=3,tokenized_requests=False,timeout=3600" \
  --include_path "$TASKS/$NAME" \
  --tasks "$NAME" --apply_chat_template \
  --samples "$(cat "$SAMPLES")" \
  --log_samples --use_cache "$OUT/cache" --output_path "$OUT" \
  > "$OUT/lm_eval.log" 2>&1 && touch "$OUT/.done"
echo "$(date) end rc=$?"

# Restore the deployed defaults, exactly as std_mmlupro.sh does (AGENTS rule 7).
sudo -n sed -i -e 's|^VA_LLM_SPEC_ARGS=.*|VA_LLM_SPEC_ARGS=|' \
               -e 's|^VA_LLM_REASONING=.*|VA_LLM_REASONING=off|' \
               -e '/^VA_LLM_CTX=/d' -e '/^VA_LLM_REASONING_BUDGET=/d' "$RT"
echo "VA_LLM_REASONING_BUDGET=-1" | sudo -n tee -a "$RT" >/dev/null
sudo -n systemctl restart va-llm
echo finished

# NOTE ON THE CONFOUND: this changes the instruction AND the shot count at
# once, so a score below the baseline does not by itself say chain of thought
# was load-bearing — it could be the loss of the exemplars. The probe is
# deliberately not an ablation: it asks whether a cheap letter-only path is
# viable at all. If it is, isolating the two is the follow-up.
