#!/bin/sh
MODEL=$1; OUT=$2; REA=$3
~/llama.cpp/build/bin/llama-server -m "$MODEL" -t 4 --port 8099 --host 127.0.0.1 -c 4096 -rea $REA >/tmp/srv.log 2>&1 &
SRV=$!
for i in $(seq 1 180); do
  [ "$(curl -s --max-time 3 localhost:8099/health 2>/dev/null)" = "{\"status\":\"ok\"}" ] && break
  sleep 2
done
: > "$OUT"; n=0
while IFS= read -r p; do
  [ -z "$p" ] && continue
  n=$((n+1))
  BODY=$(python3 -c "import json,sys; print(json.dumps({\"messages\":[{\"role\":\"user\",\"content\":sys.argv[1]}],\"temperature\":0,\"max_tokens\":1024}))" "$p")
  curl -s --max-time 900 localhost:8099/v1/chat/completions -H "Content-Type: application/json" -d "$BODY" \
  | python3 -c "
import json,sys
n=\"$n\"
try:
    d=json.load(sys.stdin); m=d[\"choices\"][0][\"message\"]; u=d.get(\"usage\",{})
    c=(m.get(\"content\") or \"\").strip().replace(chr(10),\" \")[:55]
    r=(m.get(\"reasoning_content\") or \"\")
    print(f\"Q{n}: ans={c!r:58s} think_chars={len(r):5d} out_tok={u.get(\"completion_tokens\",0):4d}\")
except Exception as e: print(f\"Q{n}: ERR {e}\")
" >> "$OUT" 2>&1
done < ~/qprompts.txt
kill $SRV 2>/dev/null
