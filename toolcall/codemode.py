"""Code Mode (plan §6.2): the task's tools as a typed TypeScript API behind one
execute_typescript tool, as Cloudflare's Code Mode does. The model's script
runs in Deno with no permissions; echo stubs record each call.

T0–T2 stubs echo their arguments (the paper's design), so the API declares
no return types beyond Promise<unknown>.
"""
import json, os, signal, subprocess, tempfile, time
from pathlib import Path

DENO = os.environ.get("DENO", str(Path.home() / "build/deno-2.9.8/deno"))
MARK = "@@CALLS@@"
CODE_TOOL = "execute_typescript"


def ts_type(s, indent="  "):
    if "enum" in s:
        return " | ".join(json.dumps(v) for v in s["enum"])
    t = s.get("type")
    if t == "string":
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "array":
        inner = ts_type(s["items"], indent) if isinstance(s.get("items"), dict) else "unknown"
        return f"({inner})[]" if "|" in inner else f"{inner}[]"
    if t == "object" and s.get("properties"):
        return ts_object(s, indent)
    if t == "object":
        return "Record<string, unknown>"
    return "unknown"


def doc(s, indent):
    text = s.get("description", "").strip()
    if "default" in s:
        text += f" (default: {json.dumps(s['default'])})"
    return f"{indent}/** {text.strip()} */\n" if text.strip() else ""


def ts_object(s, indent):
    req, inner = set(s.get("required", [])), indent + "  "
    lines = [doc(p, inner) + f"{inner}{k}{'' if k in req else '?'}: {ts_type(p, inner)};"
             for k, p in s["properties"].items()]
    return "{\n" + "\n".join(lines) + f"\n{indent}}}"


def ts_api(tools):
    fns = [doc(t["function"], "  ") + f"  {t['function']['name']}(args: {ts_type(t['function']['parameters'], '  ')}): Promise<unknown>;"
           for t in tools]
    return "declare const tools: {\n" + "\n".join(fns) + "\n};"


def code_tool(tools):
    return {"type": "function", "function": {
        "name": CODE_TOOL,
        "description": ("Run TypeScript code. The code can call the functions declared below on the global "
                        "`tools` object; each call performs that tool call and returns a Promise. Write one "
                        "complete script that makes every tool call the user's request needs, with the values "
                        "from the request. Do not declare `tools` or its functions yourself.\n\n```ts\n"
                        + ts_api(tools) + "\n```"),
        "parameters": {"type": "object", "required": ["code"],
                       "properties": {"code": {"type": "string", "description": "TypeScript source to run."}}}}}


def prelude(tools, lenient=False):
    names = json.dumps([t["function"]["name"] for t in tools])
    # lenient: bare `fn(...)` works too, as the paper's Python stubs were plain functions
    exposed = "Object.assign(globalThis, tools);\n" if lenient else ""
    # an object-literal argument is recorded as the call's arguments; anything else cannot match a schema
    return (f"const __calls: unknown[] = [];\n"
            f"const tools: any = Object.fromEntries({names}.map((name) => [name, (...a: any[]) => {{\n"
            f"  const args = a.length === 1 && a[0] && typeof a[0] === 'object' && !Array.isArray(a[0]) ? a[0] : {{ __positional: a }};\n"
            f"  __calls.push({{ name, args }});\n"
            f"  return Promise.resolve(args);\n"
            f"}}]));\n"
            + exposed +
            # unload fires once the event loop is empty, so un-awaited async work is recorded too
            f"globalThis.addEventListener('unload', () => console.log('\\n{MARK}' + JSON.stringify(__calls)));\n")


def execute(tools, code, timeout=10.0, lenient=False):
    """Run one script. Returns outcome (ok | syntax_error | runtime_error | timeout), calls, sandbox peak RSS.
    lenient also exposes the tools as globals and wraps the script in an async function, so a
    top-level `return` is legal; the model's prompt is the same either way."""
    if lenient:
        code = f"await (async () => {{\n{code}\n}})();"
    with tempfile.TemporaryDirectory() as d:
        Path(d, "main.ts").write_text(prelude(tools, lenient) + code + "\n")
        out, err = Path(d, "out"), Path(d, "err")
        t0 = time.time()
        with out.open("w") as o, err.open("w") as e:
            p = subprocess.Popen([DENO, "run", "--no-prompt", "--no-remote", "--no-npm", "--no-config", "--no-lock",
                                  "--v8-flags=--max-old-space-size=256", "main.ts"],
                                 cwd=d, stdout=o, stderr=e, stdin=subprocess.DEVNULL,
                                 env={"NO_COLOR": "1", "PATH": "/usr/bin:/bin"}, start_new_session=True)
            timed_out = False
            while (r := os.wait4(p.pid, os.WNOHANG))[0] == 0:
                if time.time() - t0 > timeout:
                    os.killpg(p.pid, signal.SIGKILL)
                    r, timed_out = os.wait4(p.pid, 0), True
                    break
                time.sleep(0.01)
            p.returncode = r[1]  # reaped by wait4, so Popen must not wait again
        stdout, stderr = out.read_text(errors="replace"), err.read_text(errors="replace")
    res = {"wall_s": round(time.time() - t0, 3), "maxrss_kb": r[2].ru_maxrss,
           "stderr": stderr[-2000:], "stdout": stdout[-2000:]}
    if timed_out:
        return {**res, "outcome": "timeout", "calls": []}
    if r[1] != 0 or MARK not in stdout:
        kind = "syntax_error" if "SyntaxError" in stderr.split("\n", 1)[0] else "runtime_error"
        return {**res, "outcome": kind, "calls": []}  # an error scores zero calls (plan §5.3)
    return {**res, "outcome": "ok", "calls": json.loads(stdout.rsplit(MARK, 1)[1].strip())}
