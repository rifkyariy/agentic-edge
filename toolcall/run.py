#!/usr/bin/env python3
"""Run tasks against a running llama-server, by JSON tool calling (plan §6.1)
or Code Mode (§6.2). Stdlib only.

One model call per task: T0's BFCL categories and T1's fan-out are single-turn,
parallel JSON calls arrive together in one response, and Code Mode writes one
script (D3a). Tasks marked multi_turn (T1's chains) run the JSON loop instead:
model call -> echoed arguments as the tool result -> next model call, until the
model stops calling tools (the paper's chaining design, §3.4).
Resumable: tasks already in the results file are skipped.

    python3 run.py tasks/t0.jsonl runs/<name>/results.jsonl [--interface json|code|code-lenient] [--url ...] [--limit N]
"""
import argparse, json, time, urllib.error, urllib.request
from pathlib import Path

import codemode

MAX_TURNS = 25  # longest T1 chain is 20 calls; the paper states no cap


def ask(url, messages, tools, max_tokens, timeout, cache=False):
    body = {"messages": messages, "tools": tools, "tool_choice": "auto",
            "parallel_tool_calls": True, "temperature": 0, "top_k": 1, "seed": 42,
            "max_tokens": max_tokens, "cache_prompt": cache}  # reuse only within a task (plan §8.3, D8)
    req = urllib.request.Request(url + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def run_code(task, tool_calls, lenient=False):
    """Execute each execute_typescript call; any failure scores zero calls."""
    scripts = [c for c in tool_calls if c["name"] == codemode.CODE_TOOL]
    if not scripts:
        return {"outcome": "no_script", "calls": []}
    runs = []
    for s in scripts:
        if not isinstance(s["args"].get("code"), str):
            return {"outcome": "bad_tool_args", "calls": [], "runs": runs}
        runs.append(codemode.execute(task["tools"], s["args"]["code"], lenient=lenient))
    bad = next((r["outcome"] for r in runs if r["outcome"] != "ok"), None)
    return {"outcome": bad or "ok", "calls": [] if bad else [c for r in runs for c in r["calls"]],
            "runs": [{**r, "code": s["args"]["code"]} for r, s in zip(runs, scripts)]}


def add_usage(a, b):
    return {k: a.get(k, 0) + v for k, v in b.items() if isinstance(v, int)} if a else b


def run_one(url, task, interface, max_tokens, timeout):
    """timeout covers the whole task, every turn of a JSON chain included (D7)."""
    t0 = time.time()
    rec = {"id": task["id"]}
    tools = task["tools"] if interface == "json" else [codemode.code_tool(task["tools"])]  # same prompt for both code modes
    loop = interface == "json" and task.get("multi_turn")
    messages, calls, turns = list(task["messages"]), [], []
    for turn in range(MAX_TURNS if loop else 1):
        sent = time.time()
        left = timeout - (sent - t0)
        try:
            if left <= 0:
                raise TimeoutError
            resp = ask(url, messages, tools, max_tokens, left, cache=turn > 0)
        except TimeoutError:
            return {**rec, "outcome": "timeout", "wall_s": round(time.time() - t0, 3), "turns": turns}
        except (urllib.error.URLError, OSError) as e:
            return {**rec, "outcome": "http_error", "error": str(e), "wall_s": round(time.time() - t0, 3)}
        choice = resp["choices"][0]
        msg = choice["message"]
        rec.update(wall_s=round(time.time() - t0, 3), finish_reason=choice.get("finish_reason"),
                   content=msg.get("content"), reasoning=msg.get("reasoning_content"),
                   usage=add_usage(rec.get("usage"), resp.get("usage") or {}), timings=resp.get("timings"))
        try:
            new = [{"name": c["function"]["name"], "args": json.loads(c["function"]["arguments"] or "{}")}
                   for c in msg.get("tool_calls") or []]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            rec.update(outcome="parse_error", error=str(e), raw_tool_calls=msg.get("tool_calls"), calls=calls)
            return rec
        calls += new
        if loop:  # per turn: what the model said and how long it took; the top level keeps the last turn
            turns.append({"start_epoch": round(sent, 3), "finish_reason": choice.get("finish_reason"), "content": msg.get("content"),
                          "n_calls": len(new), "usage": resp.get("usage"), "timings": resp.get("timings")})
        if not new or not loop:
            break
        # the stubs echo their arguments as a structured dict (paper §3.2)
        messages += [{"role": "assistant", "content": msg.get("content") or "", "tool_calls": msg["tool_calls"]}] + \
                    [{"role": "tool", "tool_call_id": c.get("id", ""), "content": json.dumps(n["args"])}
                     for c, n in zip(msg["tool_calls"], new)]
    else:
        rec["turn_cap"] = True  # still calling tools after MAX_TURNS
    rec.update(calls=calls, outcome="ok")
    if loop:
        rec["turns"] = turns
    if interface != "json":
        rec["code"] = run_code(task, rec["calls"], lenient=interface == "code-lenient")
        rec["calls"] = rec["code"].pop("calls")  # the stubs' record is what gets scored (plan §5.3)
        rec["wall_s"] = round(time.time() - t0, 3)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--interface", choices=["json", "code", "code-lenient"], default="json")
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--max-tokens", type=int, default=4096)  # a 48-call JSON fan-out is ~1.7K tokens
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(l)["id"] for l in a.out.open()} if a.out.exists() else set()
    tasks = [t for t in map(json.loads, a.tasks.open())][:a.limit]
    todo = [t for t in tasks if t["id"] not in done]
    print(f"{len(done)} done, {len(todo)} to run", flush=True)
    with a.out.open("a") as f:
        for i, t in enumerate(todo, 1):
            start = time.time()
            rec = run_one(a.url, t, a.interface, a.max_tokens, a.timeout)
            # epochs let energy.py integrate board power per task
            rec.update(start_epoch=round(start, 3), end_epoch=round(time.time(), 3))
            f.write(json.dumps(rec) + "\n")
            f.flush()
            extra = f" code={rec['code']['outcome']}" if "code" in rec else ""
            print(f"[{i}/{len(todo)}] {t['id']} {rec['outcome']} {rec['wall_s']}s "
                  f"calls={len(rec.get('calls') or [])}{extra}", flush=True)


if __name__ == "__main__":
    main()
