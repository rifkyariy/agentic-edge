#!/usr/bin/env bash
# Run any benchmark command with full device telemetry around it.
#
#   ./run_measured.sh mmlupro-e2b -- ./std_mmlupro.sh e2b
#   IDLE=60 ./run_measured.sh tinygsm-e4b -- ./std_run.sh queue
#   SRVLOG=~/research/stdbench/mmlupro100-e2b-s1/server.log \
#     ./run_measured.sh mmlupro-e2b-s1 -- ./std_mmlupro_jetson.sh e2b
#
# Produces <MEASURED_ROOT>/<label>-<stamp>/ (default ~/Research/measured on the
# Pi, ~/research/measured on the Jetson) containing:
#   telemetry.csv  1 Hz device samples (CPU per core, MHz, temp, throttle,
#                  memory, disk, process RSS/CPU, per-rail and total power)
#   requests.csv   per-request prompt/generation tokens and timings, from
#                  llama-server's own log, timestamped to line up with above
#   meta.json      model, server flags, governor, kernel, window boundaries
#   summary.json   energy, J/token, tok/s/W, thermals, utilisation
#   command.log    stdout+stderr of the wrapped command
#
# An idle baseline is recorded before and after the command (IDLE seconds,
# default 30) so the summary can report energy above idle rather than raw
# board draw. Keep the box otherwise quiet during a measured run.
set -uo pipefail
cd "$(dirname "$0")"
IDLE="${IDLE:-30}"
INTERVAL="${INTERVAL:-1.0}"
LABEL="${1:?usage: $0 <label> -- <command...>}"; shift
[ "${1:-}" = "--" ] && shift
[ $# -gt 0 ] || { echo "no command given" >&2; exit 1; }

# Pi keeps its tree in ~/Research, Jetson in ~/research (a symlink to the SSD).
ROOT="${MEASURED_ROOT:-}"
[ -n "$ROOT" ] || { [ -d ~/Research ] && ROOT=~/Research/measured || ROOT=~/research/measured; }
OUT=$ROOT/$LABEL-$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT"
SINCE=$(date "+%Y-%m-%d %H:%M:%S")

python3 - "$OUT" "$LABEL" "$*" <<'PY'
import json, os, subprocess, sys, time
out, label, cmd = sys.argv[1:4]
def sh(*c):
    try: return subprocess.run(c, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception: return ""
props = sh("curl", "-s", "-m", "3", "http://127.0.0.1:8080/props")
model = ""
try: model = json.loads(props).get("model_path", "")
except Exception: pass
json.dump({
    "label": label, "command": cmd, "model_path": model,
    "server_args": sh("ps", "-o", "args=", "-C", "llama-server"),
    "governor": sh("cat", "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
    "kernel": sh("uname", "-sr"), "host": sh("hostname"),
    "cpus": os.cpu_count(), "start_epoch": time.time(),
    "throttled_at_start": sh("vcgencmd", "get_throttled"),
}, open(os.path.join(out, "meta.json"), "w"), indent=1)
PY

echo "[$(date +%H:%M:%S)] telemetry -> $OUT/telemetry.csv (idle baseline ${IDLE}s)"
python3 telemetry.py --out "$OUT/telemetry.csv" --interval "$INTERVAL" &
TELE=$!
trap 'kill $TELE 2>/dev/null' EXIT
sleep "$IDLE"

WORK_START=$(date +%s)
echo "[$(date +%H:%M:%S)] running: $*"
"$@" > "$OUT/command.log" 2>&1 &
WORK_PID=$!

# meta.json's server_args is captured before the command starts, so it records
# whatever was already running -- the idle deployed server on the Pi, nothing at
# all on the Jetson. That is how a missing -rea survived days of review. Take a
# second sample once the run's own server is up, and keep it under a separate
# key so the original field's meaning does not change under anything already
# reading it.
( for _ in $(seq 60); do
    sleep 5
    ARGS=$(ps -o args= -C llama-server 2>/dev/null | head -1)
    # little-gemma (S3): the engine, plus the shim whose --thinking is half the config
    [ -n "$ARGS" ] || ARGS=$(ps -o args= -C run-cuda-i8 2>/dev/null | head -1)
    [ -n "$ARGS" ] && [ -z "${ARGS##*run-cuda-i8*}" ] && \
      ARGS="$ARGS | $(pgrep -af '^python3 .*[l]g_openai_shim[.]py' | head -1 | cut -d' ' -f2-)"
    [ -n "$ARGS" ] || continue
    python3 - "$OUT" "$ARGS" <<'CAPTURE'
import json, sys
out, args = sys.argv[1], sys.argv[2]
p = out + "/meta.json"
m = json.load(open(p))
if m.get("server_args_after"):
    raise SystemExit(0)
m["server_args_after"] = args
json.dump(m, open(p, "w"), indent=1)
CAPTURE
    break
  done ) &
CAPTURE_PID=$!

wait "$WORK_PID"
RC=$?
# Do not leave the sampler polling for five minutes after a short run, and
# never let it write meta.json while summarize_run.py is reading it.
kill "$CAPTURE_PID" 2>/dev/null
wait "$CAPTURE_PID" 2>/dev/null
WORK_END=$(date +%s)
echo "[$(date +%H:%M:%S)] command finished rc=$RC; idle tail ${IDLE}s"

sleep "$IDLE"
kill $TELE 2>/dev/null; wait $TELE 2>/dev/null
UNTIL=$(date "+%Y-%m-%d %H:%M:%S")

# The Pi reads llama-server's timings from the journal; the Jetson has no unit,
# so SRVLOG points at a stamp.py-prefixed server log written by the run script.
if [ -n "${SRVLOG:-}" ] && [ -f "$SRVLOG" ]; then
  python3 parse_llama_log.py --file "$SRVLOG" --out "$OUT/requests.csv"
else
  python3 parse_llama_log.py --since "$SINCE" --until "$UNTIL" --out "$OUT/requests.csv"
fi
python3 - "$OUT" "$WORK_START" "$WORK_END" "$RC" <<'PY'
import json, sys
out, ws, we, rc = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
p = out + "/meta.json"; m = json.load(open(p))
m.update(work_start_epoch=ws, work_end_epoch=we, exit_code=rc)
json.dump(m, open(p, "w"), indent=1)
PY
python3 summarize_run.py --dir "$OUT" --idle-pre "$IDLE" --idle-post "$IDLE"
echo "results in $OUT"
exit $RC
