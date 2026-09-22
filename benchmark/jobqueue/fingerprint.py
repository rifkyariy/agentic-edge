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


def capture(runner=None):
    run = runner or _run
    args = run(["ps", "-o", "args=", "-C", "llama-server"])
    props = run(["curl", "-s", "-m", "3", "http://127.0.0.1:8080/props"])
    try:
        model = json.loads(props).get("model_path", "")
    except (ValueError, AttributeError):
        model = ""
    return {
        "server_args": args,
        "model_path": model,
        "governor": run(["cat", "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"]),
        "kernel": run(["uname", "-sr"]),
        "flags": parse_flags(args),
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
