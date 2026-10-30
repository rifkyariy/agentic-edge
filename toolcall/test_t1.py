#!/usr/bin/env python3
"""Self-check for build_t1.py and run.py's JSON chain loop, against a fake
llama-server. Run: python3 test_t1.py"""
import json, threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import run
from build_t1 import CHAINS, build, pilot
from score import score_task

tasks = build(0)
assert tasks == build(0), "not deterministic"
chains = [t for t in tasks if t["category"] == "chain"]
fans = [t for t in tasks if t["category"] == "fanout"]
# the paper's counts: 52 chains, 17 of length >= 6 and 10 of length >= 13; 32 fan-outs over its 8 sizes
assert len(chains) == 52 and sum(t["n"] >= 6 for t in chains) == 17 and sum(t["n"] >= 13 for t in chains) == 10
assert min(t["n"] for t in chains) == 2 and max(t["n"] for t in chains) == 20
assert Counter(t["n"] for t in fans) == {n: 4 for n in (7, 9, 11, 13, 15, 20, 30, 48)}
assert len({t["id"] for t in tasks}) == len(tasks)
pl = pilot(tasks)
assert sorted({t["n"] for t in pl if t["category"] == "fanout"}) == [7, 9, 11, 13, 15, 20, 30, 48]
assert len({t["tools"][0]["function"]["name"] for t in pl if t["category"] == "fanout"}) == 4
assert {t["n"] for t in pl if t["category"] == "chain"} >= {2, 20} and len(pl) == 19
for t in tasks:
    assert len(t["ground_truth"]) == t["n"]
    perfect = [{"name": n, "args": {k: v[0] for k, v in spec.items()}} for gt in t["ground_truth"] for n, spec in gt.items()]
    assert score_task(t, perfect) == {"pass": True, "strict": True, "enum": True}, t["id"]
    assert not score_task(t, perfect[:-1])["pass"]
for t in chains:  # each step's value is the previous step's value after its change, and stays positive
    state = CHAINS[next(d for d in CHAINS if t["tools"][0]["function"]["name"] in [o[0] for o in CHAINS[d][4]])]
    ops = {o[0]: o[5] for o in state[4]}
    steps = [(n, list(spec.values())) for gt in t["ground_truth"] for n, spec in gt.items()]
    for (n, [[x], [a]]), (_, [[y], _]) in zip(steps, steps[1:]):
        assert y == {"+": x + a, "-": x - a, "*": x * a}[ops[n]] > 0, (t["id"], steps)

# --- the chain loop against a fake server that makes one correct call per turn
seen = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen.append(body)
        done = sum(m["role"] == "tool" for m in body["messages"])
        script = Fake.script
        msg = {"role": "assistant", "content": None}
        if done < len(script):
            n, args = script[done]
            msg["tool_calls"] = [{"id": f"call_{done}", "type": "function",
                                  "function": {"name": n, "arguments": json.dumps(args)}}]
        out = json.dumps({"choices": [{"message": msg, "finish_reason": "tool_calls" if "tool_calls" in msg else "stop"}],
                          "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
                          "timings": {"prompt_n": 100}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}"

t = next(t for t in chains if t["n"] == 5)
Fake.script = [(n, {k: v[0] for k, v in spec.items()}) for gt in t["ground_truth"] for n, spec in gt.items()]
r = run.run_one(url, t, "json", 512, 30)
assert r["outcome"] == "ok" and len(seen) == 6 and len(r["turns"]) == 6 and "turn_cap" not in r, r
assert score_task(t, r["calls"])["pass"]
assert r["usage"] == {"prompt_tokens": 600, "completion_tokens": 60, "total_tokens": 660}
assert [b["cache_prompt"] for b in seen] == [False] + [True] * 5  # reuse only within the task (D8)
last = seen[-1]["messages"]  # user, then (assistant call, echoed tool result) per step
assert [m["role"] for m in last] == ["user"] + ["assistant", "tool"] * 5
assert last[2] == {"role": "tool", "tool_call_id": "call_0", "content": json.dumps(Fake.script[0][1])}

# single-turn tasks and Code Mode never loop, even when the model keeps calling
seen.clear()
r = run.run_one(url, {**t, "multi_turn": False}, "json", 512, 30)
assert len(seen) == 1 and len(r["calls"]) == 1 and "turns" not in r, r

# a model that never stops hits the cap and says so
seen.clear()
run.MAX_TURNS = 3
r = run.run_one(url, t, "json", 512, 30)
assert len(seen) == 3 and r["turn_cap"] is True and len(r["calls"]) == 3, r
srv.shutdown()
print("build_t1.py and run.py chain loop self-check: all passed")
