#!/bin/sh
MODEL=$1; OUT=$2; shift 2
~/llama.cpp/build/bin/llama-server -m "$MODEL" -t 4 --port 8099 --host 127.0.0.1 -c 2048 -rea off "$@" >/tmp/srv.log 2>&1 &
SRV=$!
for i in $(seq 1 180); do
  [ "$(curl -s --max-time 3 localhost:8099/health 2>/dev/null)" = "{\"status\":\"ok\"}" ] && break
  sleep 2
done
: > "$OUT"
n=0
while IFS= read -r p; do
  [ -z "$p" ] && continue
  n=$((n+1))
  printf "\n===== Q%d =====\n" "$n" >> "$OUT"
  BODY=$(python3 -c "import json,sys; print(json.dumps({\"messages\":[{\"role\":\"user\",\"content\":sys.argv[1]}],\"temperature\":0,\"max_tokens\":220}))" "$p")
  curl -s --max-time 600 localhost:8099/v1/chat/completions -H "Content-Type: application/json" -d "$BODY" \
    | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin); m=d[\"choices\"][0][\"message\"]
    c=(m.get(\"content\") or \"\").strip()
    r=(m.get(\"reasoning_content\") or \"\").strip()
    print(c if c else \"[EMPTY content; reasoning=\"+r[:80]+\"]\")
except Exception as e:
    print(\"[ERR]\", e)
" >> "$OUT" 2>&1
done < ~/qprompts.txt
kill $SRV 2>/dev/null
