#!/usr/bin/env bash
# S8: MMLU-Pro with a TurboQuant-compressed KV cache, both boards.
#
#   SUBSET=s1 THINKING=off ./std_mmlupro_tq.sh e2b
#   KV=turbo4 ./std_mmlupro_tq.sh e4b          # default turbo3
#
# The S1/S2 task unchanged — same GGUFs, subsets, 5-shot CoT, greedy,
# max_gen_toks 2048, -c 8192, --cache-ram 0, -rea/--reasoning-budget/
# --reasoning-format per thinking mode — served by the pinned TurboQuant fork
# (engines/build_turboquant.sh) with -ctk/-ctv $KV. Only the engine build and
# the KV cache type differ from S1/S2.
#
# Effective types are K=q8_0, V=$KV: for Gemma 4's GQA 8:1 the fork upgrades K
# itself ("auto-asymmetric", in server.log). TURBO_AUTO_ASYMMETRIC=0 turns
# that off; it is left at the fork's default on purpose.
#
# The fork is launched directly on both boards (the Pi's va-llm unit is pinned
# to the deployed build), so the Pi stops va-llm for the run and starts it
# again on exit, and both boards log through stamp.py for SRVLOG. The Pi keeps
# the thread count va-llm serves the baseline with.
set -uo pipefail
cd "$(dirname "$0")"
MODEL_KEY="${1:?usage: $0 e2b|e4b}"
SUBSET="${SUBSET:-s1}"
THINKING="${THINKING:-off}"
KV="${KV:-turbo3}"
TQ="${TQ_COMMIT:-bcb85fc}"
FMT=""
[ "$THINKING" = on ] && FMT="--reasoning-format none"
BUDGET=-1
[ "$THINKING" = on ] && BUDGET="${BUDGET_ON:-320}"

if [ -d ~/Research ]; then
  R=~/Research; M_DIR=/home/mitlab/models; LMEVAL=~/Research/eval-venv/bin/lm_eval
  THREADS=$(sed -n 's/^VA_LLM_THREADS=//p' /etc/voice-agent/runtime.env | tail -1)
  DEV="-t ${THREADS:-3}"; PI=1; E=~/Research/engines
else
  R=~/research; M_DIR=$R/models; LMEVAL=~/venvs/eval/bin/lm_eval
  DEV="-ngl ${NGL:-99}"; PI=0; E=~/build/engines
fi
S=$R/stdbench
SERVER=$E/llama.cpp-turboquant-$TQ/build/bin/llama-server
[ -x "$SERVER" ] || { echo "no TurboQuant build at $SERVER — run engines/build_turboquant.sh" >&2; exit 1; }

case "$MODEL_KEY" in
  e2b) M=$M_DIR/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf; TAG=E2B ;;
  e4b) M=$M_DIR/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf; TAG=E4B ;;
  *) echo "unknown model key: $MODEL_KEY" >&2; exit 1 ;;
esac
OUT=$S/mmlupro100-tq-$MODEL_KEY-$SUBSET
[ "$THINKING" = on ] && OUT=$OUT-think
mkdir -p "$OUT"
SRVLOG=$OUT/server.log
cp "$(dirname "$SERVER")/../BUILD_INFO" "$OUT/engine_build.txt" 2>/dev/null

stop_server() { pgrep -f "[l]lama-server -m" | xargs -r kill 2>/dev/null; sleep 2; }
restore() {
  stop_server
  [ "$PI" = 1 ] && sudo -n systemctl start va-llm
}
trap restore EXIT
[ "$PI" = 1 ] && sudo -n systemctl stop va-llm
stop_server

echo "$(date) starting TurboQuant llama.cpp ($TQ, KV $KV, $DEV) on $TAG"
nohup sh -c "$SERVER -m $M $DEV -c 8192 --host 127.0.0.1 --port 8080 \
  -ctk $KV -ctv $KV -rea $THINKING --reasoning-budget $BUDGET $FMT --cache-ram 0 2>&1 | python3 $PWD/stamp.py" \
  > "$SRVLOG" 2>&1 < /dev/null &
for _ in $(seq 150); do curl -sf localhost:8080/health >/dev/null 2>&1 && break; sleep 2; done
curl -sf localhost:8080/health >/dev/null || { echo "server did not come up; tail of $SRVLOG:" >&2; tail -20 "$SRVLOG" >&2; exit 1; }
ps -o args= -C llama-server

echo "$(date) start MMLU-Pro subset100/$SUBSET  model=$TAG thinking=$THINKING kv=$KV"
"$LMEVAL" run --model local-chat-completions \
  --model_args "model=gemma4-$TAG,base_url=http://127.0.0.1:8080/v1/chat/completions,num_concurrent=1,max_retries=3,tokenized_requests=False,timeout=3600" \
  --tasks mmlu_pro --apply_chat_template \
  --samples "$(cat "$S/mmlupro_subset100_${SUBSET}_samples.json")" \
  --log_samples --use_cache "$OUT/cache" --output_path "$OUT" \
  > "$OUT/lm_eval.log" 2>&1 && touch "$OUT/.done"
echo "$(date) end rc=$?"
echo finished
