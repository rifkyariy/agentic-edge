#!/usr/bin/env bash
# Pi 5 driver: sweep.sh plus the server juggling this box needs.
# The engines share 8GB and four cores, so each condition gets its server
# alone: little-gemma (A) and LiteRT-LM (C) run with va-llm stopped.
#
#   ./pi5_run.sh sanity    # A/e2b only — check fabrication ~100% first
#   ./pi5_run.sh tier1     # A B D E x {e2b,e4b}
#   ./pi5_run.sh tier2     # MTP x thinking, B and E
#   ./pi5_run.sh tier3     # E4B quant sweep, B
#   ./pi5_run.sh litert    # condition C, run after everything else
#
# Condition E runs single-turn (VA_HISTORY_TURNS=0), like B and D: with
# history on, repeat n sees repeat n-1's answer and can copy it instead of
# calling the tool. Restored to the deployed default on exit.
set -uo pipefail
cd "$(dirname "$0")"
DEV=devices/pi5.json
COOLDOWN="${COOLDOWN:-60}"
MODELS=/home/mitlab/models
RT=/etc/voice-agent/runtime.env
export LG_SOCK=/tmp/lg.sock

log() { echo "[$(date +%H:%M:%S)] $*"; }

wait_llama() {
  for _ in $(seq 150); do curl -sf localhost:8080/health >/dev/null && return; sleep 2; done
  log "va-llm did not come up"; return 1
}

lg_up() {   # lg_up <gguf>
  sudo -n systemctl stop va-llm little-gemma
  pgrep -f "[b]uild-fast/run -m" | xargs -r kill; sleep 2
  rm -f "$LG_SOCK"
  nohup /home/mitlab/little-gemma/build-fast/run -m "$1" -s "$LG_SOCK" \
    > /tmp/lg.log 2>&1 < /dev/null &
  for _ in $(seq 120); do [ -S "$LG_SOCK" ] && return; sleep 2; done
  log "little-gemma did not come up"; return 1
}

lg_down() {
  pgrep -f "[b]uild-fast/run -m" | xargs -r kill; sleep 2
  sudo -n systemctl start va-llm && wait_llama
}

history() {  # history off|restore
  sudo -n sed -i '/^VA_HISTORY_TURNS=/d' "$RT"
  [ "$1" = off ] && echo "VA_HISTORY_TURNS=0" | sudo -n tee -a "$RT" >/dev/null
  sudo -n systemctl restart va-orchestrator
}

run() {  # run <cond> <model> [extra args]
  local cond="$1" model="$2"; shift 2
  log "=== $cond / $model ==="
  python3 run_benchmark.py --device "$DEV" --condition "conditions/$cond.json" \
    --model "$model" "$@" || log "(run failed — continuing)"
  sleep "$COOLDOWN"
}

case "${1:-}" in
  sanity)
    lg_up "$MODELS/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf" && run A e2b --repeat 2
    lg_down ;;
  tier1)
    trap 'history restore' EXIT
    history off
    for model in e2b e4b; do
      M=$(echo "$model" | tr a-z A-Z)
      lg_up "$MODELS/gemma-4-$M-it-qat-UD-Q4_K_XL.gguf" && run A "$model" --repeat 2
      lg_down
      for cond in B D E; do run "$cond" "$model"; done
    done
    ;;
  tier2)
    trap 'history restore' EXIT
    history off
    for model in e2b e4b; do
      for cond in B B-mtp B-think B-mtp-think E E-mtp E-think E-mtp-think; do
        run "$cond" "$model" --cases cases_t2.json
      done
    done
    # leave va-llm as deployed: MTP and thinking off
    for k in mtp reasoning; do
      curl -s localhost:8090/option -H 'Content-Type: application/json' \
        -d "{\"key\":\"$k\",\"value\":\"off\"}"; echo
    done ;;
  tier3)
    for model in e4b-q4km e4b e4b-q5km e4b-q8; do
      run B "$model" --cases cases_t3.json
      ps -o rss= -C llama-server | awk '{printf "  llama-server RSS %.2f GiB\n", $1/2^20}'
    done ;;
  litert)   # last, as asked: its own server, va-llm out of the way
    sudo -n systemctl stop va-llm
    nohup /home/mitlab/litert-venv/bin/litert-lm serve --host 127.0.0.1 --port 9379 \
      > /tmp/litert.log 2>&1 < /dev/null &
    for _ in $(seq 60); do curl -sf localhost:9379/v1/models >/dev/null && break; sleep 2; done
    for model in e2b e4b; do run C "$model"; done
    pgrep -f "[l]itert-lm serve" | xargs -r kill
    sudo -n systemctl start va-llm && wait_llama ;;
  *) echo "usage: $0 {sanity|tier1|tier2|tier3|litert}" >&2; exit 1 ;;
esac
log "done"
