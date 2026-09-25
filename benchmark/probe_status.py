#!/usr/bin/env python3
"""One-shot JSON status of a benchmark box, for the live dashboard.

    python3 probe_status.py

Works on both boards: power comes from the Pi's PMIC (`vcgencmd pmic_read_adc`)
or the Jetson's INA3221 hwmon rails, whichever exists. Stdlib only, ~0.3s per
call, safe to poll every few seconds while a benchmark runs.
"""
import glob
import json
import os
import re
import subprocess
import time

HOME = os.path.expanduser("~")
# The Pi keeps results in ~/Research, the Jetson in ~/research (SSD symlink).
ROOT = next((p for p in (f"{HOME}/Research", f"{HOME}/research") if os.path.isdir(p)), HOME)
_ADC = re.compile(r"(\w+)_([AV])\s+\w+\(\d+\)=([\d.]+)")
# tqdm: "Requesting API:  20%|██ | 20/100 [40:17<3:10:07, 142.59s/it]"
_TQDM = re.compile(r"(\d+)%\|[^|]*\|\s*(\d+)/(\d+)\s*\[([\d:]+)<([\d:?]+),\s*([\d.]+)s?/it")
_CMAKE = re.compile(r"\[\s*(\d+)%\]")


def sh(*cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def cpu_pct(interval=0.25):
    def snap():
        line = read("/proc/stat", "").split("\n")[0].split()[1:]
        v = [int(x) for x in line]
        return sum(v), v[3] + v[4]
    t0, i0 = snap()
    time.sleep(interval)
    t1, i1 = snap()
    dt, di = t1 - t0, i1 - i0
    return round(100 * (dt - di) / dt, 1) if dt else 0.0


def power():
    """(watts, per-rail dict, source). Pi: PMIC. Jetson: INA3221 hwmon."""
    out = sh("vcgencmd", "pmic_read_adc")
    if out:
        rails = {}
        for name, kind, val in _ADC.findall(out):
            a, v = rails.get(name, (None, None))
            rails[name] = (float(val), v) if kind == "A" else (a, float(val))
        watts = {k: round(a * v, 3) for k, (a, v) in rails.items() if a and v}
        return round(sum(watts.values()), 2), watts, "pmic"
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        if read(f"{h}/name") != "ina3221":
            continue
        rails, total = {}, 0.0
        for i in (1, 2, 3):
            label = read(f"{h}/in{i}_label")
            mv, ma = read(f"{h}/in{i}_input"), read(f"{h}/curr{i}_input")
            if not (label and mv and ma):
                continue
            w = round(int(mv) * int(ma) / 1e6, 3)
            rails[label] = w
            if label == "VDD_IN":       # board total; the others are subsets
                total = w
        return round(total or sum(rails.values()), 2), rails, "ina3221"
    return None, {}, "none"


def gpu():
    """(load_pct, MHz) on the Jetson; (None, None) where there is no GPU."""
    load = freq = None
    for path in ("/sys/devices/platform/gpu.0/load",
                 "/sys/class/devfreq/17000000.gpu/device/load"):
        v = read(path)
        if v is not None:
            try:
                load = int(v) / 10.0        # per-mille
                break
            except ValueError:
                pass
    v = read("/sys/class/devfreq/17000000.gpu/cur_freq")
    if v:
        try:
            freq = int(v) // 10**6
        except ValueError:
            pass
    return load, freq


def temp_c():
    v = read("/sys/class/thermal/thermal_zone0/temp")
    best = int(v) / 1000 if v else None
    for z in glob.glob("/sys/class/thermal/thermal_zone*"):
        if read(f"{z}/type") in ("tj", "tj-thermal", "TJ"):
            t = read(f"{z}/temp")
            if t:
                best = int(t) / 1000
    return round(best, 1) if best else None


def meminfo():
    d = {}
    for line in (read("/proc/meminfo") or "").split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            d[k] = int(v.split()[0])
    return d


def procs():
    out = {}
    ps = sh("ps", "-eo", "pid,rss,etimes,args")
    for line in ps.split("\n")[1:]:
        p = line.split(None, 3)
        if len(p) < 4:
            continue
        pid, rss, et, args = p
        # The two engines a run can be served by, reported alike so the device
        # card can name the model whichever is up. little-gemma is the CUDA
        # int8 binary the S3 shim spawns (lg_openai_shim.py -> run-cuda-i8).
        # Matched on the executable: the shim's own command line names the
        # engine binary too (--engine .../run-cuda-i8 -m ...).
        exe = os.path.basename(args.split()[0])
        for key, pat in (("llama_server", "llama-server"), ("little_gemma", "run-cuda-i8")):
            if (pat not in args if key == "llama_server" else exe != pat) or "grep" in args:
                continue
            out[key] = {"pid": int(pid), "rss_mb": round(int(rss) / 1024),
                        "uptime_s": int(et),
                        "model": (re.search(r"-m (\S+)", args) or [None, ""])[1].split("/")[-1],
                        "flags": " ".join(a for a in args.split()
                                          if a.startswith("-") or a.isdigit())[:120]}
        for key, pat in (("lm_eval", "lm_eval"), ("run_measured", "run_measured.sh"),
                         ("telemetry", "telemetry.py"), ("queue", "queue_subsets.sh"),
                         ("build", "cmake --build"), ("download", "jetson_models.sh")):
            if pat in args and "grep" not in args:
                out.setdefault(key, {"pid": int(pid), "uptime_s": int(et)})
    return out


def progress():
    """Newest lm-eval progress bar across both output trees."""
    logs = glob.glob(f"{ROOT}/*/*/lm_eval.log") + glob.glob(f"{ROOT}/*/*/*/lm_eval.log")
    logs = [p for p in logs if os.path.getsize(p)]
    if not logs:
        return None
    path = max(logs, key=os.path.getmtime)
    try:
        with open(path, errors="replace") as f:
            f.seek(max(0, os.path.getsize(path) - 8000))
            tail = f.read().replace("\r", "\n")
    except OSError:
        return None
    hits = _TQDM.findall(tail)
    if not hits:
        return None
    pct, done, total, elapsed, eta, rate = hits[-1]
    return {"run": os.path.basename(os.path.dirname(path)), "path": path,
            "pct": int(pct), "done": int(done), "total": int(total),
            "elapsed": elapsed, "eta": eta, "s_per_item": float(rate),
            "age_s": round(time.time() - os.path.getmtime(path))}


def measured_latest():
    dirs = sorted(glob.glob(f"{ROOT}/measured/*"), key=os.path.getmtime)
    if not dirs:
        return None
    d = dirs[-1]
    out = {"dir": os.path.basename(d)}
    tele = os.path.join(d, "telemetry.csv")
    if os.path.exists(tele):
        try:
            with open(tele) as f:
                head = f.readline().strip().split(",")
                f.seek(max(0, os.path.getsize(tele) - 4000))
                rows = [r for r in f.read().split("\n") if r.count(",") == len(head) - 1]
            out["samples"] = sum(1 for _ in open(tele)) - 1
            if rows:
                last = dict(zip(head, rows[-1].split(",")))
                out["last"] = {k: last.get(k) for k in
                               ("ts_iso", "cpu_pct", "temp_c", "power_w", "mem_used_mb",
                                "proc_rss_mb", "throttled")}
        except OSError:
            pass
    s = os.path.join(d, "summary.json")
    if os.path.exists(s):
        try:
            j = json.load(open(s))
            out["summary"] = {"energy_wh": j["power"]["energy_wh"],
                              "idle_w": j["power"]["idle_w"],
                              "mean_w": j["power"]["work_mean_w"],
                              "j_per_token": j["efficiency"]["j_per_generated_token"],
                              "tok_s_per_w": j["efficiency"]["decode_tok_s_per_w"],
                              "gen_tokens": j["tokens"]["generated_tokens"]}
        except (OSError, KeyError, ValueError):
            pass
    return out


def _num(x):
    """lm-eval writes "N/A" instead of a number when the sample is tiny."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def completed():
    """Scores of finished lm-eval runs, newest first.

    The matrix fills its cells from this list, so it must reach back over the
    whole grid: 12 llama.cpp runs per board plus the Jetson's 12 little-gemma
    ones. At the old limit of 12, each new S3 result pushed a llama.cpp score
    out and its cell fell back to "not run"."""
    out = []
    for p in sorted(glob.glob(f"{ROOT}/stdbench/*/*/results_*.json"),
                    key=os.path.getmtime, reverse=True)[:48]:
        try:
            j = json.load(open(p))
            # prefer the aggregate task over its per-subject children
            keys = list(j["results"])
            task = next((k for k in ("mmlu_pro", "tinyGSM8k", "gsm8k", "ifeval") if k in keys), keys[0])
            res = j["results"][task]
            score = _num(res.get("exact_match,custom-extract"))
            if score is None:
                score = _num(res.get("exact_match,flexible-extract"))
            se = _num(res.get("exact_match_stderr,custom-extract"))
            out.append({"run": p.split("/stdbench/")[1].split("/")[0], "task": task,
                        "score": round(100 * score, 1) if score is not None else None,
                        "stderr": round(100 * se, 1) if se is not None else 0,
                        "minutes": round((_num(j.get("total_evaluation_time_seconds")) or 0) / 60),
                        "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p)))})
        except (OSError, ValueError, StopIteration, KeyError):
            continue
    return out


def setup_state():
    """Jetson only: model downloads and the llama.cpp CUDA build."""
    out = {}
    models = sorted(glob.glob(f"{ROOT}/models/*.gguf"))
    if models:
        out["models"] = [{"name": os.path.basename(m),
                          "gb": round(os.path.getsize(m) / 2**30, 2)} for m in models]
    log = "/tmp/cmake_build.log"
    if os.path.exists(log):
        try:
            with open(log, errors="replace") as f:
                f.seek(max(0, os.path.getsize(log) - 4000))
                hits = _CMAKE.findall(f.read())
            out["build_pct"] = int(hits[-1]) if hits else 0
            out["build_done"] = os.path.exists("/tmp/build.done")
            out["build_age_s"] = round(time.time() - os.path.getmtime(log))
        except OSError:
            pass
    return out or None


def main():
    w, rails, src = power()
    gload, gmhz = gpu()
    m = meminfo()
    disks = {}
    for mount in ("/", "/mnt/ssd-ex", "/mnt/data1"):
        if os.path.ismount(mount) or mount == "/":
            st = os.statvfs(mount)
            disks[mount] = {"free_gb": round(st.f_bavail * st.f_frsize / 2**30, 1),
                            "total_gb": round(st.f_blocks * st.f_frsize / 2**30, 1)}
    print(json.dumps({
        "host": os.uname().nodename, "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "uptime_s": int(float((read("/proc/uptime") or "0").split()[0])),
        "load1": float((read("/proc/loadavg") or "0").split()[0]),
        "cpu_pct": cpu_pct(), "cpus": os.cpu_count(),
        "power_w": w, "power_src": src, "rails": rails,
        "temp_c": temp_c(),
        "gpu_pct": gload, "gpu_mhz": gmhz,
        "throttled": (sh("vcgencmd", "get_throttled").strip().split("=") + [None])[1],
        "mem_used_mb": round((m.get("MemTotal", 0) - m.get("MemAvailable", 0)) / 1024),
        "mem_total_mb": round(m.get("MemTotal", 0) / 1024),
        "swap_used_mb": round((m.get("SwapTotal", 0) - m.get("SwapFree", 0)) / 1024),
        "disks": disks, "procs": procs(), "progress": progress(),
        "measured": measured_latest(), "completed": completed(), "setup": setup_state(),
    }))


if __name__ == "__main__":
    main()
