#!/usr/bin/env python3
"""JSON tool calling against a running llama-server (plan §6.1). Stdlib only.

One model call per task: T0's BFCL categories are single-turn, and parallel
calls arrive together in one response. Resumable: tasks already in the
results file are skipped.

    python3 run_json.py tasks/t0.jsonl runs/<name>/results.jsonl [--url ...] [--limit N]
"""
import argparse, json, time, urllib.error, urllib.request
from pathlib import Path


def ask(url, task, max_tokens, timeout):
    body = {"messages": task["messages"], "tools": task["tools"], "tool_choice": "auto",
            "parallel_tool_calls": True, "temperature": 0, "top_k": 1, "seed": 42,
            "max_tokens": max_tokens, "cache_prompt": False}  # no reuse between tasks (plan §8.3)
    req = urllib.request.Request(url + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def run_one(url, task, max_tokens, timeout):
    t0 = time.time()
    rec = {"id": task["id"]}
    try:
        resp = ask(url, task, max_tokens, timeout)
    except TimeoutError:
        return {**rec, "outcome": "timeout", "wall_s": round(time.time() - t0, 3)}
    except (urllib.error.URLError, OSError) as e:
        return {**rec, "outcome": "http_error", "error": str(e), "wall_s": round(time.time() - t0, 3)}
    choice = resp["choices"][0]
    msg = choice["message"]
    rec.update(wall_s=round(time.time() - t0, 3), finish_reason=choice.get("finish_reason"),
               content=msg.get("content"), reasoning=msg.get("reasoning_content"),
               usage=resp.get("usage"), timings=resp.get("timings"))
    try:
        rec["calls"] = [{"name": c["function"]["name"], "args": json.loads(c["function"]["arguments"] or "{}")}
                        for c in msg.get("tool_calls") or []]
        rec["outcome"] = "ok"
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        rec.update(outcome="parse_error", error=str(e), raw_tool_calls=msg.get("tool_calls"))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(l)["id"] for l in a.out.open()} if a.out.exists() else set()
    tasks = [t for t in map(json.loads, a.tasks.open())][:a.limit]
    todo = [t for t in tasks if t["id"] not in done]
    print(f"{len(done)} done, {len(todo)} to run", flush=True)
    with a.out.open("a") as f:
        for i, t in enumerate(todo, 1):
            rec = run_one(a.url, t, a.max_tokens, a.timeout)
            f.write(json.dumps(rec) + "\n")
            f.flush()
            print(f"[{i}/{len(todo)}] {t['id']} {rec['outcome']} {rec['wall_s']}s "
                  f"calls={len(rec.get('calls') or [])}", flush=True)


if __name__ == "__main__":
    main()
