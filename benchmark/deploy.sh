#!/usr/bin/env bash
# Put the committed benchmark/ tree on the boards. Run it on the Mac.
#
#   benchmark/deploy.sh               both boards
#   benchmark/deploy.sh pi            one board (pi | jetson)
#   benchmark/deploy.sh --allow-dirty include uncommitted changes (recorded)
#
# What it guarantees, and why each step exists:
#
#   1. Only committed code, unless --allow-dirty. The boards used to run
#      scp'd files tens of commits behind git with no record of which; each
#      deploy now writes benchmark/DEPLOYED.json (commit, time, dirty).
#   2. Tests first, in a staging copy ON the board. Board-specific bugs have
#      been the norm (AGENTS §7), so passing on the Mac is not enough. A
#      failure stops that board before anything live is touched.
#   3. Never a run's own scripts while it runs. rsync replaces each file via
#      a temp file and rename, so a running bash keeps reading the old one
#      (AGENTS §4.1 was scp truncating in place). But a run invokes other
#      scripts later (summarize_run.py, parse_llama_log.py ...), and swapping
#      those mid-run would mix versions in one result. So while a board is
#      busy only the queue's control files are deployed; the rest waits,
#      and is listed.
#   4. No restart mid-run. An idle daemon is restarted; a busy one reloads
#      itself between jobs when its code has changed (queue_runner.py).
set -uo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"

DIRTY=0
TARGETS=()
for a in "$@"; do
  case "$a" in
    --allow-dirty) DIRTY=1 ;;
    pi|jetson) TARGETS+=("$a") ;;
    all) TARGETS=(pi jetson) ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "unknown argument: $a" >&2; exit 2 ;;
  esac
done
[ ${#TARGETS[@]} -eq 0 ] && TARGETS=(pi jetson)

# Case differs per board (AGENTS §2): ~/Research on the Pi, ~/research on the Jetson.
host_of() { case "$1" in pi) echo MITLAB-EDGE ;; jetson) echo MITLAB-JETSON ;; esac; }
repo_of() { case "$1" in pi) echo Research/agentic-edge ;; jetson) echo research/agentic-edge ;; esac; }

# The queue's own files: safe to replace while a run is in flight, because the
# run never reads them. Everything else under benchmark/ is the run's.
CONTROL='^benchmark/(queue_ctl\.py|queue_runner\.py|jobqueue/|job_kinds\.json|baselines\.json|probe_status\.py|run_detail\.py|tests/|systemd/|install_queue\.sh|deploy\.sh)'

if [ -n "$(git status --porcelain -- benchmark)" ]; then
  if [ $DIRTY -eq 0 ]; then
    echo "benchmark/ has uncommitted changes; commit them, or pass --allow-dirty" >&2
    git status --short -- benchmark >&2
    exit 1
  fi
  echo "warning: deploying uncommitted changes (recorded as dirty)"
fi
COMMIT=$(git rev-parse --short HEAD)
LIST=$(mktemp); CTRL=$(mktemp)
trap 'rm -f "$LIST" "$CTRL"' EXIT
{ git ls-files benchmark
  [ $DIRTY -eq 1 ] && git ls-files --others --exclude-standard benchmark
} | grep -v '__pycache__' | sort -u > "$LIST"
grep -E "$CONTROL" "$LIST" > "$CTRL"

