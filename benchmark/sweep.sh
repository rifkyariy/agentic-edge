#!/usr/bin/env bash
# Run a whole tier on THIS device, one command.
#
#   ./sweep.sh tier1 devices/pi5.json      # 5 conditions x 2 models
#   ./sweep.sh tier2 devices/jetson.json   # MTP x thinking, conditions B and E
#   ./sweep.sh tier3 devices/pi5.json      # quant sweep, one condition
#   ./sweep.sh all   devices/pi5.json
#
# Copying the study to a new box is: git pull, write devices/<box>.json once,
# run this. No per-device code edits, no 20 hand-typed invocations, and
# unsupported combinations skip themselves with a recorded reason rather than
# producing a mislabeled row.
#
# Plain POSIX-ish bash: macOS ships bash 3.2, so no associative arrays.
set -uo pipefail
cd "$(dirname "$0")"

TIER="${1:-}"
DEVICE="${2:-}"
[ -n "$TIER" ] && [ -n "$DEVICE" ] || {
  echo "usage: $0 {tier1|tier2|tier3|all} devices/<box>.json" >&2; exit 1; }
[ -f "$DEVICE" ] || { echo "no such device file: $DEVICE" >&2; exit 1; }

COOLDOWN="${COOLDOWN:-30}"   # seconds between runs; a throttled run is not comparable

run() {  # run <condition-file> <model-key> [cases-file]
  local cond="$1" model="$2" cases="${3:-cases.json}"
  echo
echo "======================================================================"
  echo "  $(basename "$cond" .json) / $model / $(basename "$cases" .json)"
  echo "======================================================================"
  python3 run_benchmark.py --device "$DEVICE" --condition "$cond" \
                           --model "$model" --cases "$cases" \
    || echo "  (run failed — continuing; the gap will be visible in report.py)"
  sleep "$COOLDOWN"
}

tier1() {   # headline: every architecture, both models, default settings
  for model in e2b e4b; do
    for cond in A B C D E; do
      run "conditions/$cond.json" "$model" cases.json
    done
  done
}

tier2() {   # feature trade-off: only the engines that support the toggles
  for model in e2b e4b; do
    for cond in B B-mtp B-think B-mtp-think E E-mtp E-think E-mtp-think; do
      run "conditions/$cond.json" "$model" cases_t2.json
    done
  done
}

tier3() {   # quant sweep: one condition, one model family, several quants
  for model in e4b-q4km e4b e4b-q5km e4b-q8; do
    run "conditions/B.json" "$model" cases_t3.json
  done
}

case "$TIER" in
  tier1) tier1 ;;
  tier2) tier2 ;;
  tier3) tier3 ;;
  all)   tier1; tier2; tier3 ;;
  *) echo "unknown tier: $TIER" >&2; exit 1 ;;
esac

echo
echo "done. tables:  python3 report.py t1 ; python3 report.py t2 ; ..."
