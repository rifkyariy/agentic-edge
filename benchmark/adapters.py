"""Engine adapters for the benchmark harness.

Each adapter takes (config: dict, case: dict) and returns a common result
dict:

    ok, error, text, ttft_s, total_s,
    prompt_tokens, completion_tokens, tokens_per_s,
    thinking_chars, tool_called

Four completely different interfaces hide behind that one shape — an
OpenAI-compatible HTTP server, a bare CLI binary, and this project's own
modular pipeline over Unix-socket-backed services — so this file is the only
place that has to know the difference. Stdlib only: no pip install needed to
clone this repo and run it on a fresh device.
"""
import json
import os
import queue
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request


def _now():
    return time.time()


# ---------------------------------------------------------------- llama.cpp / LiteRT-LM
_SCHEMAS = None


def tool_schemas():
    """The same six schemas va-tools offers, dumped to a file so condition D
    can offer them on a device where va-tools is not running at all."""
    global _SCHEMAS
    if _SCHEMAS is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "tool_schemas.json")
        with open(path) as f:
            _SCHEMAS = json.load(f)
    return _SCHEMAS


def run_openai_compat(cfg, case):
    """llama.cpp and LiteRT-LM both speak /v1/chat/completions.

    cfg["offer_tools"] is the B-vs-D switch: false sends a bare messages
    array (no tool access at all), true offers the full schema set with
    tool_choice "auto" and lets the model decide alone — naive function
    calling, the thing condition E has to beat.

    MTP and thinking are server-LAUNCH flags for these two engines
    (`--spec-type draft-mtp`, `-rea on`), not per-request fields, so
    cfg["mtp"]/cfg["thinking"] are labels here. Launch the server with
    serve_llama_cpp.sh, which reads the same config, rather than by hand —
    a mismatch silently mislabels the row.
    """
    body = {
        "model": cfg.get("model", {}).get("name", "local"),
        "messages": [{"role": "user", "content": case["prompt"]}],
        "stream": True,
        "temperature": 0,
        "max_tokens": cfg.get("max_tokens", 500),
    }
    if cfg.get("offer_tools"):
        body["tools"] = tool_schemas()
        body["tool_choice"] = "auto"
    data = json.dumps(body).encode()
    req = urllib.request.Request(cfg["endpoint"], data=data,
                                  headers={"Content-Type": "application/json"})
    t0 = _now()
    first = None
    text, usage, think_chars = "", {}, 0
    tool_called = None
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout_s", 180)) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                chunk = json.loads(payload)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                if delta.get("reasoning_content"):
                    think_chars += len(delta["reasoning_content"])
                if delta.get("content"):
                    if first is None:
                        first = _now() - t0
                    text += delta["content"]
                for tc in delta.get("tool_calls") or []:
                    fn = (tc.get("function") or {}).get("name")
                    if fn:
                        tool_called = fn
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return {"ok": False, "error": str(e), "total_s": _now() - t0}
    total = _now() - t0
    comp = usage.get("completion_tokens")
    return {
        "ok": True, "text": text.strip(), "ttft_s": first, "total_s": total,
        "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": comp,
        "tokens_per_s": round(comp / total, 2) if comp and total else None,
        "thinking_chars": think_chars or None, "tool_called": tool_called,
        "error": None,
    }


# ---------------------------------------------------------------- little-gemma
_LG_TIMING = re.compile(
    r"(prompt|gen):\s*(\d+)\s*tokens?\s*in\s*([\d.]+)s\s*\(([\d.]+)\s*tok/s\)")


def run_little_gemma(cfg, case):
    """little-gemma is a bare CLI: `lg "<prompt>"`, printing the answer plus
    timing lines. No server, no tool calling, no thinking flag — the plainest
    possible adapter, and the baseline everything else is measured against."""
    t0 = _now()
    argv = [cfg["binary"]] + list(cfg.get("binary_args") or []) + [case["prompt"]]
    try:
        r = subprocess.run(argv, capture_output=True,
                           text=True, timeout=cfg.get("timeout_s", 180))
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": str(e), "total_s": _now() - t0}
    total = _now() - t0
    combined = r.stdout + "\n" + r.stderr
    timings = {m.group(1): (int(m.group(2)), float(m.group(3)), float(m.group(4)))
               for m in _LG_TIMING.finditer(combined)}
    gen, prompt_t = timings.get("gen"), timings.get("prompt")
    text = "\n".join(l for l in r.stdout.splitlines()
                     if not _LG_TIMING.search(l)).strip()
    return {
        "ok": r.returncode == 0, "text": text, "total_s": total,
        "ttft_s": prompt_t[1] if prompt_t else None,
        "prompt_tokens": prompt_t[0] if prompt_t else None,
        "completion_tokens": gen[0] if gen else None,
        "tokens_per_s": gen[2] if gen else None,
        "thinking_chars": None, "tool_called": None,
        "error": None if r.returncode == 0 else (r.stderr[:300] or "nonzero exit"),
    }


