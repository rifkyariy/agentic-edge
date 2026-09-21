#!/usr/bin/env bash
# MMLU-Pro on the Jetson Orin Nano, same subsets and task config as the Pi.
#
#   ./std_mmlupro_jetson.sh e2b            # subset s1, thinking off
#   SUBSET=s2 ./std_mmlupro_jetson.sh e4b
#
# Differences from the Pi script, and only these:
#   * llama.cpp is started directly (there is no systemd unit here) with
#     -ngl 99 so the whole model sits on the GPU — the point of this device.
#   * its stdout is timestamped through stamp.py so parse_llama_log.py can read
#     per-request timings from a file the way it reads them from the journal.
# Everything else — task, 5-shot CoT, greedy, max_gen_toks 2048, the question
# subset, -c 8192, --cache-ram 0 — matches the Pi exactly, or the two devices
# would not be comparable.
set -uo pipefail
cd "$(dirname "$0")"
MODEL_KEY="${1:?usage: $0 e2b|e4b}"
SUBSET="${SUBSET:-s1}"
NGL="${NGL:-99}"
R=~/research
M_DIR=$R/models
S=$R/stdbench
SERVER=~/build/llama.cpp/build/bin/llama-server

case "$MODEL_KEY" in
  e2b) M=$M_DIR/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf; TAG=E2B ;;
  e4b) M=$M_DIR/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf; TAG=E4B ;;
  *) echo "unknown model key: $MODEL_KEY" >&2; exit 1 ;;
esac
OUT=$S/mmlupro100-$MODEL_KEY-$SUBSET
mkdir -p "$OUT"
SRVLOG=$OUT/server.log

pkill -f "llama-server -m" 2>/dev/null; sleep 2
echo "$(date) starting llama.cpp (CUDA, -ngl $NGL) on $TAG"
# -rea off --reasoning-budget -1 must match the Pi. Without them llama.cpp
# splits Gemma's thinking into reasoning_content, which lm-eval never reads:
# answers come back truncated or entirely empty, and the run scores far below
# what the model actually produced. This cost every Jetson MMLU-Pro run before
# 2026-09-21.
nohup sh -c "$SERVER -m $M -c 8192 --host 127.0.0.1 --port 8080 \
  -ngl $NGL -rea off --reasoning-budget -1 --cache-ram 0 2>&1 | python3 $PWD/stamp.py" \
  > "$SRVLOG" 2>&1 < /dev/null &
for _ in $(seq 150); do curl -sf localhost:8080/health >/dev/null 2>&1 && break; sleep 2; done
curl -s localhost:8080/props | grep -o '"model_path":"[^"]*"'
"$SERVER" --list-devices 2>/dev/null | grep -i cuda || true

echo "$(date) start MMLU-Pro subset100/$SUBSET  model=$TAG"
~/venvs/eval/bin/lm_eval run --model local-chat-completions \
  --model_args "model=gemma4-$TAG,base_url=http://127.0.0.1:8080/v1/chat/completions,num_concurrent=1,max_retries=3,tokenized_requests=False,timeout=3600" \
  --tasks mmlu_pro --apply_chat_template \
  --samples "$(cat "$S/mmlupro_subset100_${SUBSET}_samples.json")" \
  --log_samples --use_cache "$OUT/cache" --output_path "$OUT" \
  > "$OUT/lm_eval.log" 2>&1 && touch "$OUT/.done"
echo "$(date) end rc=$?"

pkill -f "llama-server -m" 2>/dev/null
echo finished
