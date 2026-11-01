#!/usr/bin/env bash
# T1 Stage 1: 8 runs, E2B first. Before each, wait up to 60 min for the board to be free.
cd ~/research/toolcall
free() {
  local avail; avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
  [ "$avail" -gt 5500 ] && ! pgrep -x llama-server >/dev/null && ! pgrep -f efficient_cslr_edge >/dev/null
}
for model in e2b e4b; do
  for kv in q8_0 turbo3; do
    for iface in json code-lenient; do
      for _ in $(seq 120); do free && break; sleep 30; done
      free || { echo "$(date) not starting t1 $iface $kv $model: board busy or memory low"; exit 1; }
      echo "=== $(date) t1 $iface $kv $model ==="
      TIER=t1 KV=$kv IFACE=$iface ./run_jetson.sh $model || echo "$(date) FAILED t1 $iface $kv $model"
    done
  done
done
echo "$(date) all done"
