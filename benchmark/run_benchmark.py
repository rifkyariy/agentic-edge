#!/usr/bin/env python3
"""Benchmark harness. Device config + condition config + model key -> one run.

    python3 run_benchmark.py --device devices/pi5.json \
                            --condition conditions/E.json --model e4b

Config is two layers on purpose. devices/*.json holds everything specific to
one box (paths, endpoints, CUDA, power mode) and is written once when you set
that box up. conditions/*.json holds the experiment axes (engine, tools, MTP,
thinking) and is identical on every device. So a new device is one new file,
a new condition is one new file, and neither duplicates the other — running
the study elsewhere is `git pull` plus a device file.

Stdlib only. See EXPERIMENT_PLAN.md for which runs to do in what order, and
sweep.sh to run a whole tier at once.
"""
import argparse
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adapters

# An answer that declines, hedges or defers is not a fabrication — it is the
# correct behaviour for a model with no way to look something up. Only a
# confident, substantive answer to a live-data question with no tool call
# counts against it.
REFUSAL = re.compile(
    r"(?i)\bi (?:do not|don't|cannot|can't|am not able to)\b"
    r"|\bno (?:access|way) to\b|\bunable to\b|\bmy (?:knowledge|training)\b"
    r"|\bas of my\b|\bmay be out of date\b|\bcheck a (?:live|current)\b"
    r"|\bi have no\b|\brecommend checking\b|\bplease check\b")


def merge_config(device_path, condition_path, model_key, overrides):
    """Flatten the two layers into the single dict the adapters expect."""
    with open(device_path) as f:
        dev = json.load(f)
    with open(condition_path) as f:
        cond = json.load(f)

    engine = cond["engine"]
    models = dev.get("models") or {}
    if model_key not in models and engine != "little_gemma":
        sys.exit(f"device {dev['device']!r} has no model {model_key!r} — "
                 f"have: {', '.join(models) or '(none)'}")

    cfg = {
        "device": dev["device"],
        "hardware": dev.get("hardware"),
        "power_mode": dev.get("power_mode"),
        "cuda": bool(dev.get("cuda")),
        "engine": engine,
        "condition": cond["condition"],
        "label": cond.get("label", cond["condition"]),
        "offer_tools": bool(cond.get("offer_tools")),
        "mtp": bool(cond.get("mtp")),
        "thinking": bool(cond.get("thinking")),
        "model": models.get(model_key, {"name": model_key, "quant": "n/a"}),
        "model_key": model_key,
        "repeat": dev.get("repeat", 4),
        "timeout_s": dev.get("timeout_s", 240),
    }
    # little-gemma on a CUDA box is not the same condition as on a CPU box:
    # the project is C/CUDA by design, and conflating the two rows would hide
    # the single most interesting comparison in the study.
    if engine == "little_gemma":
        cfg["condition"] += "-cuda" if cfg["cuda"] else "-cpu"
        cfg["label"] += " [CUDA]" if cfg["cuda"] else " [CPU]"
        cfg["binary"] = (dev.get("binaries") or {}).get("little_gemma")
        cfg["binary_args"] = (dev.get("binary_args") or {}).get("little_gemma")
        cfg["log"] = (dev.get("logs") or {}).get("little_gemma")
        if not cfg["binary"]:
            sys.exit(f"device {dev['device']!r} has no binaries.little_gemma path")
    elif engine == "proposed":
        cfg["proposed_url"] = dev.get("proposed_url")
        if not cfg["proposed_url"]:
            sys.exit(f"device {dev['device']!r} has no proposed_url")
    else:
        cfg["endpoint"] = (dev.get("endpoints") or {}).get(engine)
        if engine == "litert_lm":
            # LiteRT-LM serves .litertlm bundles by id, not our GGUF paths.
            cfg["request_model"] = (dev.get("litert_models") or {}).get(model_key)
        if not cfg["endpoint"]:
            sys.exit(f"device {dev['device']!r} has no endpoints.{engine}")

    # The model key must change what is actually loaded, not just the label.
    # llama.cpp's /props says what it has; va-web can switch it (below).
    cfg["llama_props_url"] = ((dev.get("endpoints") or {}).get("llama_cpp") or
                              "").split("/v1/")[0] + "/props"
    cfg.setdefault("proposed_url", dev.get("proposed_url"))
    cfg["litert_models"] = dev.get("litert_models") or {}

    cfg.update(overrides)
    return cfg