# ---------------------------------------------------------------- our proposed architecture
def configure_proposed(cfg):
    """Push cfg["mtp"]/cfg["thinking"] to the running voice-agent via
    POST /option (each restarts va-llm) and wait for it to come back, so a
    config change is genuinely "no setup" — no SSH, no manual toggle in the
    web UI. Raises RuntimeError if the option or the restart fails."""
    base = cfg["proposed_url"].rstrip("/")
    for key in ("mtp", "thinking"):
        if key not in cfg:
            continue
        value = "on" if cfg[key] else "off"
        body = json.dumps({"key": "reasoning" if key == "thinking" else key,
                           "value": value}).encode()
        req = urllib.request.Request(base + "/option", data=body,
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read())
        if not res.get("ok"):
            raise RuntimeError(f"/option {key}={value} failed: {res.get('message')}")
    deadline = _now() + 120
    while _now() < deadline:
        try:
            with urllib.request.urlopen(base + "/status", timeout=5) as r:
                status = json.loads(r.read())
        except (urllib.error.URLError, OSError):
            status = {}
        if status.get("va-llm") == "active":
            return
        time.sleep(2)
    raise RuntimeError("va-llm did not come back within 120s of the option change")


def run_proposed(cfg, case):
    """The full modular pipeline: intent classification, tool calling,
    thinking, MTP — everything this repo's own voice-agent does, exercised
    exactly as a real user would (POST /say, read the SSE event stream).
    This is the one adapter that answers "does the extra architecture around
    the raw model actually help" rather than just "how fast is the model"."""
    base = cfg["proposed_url"].rstrip("/")
    q, stop = queue.Queue(), threading.Event()

    def reader():
        try:
            with urllib.request.urlopen(base + "/events",
                                        timeout=cfg.get("timeout_s", 180)) as r:
                for raw in r:
                    if stop.is_set():
                        return
                    line = raw.decode("utf-8", "replace").strip()
                    if line.startswith("data: "):
                        q.put(line[6:])
        except (urllib.error.URLError, OSError):
            pass

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    time.sleep(0.3)  # let the SSE connection attach before the turn is sent

    t0 = _now()
    body = json.dumps({"text": case["prompt"]}).encode()
    req = urllib.request.Request(base + "/say", data=body,
                                  headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except (urllib.error.URLError, OSError) as e:
        stop.set()
        return {"ok": False, "error": str(e), "total_s": _now() - t0}

    first_clause, intent, category, tools_used, done = None, None, None, [], None
    tool_time = 0.0
    deadline = t0 + cfg.get("timeout_s", 180)
    while True:
        remaining = deadline - _now()
        if remaining <= 0:
            break
        try:
            raw = q.get(timeout=remaining)
        except queue.Empty:
            break
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        t = ev.get("type")
        if t == "intent":
            intent, category = ev.get("intent"), ev.get("category")
        elif t == "tool_call":
            tools_used.append(ev.get("name"))
        elif t == "tool_result":
            # Sofascore/Open-Meteo round-trip time. Not the architecture's
            # cost and it varies with the internet, so it is recorded
            # separately and subtracted to get model_time.
            tool_time += ev.get("took") or 0.0
        elif t == "clause" and first_clause is None:
            first_clause = ev.get("at")
        elif t in ("done", "empty"):
            done = ev
            break
    stop.set()
    total = _now() - t0
    if done is None:
        return {"ok": False, "error": "timed out waiting for done/empty",
                "total_s": total, "intent": intent, "category": category,
                "tool_called": tools_used[0] if tools_used else None,
                "tools_all": tools_used, "tool_time_s": round(tool_time, 3)}
    ok = bool(done.get("reply"))
    total_s = done.get("total", total)
    return {
        "ok": ok, "text": done.get("reply", ""), "ttft_s": first_clause,
        "total_s": total_s,
        "tool_time_s": round(tool_time, 3),
        "model_time_s": round(total_s - tool_time, 3) if total_s else None,
        "prompt_tokens": None, "completion_tokens": None, "tokens_per_s": None,
        "thinking_chars": done.get("think_chars"),
        "tool_called": tools_used[0] if tools_used else None,
        "tools_all": tools_used, "intent": intent, "category": category,
        "finish": done.get("finish"),
        "error": None if ok else (done.get("reason") or "empty reply"),
    }


ENGINES = {
    "llama_cpp": run_openai_compat,
    "litert_lm": run_openai_compat,
    "little_gemma": run_little_gemma,
    "proposed": run_proposed,
}

# What each engine can actually do. An unsupported toggle is not a failure to
# hide — it is an "n/a" cell that needs a reason attached, so the writeup can
# say why rather than showing a mysteriously missing row.
CAPABILITIES = {
    "llama_cpp": {
        "offer_tools": True, "mtp": True, "thinking": True,
        "live_toggle": False,
    },
    "litert_lm": {
        "offer_tools": True, "mtp": None, "thinking": True,
        "live_toggle": False,
        "unknown": {"mtp": "LiteRT-LM speculative-decoding support on this "
                           "board is unverified — confirm before claiming a "
                           "number either way"},
    },
    "little_gemma": {
        "offer_tools": False, "mtp": False, "thinking": False,
        "live_toggle": False,
        "why": {"offer_tools": "CLI inference binary, no function-calling "
                               "interface at all",
                "mtp": "no speculative-decoding flag",
                "thinking": "no reasoning-channel flag"},
    },
    "proposed": {
        "offer_tools": True, "mtp": True, "thinking": True,
        "live_toggle": True,
    },
}


def unsupported(engine, cfg):
    """[(toggle, reason)] for every requested toggle this engine cannot do."""
    caps = CAPABILITIES.get(engine, {})
    out = []
    for toggle in ("offer_tools", "mtp", "thinking"):
        if not cfg.get(toggle):
            continue
        supported = caps.get(toggle)
        if supported is False:
            out.append((toggle, (caps.get("why") or {}).get(
                toggle, f"{engine} does not support {toggle}")))
        elif supported is None:
            out.append((toggle, (caps.get("unknown") or {}).get(
                toggle, f"{engine} {toggle} support unverified")))
    return out
