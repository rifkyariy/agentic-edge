#!/usr/bin/env python3
"""Self-check for codemode.py. The execution checks need Deno (DENO=<path>, default
~/build/deno-2.9.8/deno) and are skipped without it. Run: python3 test_codemode.py"""
import os
from codemode import DENO, execute, ts_api

TOOLS = [{"type": "function", "function": {
    "name": "get_user_info", "description": "Retrieve details for a user.",
    "parameters": {"type": "object", "required": ["user_id"], "properties": {
        "user_id": {"type": "integer", "description": "The user's ID."},
        "special": {"type": "string", "description": "Special info.", "default": "none"},
        "mode": {"type": "string", "enum": ["a", "b"]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "filter": {"type": "object", "properties": {"min": {"type": "number"}}, "required": ["min"]}}}}}]

api = ts_api(TOOLS)
for part in ["/** Retrieve details for a user. */", "get_user_info(args: {", "user_id: number;",
             '/** Special info. (default: "none") */', "special?: string;", 'mode?: "a" | "b";',
             "tags?: string[];", "filter?: {", "min: number;", "}): Promise<unknown>;"]:
    assert part in api, (part, api)

if not os.path.exists(DENO):
    print("ts_api checks passed; no Deno at", DENO, "- execution checks skipped")
    raise SystemExit

r = execute(TOOLS, 'await tools.get_user_info({ user_id: 7890, special: "black" });')
assert r["outcome"] == "ok" and r["calls"] == [{"name": "get_user_info", "args": {"user_id": 7890, "special": "black"}}], r
assert r["maxrss_kb"] > 0
# un-awaited async work still lands before the calls are printed
r = execute(TOOLS, "async function main() { await tools.get_user_info({ user_id: 1 }); await tools.get_user_info({ user_id: 2 }); }\nmain();")
assert [c["args"]["user_id"] for c in r["calls"]] == [1, 2], r
# the model's own printing does not confuse the call record
assert execute(TOOLS, 'console.log("hi"); await tools.get_user_info({ user_id: 3 });')["calls"][0]["args"] == {"user_id": 3}
# positional arguments are recorded, and cannot match a schema
assert execute(TOOLS, "await tools.get_user_info(5);")["calls"] == [{"name": "get_user_info", "args": {"__positional": [5]}}]
# failures score zero calls, even if some calls ran first
assert execute(TOOLS, "let x = ;")["outcome"] == "syntax_error"
r = execute(TOOLS, 'await tools.get_user_info({ user_id: 1 }); throw new Error("boom");')
assert r["outcome"] == "runtime_error" and r["calls"] == [], r
assert execute(TOOLS, "await tools.no_such_tool({});")["outcome"] == "runtime_error"
# the sandbox has no file, network or environment access
assert execute(TOOLS, 'await Deno.readTextFile("/etc/hostname");')["outcome"] == "runtime_error"
assert execute(TOOLS, 'await fetch("http://example.com");')["outcome"] == "runtime_error"
assert execute(TOOLS, "while (true) {}", timeout=2)["outcome"] == "timeout"
print("codemode.py self-check: all passed")