def _get_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def loaded_model(cfg):
    """What the engine actually has loaded, or None if we can't tell."""
    if cfg["engine"] in ("llama_cpp", "proposed"):
        try:
            return _get_json(cfg["llama_props_url"]).get("model_path")
        except (urllib.error.URLError, OSError, ValueError):
            return None
    if cfg["engine"] == "little_gemma":
        out = subprocess.run(["pgrep", "-af", "[r]un -m "], capture_output=True, text=True)
        m = re.search(r" -m (\S+)", out.stdout)
        return m.group(1) if m else None
    return cfg.get("request_model")


def ensure_model(cfg):
    """Make llama.cpp serve cfg's model (via va-web's POST /model, which
    restarts va-llm), or exit. A row labelled E4B that ran E2B is worse than
    no row. For little-gemma and LiteRT-LM it only verifies."""
    want = cfg["model"].get("path")
    have = loaded_model(cfg)
    if cfg["engine"] == "litert_lm" or not want or have == want:
        return have
    if cfg["engine"] in ("llama_cpp", "proposed") and cfg.get("proposed_url"):
        print(f"switching llama.cpp model: {have} -> {want} (restarts va-llm)...")
        req = urllib.request.Request(
            cfg["proposed_url"].rstrip("/") + "/model",
            data=json.dumps({"path": want}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=15).read()
        except urllib.error.HTTPError as e:
            sys.exit(f"model switch refused: {e.read()[:200]}")
        deadline = time.time() + 300
        while time.time() < deadline:
            time.sleep(3)
            if loaded_model(cfg) == want:
                return want
        sys.exit(f"llama.cpp did not come up with {want} within 300s")
    sys.exit(f"{cfg['engine']} has {have!r} loaded, run wants {want!r} — "
             f"start it with the right model first")


def score(case, r):
    """Attach the three objective metrics. Deliberately no live ground truth:
    fabrication rate carries the factual-reliability argument without needing
    to know what the weather actually was at run time."""
    if case.get("expected_substring") is not None:
        r["correct"] = case["expected_substring"].lower() in (r.get("text") or "").lower()
    if case.get("expected_tool") is not None:
        r["tool_correct"] = r.get("tool_called") == case["expected_tool"]
        text = (r.get("text") or "").strip()
        r["fabricated"] = bool(
            not r.get("tool_called") and text and not REFUSAL.search(text))
    return r


def summarise(results):
    """Median, and cold separated from warm. A mean over repeats averages one
    cold turn (system-prompt prefill not yet cached, ~2.2x slower on this
    stack) with two warm ones and describes neither."""
    ok = [r for r in results if r.get("ok")]
    cold = [r for r in ok if r.get("repeat_n") == 0]
    warm = [r for r in ok if r.get("repeat_n", 0) > 0]

    def med(rows, field):
        vals = [r[field] for r in rows if r.get(field) is not None]
        return round(statistics.median(vals), 3) if vals else None

    def rng(rows, field):
        vals = [r[field] for r in rows if r.get(field) is not None]
        return [round(min(vals), 3), round(max(vals), 3)] if vals else None

    def frac(field):
        n = sum(1 for r in results if field in r)
        k = sum(1 for r in results if r.get(field))
        return {"n": n, "k": k, "pct": round(100 * k / n, 1)} if n else None

    return {
        "n": len(results), "n_ok": len(ok),
        "cold_total_s": med(cold, "total_s"),
        "warm_total_s": med(warm, "total_s"),
        "warm_total_range": rng(warm, "total_s"),
        "warm_ttft_s": med(warm, "ttft_s"),
        "warm_model_time_s": med(warm, "model_time_s"),
        "warm_tool_time_s": med(warm, "tool_time_s"),
        "warm_tokens_per_s": med(warm, "tokens_per_s"),
        "tool_selection": frac("tool_correct"),
        "fabrication": frac("fabricated"),
        "static_answers": frac("correct"),
    }


def gpu_info():
    """Best-effort CUDA telemetry: absent on the Pi, present on Jetson. Never
    fatal — a null field is itself part of the CUDA comparison."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,utilization.gpu",
             "--format=csv,noheader"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            name, mem, util = [x.strip() for x in out.stdout.splitlines()[0].split(",")]
            return {"name": name, "memory_used": mem, "utilization": util}
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def thermals():
    """Throttled runs are not comparable runs, so record the temperature."""
    for cmd, pat in ((["vcgencmd", "measure_temp"], r"([\d.]+)"),
                     (["cat", "/sys/class/thermal/thermal_zone0/temp"], r"(\d+)")):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            m = re.search(pat, out.stdout or "")
            if m:
                v = float(m.group(1))
                return round(v / 1000 if v > 200 else v, 1)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            continue
    return None


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", required=True, help="devices/<box>.json")
    ap.add_argument("--condition", required=True, help="conditions/<X>.json")
    ap.add_argument("--model", required=True, help="a key in the device's models{}")
    ap.add_argument("--cases", default=None, help="default: cases.json")
    ap.add_argument("--repeat", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    cfg = merge_config(args.device, args.condition, args.model,
                       {"repeat": args.repeat} if args.repeat else {})
    cases_path = args.cases or os.path.join(here, "cases.json")
    with open(cases_path) as f:
        cases = json.load(f)
    repeat = cfg["repeat"]

    run_fn = adapters.ENGINES.get(cfg["engine"])
    if not run_fn:
        sys.exit(f"unknown engine {cfg['engine']!r}")

    skipped = adapters.unsupported(cfg["engine"], cfg)
    if cfg["engine"] == "litert_lm" and not cfg.get("request_model"):
        skipped.append(("model", cfg["litert_models"].get("_note") or
                        f"no .litertlm bundle for {args.model} on this device"))
    if skipped:
        print(f"SKIPPED {cfg['condition']} on {cfg['device']}: "
              f"{cfg['engine']} cannot do " +
              ", ".join(f"{t} ({why})" for t, why in skipped))
        run = {"config": cfg, "skipped": [{"toggle": t, "reason": w}
                                          for t, w in skipped],
               "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "results": []}
    else:
        cfg["loaded_model"] = ensure_model(cfg)
        # va-web's /option also drives condition B's server, so its MTP and
        # thinking labels match how llama.cpp was actually launched.
        if cfg["engine"] in ("proposed", "llama_cpp") and cfg.get("proposed_url"):
            print(f"configuring: mtp={cfg['mtp']} thinking={cfg['thinking']} "
                  f"(restarts va-llm, waiting)...")
            adapters.configure_proposed(cfg)

        m = cfg["model"]
        print(f"{cfg['condition']}  {cfg['label']}\n"
              f"device={cfg['device']} cuda={cfg['cuda']} model={m.get('name')} "
              f"quant={m.get('quant')} tools={cfg['offer_tools']} "
              f"mtp={cfg['mtp']} thinking={cfg['thinking']}\n"
              f"{len(cases)} cases x{repeat} (repeat 0 = cold)\n")

        results = []
        for case in cases:
            for n in range(repeat):
                print(f"  {case['id']} ({n + 1}/{repeat})...", end=" ", flush=True)
                r = run_fn(cfg, case)
                r["case_id"], r["category"], r["repeat_n"] = (
                    case["id"], case.get("category"), n)
                score(case, r)
                results.append(r)
                flags = "".join(("T" if r.get("tool_correct") else "",
                                 "F" if r.get("fabricated") else "",
                                 "C" if r.get("correct") else ""))
                print(("ok" if r.get("ok") else f"FAILED: {r.get('error')}")
                      + f"  {r.get('total_s')}s {flags}")

        run = {"config": cfg, "host": platform.node(),
               "python": platform.python_version(), "gpu": gpu_info(),
               "temp_c": thermals(),
               "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "summary": summarise(results), "results": results}
        print("\nsummary:", json.dumps(run["summary"], indent=1))

    out_dir = os.path.join(here, "results")
    os.makedirs(out_dir, exist_ok=True)
    m = cfg["model"]
    tag = (f"{cfg['device']}-{cfg['condition']}-{m.get('name','model')}-"
           f"{m.get('quant','q')}")
    path = os.path.join(out_dir, args.out or
                        f"{time.strftime('%Y%m%d-%H%M%S')}-{tag}.json")
    with open(path, "w") as f:
        json.dump(run, f, indent=2)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
