"""What the server is actually serving, against what it was supposed to.

The Pi reaches llama-server through va-llm and runtime.env; the Jetson launches
it directly. Comparing the *inputs* on each board compares two incomparable
things. The resolved command line is the only common ground — which is what
AGENTS §10 says to diff, and what nothing was doing automatically.
"""
import json
import os
import subprocess

from . import paths as _paths

# Flag name -> the keys that introduce it. -rea is the short form of
# --reasoning. --reasoning-format is a DIFFERENT flag; keeping them apart is
# the whole reason this module exists.
_FLAGS = {
    "ctx": ("-c", "--ctx-size"),
    "cache_ram": ("--cache-ram",),
    "reasoning": ("-rea", "--reasoning"),
    "reasoning_budget": ("--reasoning-budget",),
    "reasoning_format": ("--reasoning-format",),
    "ngl": ("-ngl", "--n-gpu-layers"),
    "model": ("-m", "--model"),
}
_LOOKUP = {flag: key for key, flags in _FLAGS.items() for flag in flags}

# little-gemma (S3) has no server binary of its own to read: lg_openai_shim.py
# launches the engine, and the served config is split across the two command
# lines. The engine carries the model and the reasoning budget; the shim
# carries --thinking, the <|think|> switch that stands in for -rea.
ENGINE = "run-cuda-i8"


def _is_number(tok):
    try:
        float(tok)
        return True
    except ValueError:
        return False


def parse_flags(argv_line):
    out = {key: None for key in _FLAGS}
    tokens = (argv_line or "").split()
    for i, token in enumerate(tokens):
        key = _LOOKUP.get(token)
        if key is None:
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is None:
            continue
        # -rea takes an optional value, so a following flag means it was
        # omitted. A negative number (--reasoning-budget -1) is a value, not a
        # flag, so it is checked before the leading-dash rule rejects it.
        if _is_number(nxt) or not nxt.startswith("-"):
            out[key] = nxt
    return out


def _run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_lg(engine_line, shim_line):
    """The little-gemma counterpart of parse_flags. -raw is a bare switch, so it
    reads as "on" when present rather than taking the next token."""
    eng = (engine_line or "").split()
    shim = (shim_line or "").split()

    def value(tokens, flag):
        if flag in tokens:
            i = tokens.index(flag)
            if i + 1 < len(tokens):
                return tokens[i + 1]
        return None

    return {
        "engine": "little-gemma",
        "model": value(eng, "-m"),
        "raw": "on" if "-raw" in eng else None,
        "think": value(eng, "-think"),
        "thinking": value(shim, "--thinking"),
    }


def server_pids(runner=None):
    """Pids of every running llama-server or little-gemma engine. Only
    whole-number lines count, so a runner that answers some other ps question
    cannot pass for a pid list."""
    out = (runner or _run)(["ps", "-o", "pid=", "-C", "llama-server," + ENGINE])
    return sorted(int(line) for line in (out or "").split("\n")
                  if line.strip().isdigit())


def capture(runner=None):
    run = runner or _run
    args = run(["ps", "-o", "args=", "-C", "llama-server"])
    flags = parse_flags(args)
    if not args:
        engine = run(["ps", "-o", "args=", "-C", ENGINE]).split("\n")[0]
        if ENGINE in engine:
            shim = run(["pgrep", "-af", "^python3 .*[l]g_openai_shim[.]py"]).split("\n")[0]
            args = engine + " | " + shim.split(" ", 1)[-1]
            flags = parse_lg(engine, shim)
    props = run(["curl", "-s", "-m", "3", "http://127.0.0.1:8080/props"])
    try:
        model = json.loads(props).get("model_path", "")
    except (ValueError, AttributeError):
        model = ""
    return {
        "server_args": args,
        "pids": server_pids(run),
        "model_path": model,
        "governor": run(["cat", "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"]),
        "kernel": run(["uname", "-sr"]),
        "flags": flags,
    }


def load_baselines(path=None):
    path = path or os.path.join(_paths.bench_dir(), "baselines.json")
    with open(path) as f:
        return json.load(f)


def diff(flags, expected):
    rows = []
    for key in sorted(expected):
        want = expected[key]
        got = flags.get(key)
        rows.append({"key": key, "expected": want, "actual": got,
                     "ok": got is not None and str(got) == str(want)})
    return rows


def agrees(rows):
    return all(r["ok"] for r in rows)
