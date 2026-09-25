#!/usr/bin/env bash
# MMLU-Pro through little-gemma (CUDA int8) on the Jetson Orin Nano — the S3 rows.
#
#   ./std_mmlupro_lg_jetson.sh e2b                        # subset s1, thinking off
#   SUBSET=s2 THINKING=on ./std_mmlupro_lg_jetson.sh e4b
#
# The same run as std_mmlupro_jetson.sh with only the engine swapped: same
# GGUF files, subsets, task, 5-shot CoT, greedy, 2048-token answer budget,
# 8192 context, and the same prompt byte for byte (lg_openai_shim.py renders
# it as llama-server does; tests/test_lg_shim.py holds it to that).
#
# little-gemma has no HTTP, so lg_openai_shim.py fronts it on :8080 and
# launches the engine itself. The llama.cpp flags map onto it as:
#   -rea off|on               -> shim --thinking off|on (<|think|> in the system turn)
#   --reasoning-budget -1|320 -> engine -think -1|320
#   --reasoning-format none   -> the shim returns thoughts inline, always
#   -c 8192 / answer 2048     -> SERVE_SEQ / SERVE_GEN, compiled in (setup_jetson.sh)
#   --cache-ram 0             -> no prompt cache exists to limit
# Build the engine first: ./little_gemma/setup_jetson.sh
set -uo pipefail
cd "$(dirname "$0")"
MODEL_KEY="${1:?usage: $0 e2b|e4b}"
SUBSET="${SUBSET:-s1}"
THINKING="${THINKING:-off}"
BUDGET=-1
[ "$THINKING" = on ] && BUDGET="${BUDGET_ON:-320}"
R=~/research
M_DIR=$R/models
S=$R/stdbench
ENGINE=~/build/little-gemma/build/run-cuda-i8

case "$MODEL_KEY" in
  e2b) M=$M_DIR/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf; TAG=E2B ;;
  e4b) M=$M_DIR/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf; TAG=E4B ;;
  *) echo "unknown model key: $MODEL_KEY" >&2; exit 1 ;;
esac
[ -x "$ENGINE" ] || { echo "no $ENGINE — run ./little_gemma/setup_jetson.sh" >&2; exit 1; }
OUT=$S/mmlupro100-lg-$MODEL_KEY-$SUBSET
[ "$THINKING" = on ] && OUT=$OUT-think
mkdir -p "$OUT"
SRVLOG=$OUT/server.log
cp ~/build/little-gemma/build/BUILD_INFO "$OUT/engine_build.txt" 2>/dev/null

stop_servers() {   # by pid, bracketed patterns: never match this script or an ssh line
  pgrep -f "[l]g_openai_shim.py" | xargs -r kill
  pgrep -f "[l]lama-server -m" | xargs -r kill
  sleep 3
  pgrep -f "[r]un-cuda-i8 -m" | xargs -r kill   # the shim takes its engine down; belt and braces
}
stop_servers
echo "$(date) starting little-gemma (CUDA int8) on $TAG, thinking=$THINKING budget=$BUDGET"
nohup sh -c "python3 $PWD/lg_openai_shim.py --engine $ENGINE -m $M \
  --thinking $THINKING --think $BUDGET --port 8080 2>&1 | python3 $PWD/stamp.py little-gemma" \
  > "$SRVLOG" 2>&1 < /dev/null &
# E4B's first load spends ~150s in the engine's warmup on this board
for _ in $(seq 300); do curl -sf localhost:8080/health >/dev/null 2>&1 && break; sleep 2; done
curl -s localhost:8080/props; echo

echo "$(date) start MMLU-Pro subset100/$SUBSET  model=$TAG engine=little-gemma thinking=$THINKING"
~/venvs/eval/bin/lm_eval run --model local-chat-completions \
  --model_args "model=gemma4-$TAG,base_url=http://127.0.0.1:8080/v1/chat/completions,num_concurrent=1,max_retries=3,tokenized_requests=False,timeout=3600" \
  --tasks mmlu_pro --apply_chat_template \
  --samples "$(cat "$S/mmlupro_subset100_${SUBSET}_samples.json")" \
  --log_samples --use_cache "$OUT/cache" --output_path "$OUT" \
  > "$OUT/lm_eval.log" 2>&1 && touch "$OUT/.done"
echo "$(date) end rc=$?"

stop_servers
echo finished
