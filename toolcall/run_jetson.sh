#!/usr/bin/env bash
# T0 JSON tool-calling baseline on the Jetson (plan §8): the TurboQuant fork,
# thinking off, one KV type, one model.
#
#   ./run_jetson.sh e2b                  # KV=q8_0
#   KV=turbo3 LIMIT=20 ./run_jetson.sh e4b
#   TAG=r2 ./run_jetson.sh e2b           # a repeat, in its own folder
#
# Stops the voice agent's units (they hold the GPU) and leaves them stopped:
#   systemctl --user start va-llm va-asr va-tts va-tools va-orchestrator va-web
set -euo pipefail
cd "$(dirname "$0")"
MODEL_KEY="${1:?usage: $0 e2b|e4b}"
KV="${KV:-q8_0}"
TQ="${TQ_COMMIT:-bcb85fc}"
PORT=8090
SERVER=~/build/engines/llama.cpp-turboquant-$TQ/build/bin/llama-server
case "$MODEL_KEY" in
  e2b) M=~/research/models/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf ;;
  e4b) M=~/research/models/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf ;;
  *) echo "unknown model key: $MODEL_KEY" >&2; exit 1 ;;
esac
OUT=runs/t0-json-$KV-off-$MODEL_KEY${LIMIT:+-smoke$LIMIT}${TAG:+-$TAG}
mkdir -p "$OUT"

systemctl --user stop va-web va-orchestrator va-tools va-tts va-asr va-llm 2>/dev/null || true
if pgrep -x llama-server >/dev/null; then
  echo "another llama-server is running; refusing to share the GPU:" >&2; pgrep -ax llama-server >&2; exit 1
fi

"$SERVER" -m "$M" --jinja -c 8192 -ngl 99 -ctk "$KV" -ctv "$KV" -fa on \
  -np 1 -b 512 -ub 512 --cache-ram 0 -rea off --reasoning-budget -1 \
  --temp 0 --top-k 1 --seed 42 -n 1024 --host 127.0.0.1 --port $PORT \
  > "$OUT/server.log" 2>&1 < /dev/null &
SRV=$!
TEGRA=""
cleanup() { [ -n "$TEGRA" ] && kill "$TEGRA" 2>/dev/null; kill "$SRV" 2>/dev/null; wait 2>/dev/null; true; }
trap cleanup EXIT
for _ in $(seq 150); do curl -sf localhost:$PORT/health >/dev/null 2>&1 && break; sleep 2; done
curl -sf localhost:$PORT/health >/dev/null || { echo "server did not come up:" >&2; tail -20 "$OUT/server.log" >&2; exit 1; }

# captured from the running process, not from this script (the meta.json lesson)
python3 - "$OUT/manifest.json" "$SRV" "$M" "$PORT" "$(dirname "$SERVER")/../.." <<'EOF'
import hashlib, json, subprocess, sys, time, urllib.request
out, pid, model, port, src = sys.argv[1:]
sh = lambda *c: subprocess.run(c, capture_output=True, text=True).stdout.strip()
# streamed: reading a 4 GB GGUF whole beside a loaded E4B server OOM-killed this step
sha = lambda p: hashlib.file_digest(open(p, "rb"), "sha256").hexdigest()
cat = lambda p: open(p).read().strip()
gpu = "/sys/devices/platform/bus@0/17000000.gpu/devfreq/17000000.gpu/"
props = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/props"))
json.dump({
    "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "server_argv": open(f"/proc/{pid}/cmdline").read().split("\0")[:-1],
    "fork_commit": sh("git", "-C", src, "rev-parse", "HEAD"),
    "model_sha256": sha(model),
    "chat_template_sha256": hashlib.sha256(props.get("chat_template", "").encode()).hexdigest(),
    "power_mode": sh("nvpmodel", "-q"),
    # locked by jetson_clocks when min == max; the lock does not survive a reboot
    "gpu_freq_min_max": [cat(gpu + "min_freq"), cat(gpu + "max_freq")],
    "cpu0_freq_min_max": [cat("/sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq"),
                          cat("/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq")],
    "tasks_sha256": sha("tasks/t0.jsonl"),
    "harness_sha256": {f: sha(f) for f in ("run_json.py", "score.py", "run_jetson.sh")},
}, open(out, "w"), indent=2)
EOF

python3 run_json.py tasks/t0.jsonl "$OUT/warmup.jsonl" --url http://127.0.0.1:$PORT --limit 1 >/dev/null
tegrastats --interval 1000 --logfile "$OUT/tegrastats.log" & TEGRA=$!
python3 run_json.py tasks/t0.jsonl "$OUT/results.jsonl" --url http://127.0.0.1:$PORT ${LIMIT:+--limit $LIMIT}
python3 score.py tasks/t0.jsonl "$OUT/results.jsonl"
