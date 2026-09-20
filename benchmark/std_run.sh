#!/usr/bin/env bash
# Standard benchmarks on the Pi, replacing the hand-written static cases:
#   tinyGSM8k (Polo et al. 2024) and IFEval (Zhou et al. 2023) via
#   lm-evaluation-harness, against the same servers conditions B and C use.
#
#   ./std_run.sh queue    # tinyGSM8k on B, E2B then E4B (current focus)
#   ./std_run.sh full     # deferred: IFEval (B) + BFCL (D) per model, then C
#   ./std_run.sh litert   # C only
#
# BFCL (Patil et al., ICML 2025) runs through its generic OpenAI-compatible
# chat-completions function-calling handler (OpenAICompletionsHandler, borrowed
# via the openbmb/MiniCPM-SALA-FC registry entry, whose name llama.cpp ignores)
# pointed at llama.cpp — the same native tool-calling path as condition D.
# Everything is grouped per model so no run straddles a model switch.
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
BFCL_CATS=simple_python,multiple,irrelevance,live_simple,live_irrelevance
BFCL_HANDLER=openbmb/MiniCPM-SALA-FC

bfcl_run() {  # bfcl_run <label>
  log "=== $1 / BFCL $BFCL_CATS ==="
  mkdir -p "$OUT/bfcl-$1" && (
    cd "$OUT/bfcl-$1" && . ~/Research/bfcl-venv/bin/activate &&
    export BFCL_PROJECT_ROOT="$PWD" OPENAI_BASE_URL=http://127.0.0.1:8080/v1 OPENAI_API_KEY=local &&
    bfcl generate --model "$BFCL_HANDLER" --test-category "$BFCL_CATS" --temperature 0.001 > gen.log 2>&1 &&
    bfcl evaluate --model "$BFCL_HANDLER" --test-category "$BFCL_CATS" 2>&1 | grep -E "Accuracy" | tee eval.log
  ) || log "(bfcl failed)"
}
case "${1:-}" in
  queue)   # tinyGSM8k only for now; IFEval, BFCL and LiteRT (C) deferred
    for m in E2B E4B; do
      l=$(echo $m | tr A-Z a-z)
      [ -f "$OUT/B-$l/.tinyGSM8k.done" ] && continue
      use_model "$MODELS/gemma-4-$m-it-qat-UD-Q4_K_XL.gguf" &&
        evaluate "B-$l" "$LLAMA" "gemma4-$m" tinyGSM8k &&
        touch "$OUT/B-$l/.tinyGSM8k.done"
    done ;;
  full)     # the deferred rest: IFEval + BFCL per model, then C
    for m in E2B E4B; do
      l=$(echo $m | tr A-Z a-z)
      use_model "$MODELS/gemma-4-$m-it-qat-UD-Q4_K_XL.gguf" || continue
      evaluate "B-$l" "$LLAMA" "gemma4-$m" ifeval
      bfcl_run "D-$l"
    done
    "$0" litert ;;
  litert)
    sudo -n systemctl stop va-llm
    nohup /home/mitlab/litert-venv/bin/litert-lm serve --host 127.0.0.1 --port 9379 \
      > /tmp/litert.log 2>&1 < /dev/null &
    for _ in $(seq 60); do curl -sf localhost:9379/v1/models >/dev/null && break; sleep 2; done
    for task in tinyGSM8k ifeval; do
      evaluate C-e4b http://127.0.0.1:9379/v1/chat/completions gemma-4-E4B-it.litertlm "$task"
    done
    pgrep -f "[l]itert-lm serve" | xargs -r kill
    sudo -n systemctl start va-llm ;;
  *) echo "usage: $0 {queue|full|litert}" >&2; exit 1 ;;
esac
log "done"