STATUS=0
for b in "${TARGETS[@]}"; do
  H=$(host_of "$b"); R=$(repo_of "$b")
  echo "== $b ($H)"

  busy=$(ssh "$H" 'pgrep -fa "[l]m_eval|[r]un_measured|[s]td_mmlupro|[s]td_run|[p]i5_run" | cut -c1-100')
  active=$(ssh "$H" "cd ~/$R/benchmark && python3 queue_ctl.py --status" 2>/dev/null |
           python3 -c 'import json,sys; a=json.load(sys.stdin).get("active"); print(a["label"] if a else "")' 2>/dev/null)

  # A daemon started before self-reload existed cannot pick up new code by
  # itself; it needs one restart, which is only safe when its queue is idle.
  # Asked of the running daemon, not the file on disk: a deploy may already
  # have replaced queue_runner.py under a daemon still running the old code.
  legacy=$(ssh "$H" 'q=$HOME/'"${R%/agentic-edge}"'/queue
    d=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[\"pid\"])" "$q/daemon.json" 2>/dev/null)
    [ -n "$d" ] && [ "$d" = "$(cat "$q/runner.pid" 2>/dev/null)" ] || echo yes')

  # 1. stage and test on the board
  ssh "$H" "rm -rf ~/$R/.deploy-staging && mkdir -p ~/$R/.deploy-staging" || { STATUS=1; continue; }
  if ! rsync -a --files-from="$LIST" ./ "$H:$R/.deploy-staging/"; then
    echo "   rsync to staging failed; nothing live was touched" >&2; STATUS=1; continue
  fi
  if ! ssh "$H" "cd ~/$R/.deploy-staging/benchmark &&
                 python3 -m unittest discover -s tests > ../tests.log 2>&1; rc=\$?;
                 tail -1 ../tests.log | sed 's/^/   tests: /'; exit \$rc"; then
    echo "   TESTS FAILED on $b; nothing live was touched. Log: ~/$R/.deploy-staging/tests.log" >&2
    STATUS=1; continue
  fi

  # 2. choose what goes live
  if [ -n "$busy" ]; then
    use="$CTRL"
    echo "   busy — deploying the queue's control files only:"
    echo "$busy" | sed 's/^/     /'
    rsync -a --checksum --dry-run --itemize-changes --files-from="$LIST" ./ "$H:$R/" |
      awk '$1 ~ /^[<>]f/ {print $2}' | grep -vE "$CONTROL" | sed 's/^/     deferred until idle: /'
  else
    use="$LIST"
  fi

  # 3. staging -> live, on the board (per-file temp + rename, never in place)
  ssh "$H" "cd ~/$R && rsync -a --files-from=- .deploy-staging/ ./" < "$use" || { STATUS=1; continue; }
  partial=$([ "$use" = "$CTRL" ] && echo true || echo false)
  ssh "$H" "cat > ~/$R/benchmark/DEPLOYED.json" <<EOF
{"commit": "$COMMIT", "dirty": $([ $DIRTY -eq 1 ] && echo true || echo false), "partial": $partial, "at": "$(date '+%Y-%m-%dT%H:%M:%S%z')"}
EOF

  # 4. the unit file, only if it changed; daemon-reload never restarts it
  ssh "$H" "cd ~/$R/benchmark && B=\$(pwd) && sed \"s|__BENCH_DIR__|\$B|g\" systemd/agentic-queue.service |
            cmp -s - ~/.config/systemd/user/agentic-queue.service ||
            { sed \"s|__BENCH_DIR__|\$B|g\" systemd/agentic-queue.service > ~/.config/systemd/user/agentic-queue.service &&
              systemctl --user daemon-reload && echo '   unit file updated (daemon-reload, no restart)'; }"

  # 5. the daemon
  if [ -z "$active" ] && [ -z "$busy" ]; then
    ssh "$H" 'systemctl --user restart agentic-queue && sleep 2 && systemctl --user is-active agentic-queue' |
      sed 's/^/   daemon restarted: /'
  elif [ -n "$active" ] && [ -n "$legacy" ]; then
    echo "   daemon kept running job $active. It predates self-reload, so run"
    echo "   deploy.sh $b again once its queue is empty to restart it once."
  elif [ -n "$active" ]; then
    echo "   daemon kept running: it reloads itself after job $active"
  else
    ssh "$H" 'systemctl --user restart agentic-queue && sleep 2 && systemctl --user is-active agentic-queue' |
      sed 's/^/   daemon restarted (its queue was idle; the busy run is outside it): /'
  fi
  echo "   deployed $COMMIT$([ $DIRTY -eq 1 ] && echo ' (dirty)')$([ "$partial" = true ] && echo ', control files only')"
done
exit $STATUS
