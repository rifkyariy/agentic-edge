#!/usr/bin/env bash
# Push this repo's files to their flat, hardcoded locations on the Pi and
# restart the matching service(s). The repo is organised by kind (services/,
# web/, config/, systemd/) for readability; the Pi is not — every unit's
# ExecStart/EnvironmentFile names an absolute /opt or /etc path, so this
# script is what maps one layout onto the other.
#
# Usage:
#   ./deploy.sh                 deploy + restart every code target below
#   ./deploy.sh asr tts web     deploy + restart just those targets
#   ./deploy.sh units           push systemd/*.service, then daemon-reload
#                                (does NOT enable or restart anything)
#   ./deploy.sh config          push config/config.env -> /etc/voice-agent/
#                                (does NOT restart anything: every service
#                                reads this file, and runtime.env holds the
#                                UI's live choices — review the diff first)
#
# Plain `case`, not an associative array: macOS ships bash 3.2, which has no
# associative arrays at all, and this needs to run there without asking for
# a newer bash first.
set -euo pipefail
cd "$(dirname "$0")"

HOST=MITLAB-EDGE
OPT=/opt/voice-agent
ETC=/etc/voice-agent
CODE_TARGETS="asr tts tools orchestrator web ui prompt"

# Prints "local_path remote_path unit" (unit may be empty) for a target name.
target_spec() {
  case "$1" in
    asr)          echo "services/asr_service.py $OPT/asr_service.py va-asr" ;;
    tts)          echo "services/tts_service.py $OPT/tts_service.py va-tts" ;;
    tools)        echo "services/tools_service.py $OPT/tools_service.py va-tools" ;;
    orchestrator) echo "services/orchestrator.py $OPT/orchestrator.py va-orchestrator" ;;
    web)          echo "services/web_service.py $OPT/web_service.py va-web" ;;
    ui)           echo "web/ui.html $OPT/ui.html va-web" ;;
    prompt)       echo "config/system-prompt.txt $OPT/system-prompt.txt va-orchestrator" ;;
    *)            return 1 ;;
  esac
}

deploy_one() {
  local spec local_path remote_path unit
  spec="$(target_spec "$1")" || { echo "unknown target: $1 (have: $CODE_TARGETS units config)" >&2; exit 1; }
  read -r local_path remote_path unit <<< "$spec"
  echo "==> $1: $local_path -> $HOST:$remote_path"
  scp -q "$local_path" "$HOST:$remote_path"
  if [ -n "$unit" ]; then
    ssh "$HOST" "sudo systemctl restart $unit && systemctl is-active $unit"
  fi
}

case "${1:-}" in
  units)
    echo "==> systemd/*.service -> $HOST:/etc/systemd/system/"
    scp -q systemd/*.service "$HOST:/tmp/"
    ssh "$HOST" "sudo mv /tmp/va-*.service /etc/systemd/system/ && sudo systemctl daemon-reload"
    echo "Units updated. Nothing restarted — enable/start what you need explicitly."
    ;;
  config)
    echo "==> config/config.env -> $HOST:$ETC/config.env"
    echo "Diff against the live file first:"
    ssh "$HOST" "cat $ETC/config.env" | diff -u - config/config.env || true
    read -p "Push anyway? [y/N] " ok
    [ "$ok" = y ] || exit 1
    scp -q config/config.env "$HOST:/tmp/config.env"
    ssh "$HOST" "sudo mv /tmp/config.env $ETC/config.env"
    echo "Deployed. Every va-* unit reads this file — restart them yourself when ready."
    ;;
  "")
    for t in $CODE_TARGETS; do deploy_one "$t"; done
    ;;
  *)
    for t in "$@"; do deploy_one "$t"; done
    ;;
esac
