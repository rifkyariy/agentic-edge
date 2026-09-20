#!/usr/bin/env bash
# MMLU-Pro on the fixed 100-question stratified subset, one model per run.
#
#   ./std_mmlupro.sh e2b              # baseline, thinking off
#   ./std_mmlupro.sh e4b
#   THINKING=on ./std_mmlupro.sh e2b  # the reasoning-mode row
#
# Build the subset once with mmlupro_subset.py (seed 20260918, proportional
# over all 14 subjects). The ids are committed in findings/stdbench/.
#
# Two settings this box needs, both restored on exit:
#   -c 8192        the longest prompt is 2362 tokens and max_gen_toks is 2048,
#                  so the deployed 4096 would truncate answers
#   --cache-ram 0  llama.cpp's default 8192 MiB host prompt cache exceeds the
#                  Pi's RAM; with 100 distinct prompts it gets OOM-killed
#                  (first E4B tinyGSM8k attempt died at question 48)
#
# Set directly in runtime.env rather than through va-web's /model, which
# recomputes VA_LLM_SPEC_ARGS and would drop the flags.
set -uo pipefail
MODEL_KEY="${1:?usage: $0 {e2b|e4b}}"
THINKING="${THINKING:-off}"
RT=/etc/voice-agent/runtime.env
S=~/Research/stdbench

case "$MODEL_KEY" in
  e2b) M=/home/mitlab/models/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf; TAG=E2B ;;
  e4b) M=/home/mitlab/models/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf; TAG=E4B ;;
  *) echo "unknown model key: $MODEL_KEY" >&2; exit 1 ;;
esac
OUT=$S/mmlupro100-$MODEL_KEY
[ "$THINKING" = on ] && OUT=$OUT-think
mkdir -p "$OUT"

sudo -n sed -i -e "s|^VA_LLM_MODEL_PATH=.*|VA_LLM_MODEL_PATH=$M|" \
               -e 's|^VA_LLM_SPEC_ARGS=.*|VA_LLM_SPEC_ARGS=--cache-ram 0|' \
               -e "s|^VA_LLM_REASONING=.*|VA_LLM_REASONING=$THINKING|" \
               -e '/^VA_LLM_CTX=/d' "$RT"
echo "VA_LLM_CTX=8192" | sudo -n tee -a "$RT" >/dev/null
sudo -n systemctl restart va-llm
for _ in $(seq 150); do
  curl -s -m 3 localhost:8080/props | grep -q "\"model_path\":\"$M\"" && break
  sleep 2
done
ps -o args= -C llama-server
echo "$(date) start MMLU-Pro subset100  model=$TAG thinking=$THINKING"

# Stock lm-eval mmlu_pro config: 5-shot CoT, greedy, max_gen_toks 2048,
# 'answer is (X)' extraction. Only the question set is restricted.
~/Research/eval-venv/bin/lm_eval run --model local-chat-completions \
  --model_args "model=gemma4-$TAG,base_url=http://127.0.0.1:8080/v1/chat/completions,num_concurrent=1,max_retries=3,tokenized_requests=False,timeout=3600" \
  --tasks mmlu_pro --apply_chat_template \
  --samples "$(cat "$S/mmlupro_subset100_samples.json")" \
  --log_samples --use_cache "$OUT/cache" --output_path "$OUT" \
  > "$OUT/lm_eval.log" 2>&1 && touch "$OUT/.done"
echo "$(date) end rc=$?"

# Back to the deployed defaults.
sudo -n sed -i -e 's|^VA_LLM_SPEC_ARGS=.*|VA_LLM_SPEC_ARGS=|' \
               -e 's|^VA_LLM_REASONING=.*|VA_LLM_REASONING=off|' \
               -e '/^VA_LLM_CTX=/d' "$RT"
sudo -n systemctl restart va-llm
echo finished
