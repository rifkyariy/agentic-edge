#!/bin/sh
# Install and start the queue daemon on this board. Run it on the board.
#
#   ./install_queue.sh
#
# Uses a systemd *user* unit, which works identically on both boards: the
# Jetson has no passwordless sudo, but lingering is a per-user setting and
# `loginctl enable-linger` succeeds there without it.
set -eu

BENCH=$(cd "$(dirname "$0")" && pwd)
UNIT_DIR=$HOME/.config/systemd/user
UNIT=$UNIT_DIR/agentic-queue.service

mkdir -p "$UNIT_DIR"
sed "s|__BENCH_DIR__|$BENCH|g" "$BENCH/systemd/agentic-queue.service" > "$UNIT"
echo "wrote $UNIT"

# Without lingering the unit dies at logout, which is exactly when a
# three-hour run needs it most.
loginctl enable-linger "$USER" 2>/dev/null || true
printf "linger: "; loginctl show-user "$USER" -p Linger

systemctl --user daemon-reload
systemctl --user enable --now agentic-queue.service
systemctl --user --no-pager status agentic-queue.service | head -5
