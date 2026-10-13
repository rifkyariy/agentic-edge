#!/usr/bin/env bash
# tinyGSM8k (Polo et al. 2024) on the Pi via lm-evaluation-harness, against
# the same server condition B uses:
#
#   ./std_run.sh queue    # tinyGSM8k on B, E2B then E4B
#
# MMLU-Pro runs from std_mmlupro.sh instead (it needs -c 8192).
# LiteRT-LM (condition C) was dropped on 2026-09-20 and removed from the box.
#
# Task configs are lm-eval's own, unmodified (greedy, their shot counts and
# max_gen_toks) so the numbers are comparable to published ones.
set -uo pipefail
cd "$(dirname "$0")"
OUT=~/Research/stdbench
EVAL=~/Research/eval-venv/bin/lm_eval
MODELS=/home/mitlab/models
log() { echo "[$(date +%H:%M:%S)] $*"; }

use_model() {  # llama.cpp via va-web, verified through /props
  curl -s localhost:8090/model -H 'Content-Type: application/json' \
    -d "{\"path\":\"$1\"}"; echo
  for _ in $(seq 300); do
    curl -s -m 3 localhost:8080/props | grep -q "\"model_path\":\"$1\"" && return
    sleep 2
  done
  log "llama.cpp did not load $1"; return 1
}

evaluate() {  # evaluate <label> <url> <model-id> <tasks>
  log "=== $1 / $4 ==="
  "$EVAL" --model local-chat-completions \
    --model_args "model=$3,base_url=$2,num_concurrent=1,max_retries=3,tokenized_requests=False,timeout=1800" \
    --apply_chat_template --tasks "$4" --log_samples \
    --output_path "$OUT/$1" 2>&1 | grep -E "^\||Error|error" || log "(failed)"
}

LLAMA=http://127.0.0.1:8080/v1/chat/completions

case "${1:-}" in
  queue)
    for m in E2B E4B; do
      l=$(echo $m | tr A-Z a-z)
      [ -f "$OUT/B-$l/.tinyGSM8k.done" ] && continue
      use_model "$MODELS/gemma-4-$m-it-qat-UD-Q4_K_XL.gguf" &&
        evaluate "B-$l" "$LLAMA" "gemma4-$m" tinyGSM8k &&
        touch "$OUT/B-$l/.tinyGSM8k.done"
    done ;;
  *) echo "usage: $0 queue" >&2; exit 1 ;;
esac
log "done"
