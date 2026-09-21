#!/bin/sh
# Run a list of MMLU-Pro subsets back to back on the Jetson, one at a time.
#
#   ./queue_jetson.sh e4b s2 s3
#
# Each run gets a free-memory precheck first. E4B peaks at ~5,630 MB resident on
# a 7,485 MB board with no swap, so a second workload of even ~500 MB is enough
# for the OOM killer to take llama-server mid-run — which is how s2 died at
# question 94 after 2h39m. Refusing to start costs seconds; finding out three
# hours in costs the run.
set -eu

MODEL="${1:?usage: queue_jetson.sh <e2b|e4b> <subset>...}"
shift
[ $# -gt 0 ] || { echo "no subsets given" >&2; exit 1; }

case "$MODEL" in
  # E4B's 5,630 MB peak is larger than the board ever has free; it fits only
  # because the kernel reclaims page cache under pressure, which is how s1
  # succeeded with 165 MB to spare. So the gate is "is the box otherwise
  # clean", not "does the peak fit" — the latter is never true here.
  e4b) NEED_MB=5400 ;;          # 5,630 observed peak, minus reclaimable cache
  e2b) NEED_MB=3900 ;;          # 3,600 observed peak
  *)   echo "unknown model: $MODEL" >&2; exit 1 ;;
esac

BENCH="$HOME/research/agentic-edge/benchmark"
STD="$HOME/research/stdbench"
cd "$BENCH"

echo "queue: $MODEL $* (redirect stdout to keep a log)"

for S in "$@"; do
  RUN="mmlupro100-$MODEL-$S"
  echo "=== $(date '+%F %T')  $RUN"

  if [ -d "$STD/$RUN" ]; then
    echo "!! $STD/$RUN already exists — move it aside first (a stale lm-eval"
    echo "   cache there is replayed instead of regenerated). Skipping."
    continue
  fi

  AVAIL=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
  if [ "$AVAIL" -lt "$NEED_MB" ]; then
    echo "!! only ${AVAIL} MB available, $MODEL needs ~${NEED_MB} MB. Who else is on the box:"
    ps -eo user,rss --no-headers | awk '{s[$1]+=$2} END {for (u in s) if (s[u] > 51200) printf "     %-10s %5d MB\n", u, s[u]/1024}'
    echo "   Aborting the queue rather than starting a run that will be killed."
    exit 1
  fi
  echo "   ${AVAIL} MB available, need ~${NEED_MB} MB — ok"

  SRVLOG="$STD/$RUN/server.log" SUBSET="$S" \
    ./run_measured.sh "mmlupro-$MODEL-$S" -- env SUBSET="$S" ./std_mmlupro_jetson.sh "$MODEL" \
    || echo "!! run_measured returned $? for $RUN"

  # run_measured.sh trusts the run script's exit status, and
  # std_mmlupro_jetson.sh ends on `echo finished` so it always returns 0.
  # The .done marker is the honest signal.
  if [ -f "$STD/$RUN/.done" ]; then
    echo "   $RUN completed"
  else
    echo "!! $RUN did NOT complete — no .done marker. Stopping the queue."
    tail -3 "$STD/$RUN/lm_eval.log" 2>/dev/null
    exit 1
  fi
done

echo "=== $(date '+%F %T')  queue finished"
