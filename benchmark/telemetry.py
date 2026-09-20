#!/usr/bin/env python3
"""Per-second device telemetry for a Raspberry Pi 5 during a benchmark run.

    python3 telemetry.py --out run/telemetry.csv [--interval 1.0] [--proc llama-server]

One CSV row per sample: wall clock, CPU utilisation (total and per core), core
frequencies, temperature, throttle flags, memory, disk I/O, the inference
process's own CPU/RSS, and **board power** derived from the PMIC's per-rail
current and voltage readings.

Power method, per board:
  Pi 5      `vcgencmd pmic_read_adc` gives a current and a voltage channel per
            rail; power is the sum of V*I over all rails.
  Jetson    the INA3221 hwmon exposes VDD_IN (whole board) plus VDD_CPU_GPU_CV
            and VDD_SOC; VDD_IN is the total and the other two are subsets of
            it, so they are logged but not added.
Either way this is the board's own DC consumption and excludes PSU conversion
loss — an external meter would read perhaps 10-20% higher. It is consistent
across runs, which is what the efficiency comparison needs, but it is not wall
power. The two boards use the same method, so the comparison holds.

Stdlib only, reads /proc directly (the box has no mpstat/pidstat). One sample
costs ~15ms, dominated by the two vcgencmd calls.
"""
import argparse
import csv
import glob
import os
import re
import signal
import subprocess
import sys
import time

CLK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")
_ADC = re.compile(r"(\w+)_([AV])\s+\w+\(\d+\)=([\d.]+)")


def cpu_times():
    """[(total, idle)] for the aggregate line then each core."""
    out = []
    with open("/proc/stat") as f:
        for line in f:
            if not line.startswith("cpu"):
                break
            v = [int(x) for x in line.split()[1:]]
            out.append((sum(v), v[3] + v[4]))  # idle + iowait
    return out


def proc_times(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            v = f.read().rsplit(") ", 1)[1].split()
        return int(v[11]) + int(v[12]), int(v[21]) * PAGE  # utime+stime, rss
    except (OSError, IndexError):
        return None, None


def meminfo():
    d = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            d[k] = int(v.split()[0])  # kB
    return d


def diskstats():
    r = w = 0
    with open("/proc/diskstats") as f:
        for line in f:
            p = line.split()
            if p[2].startswith(("mmcblk0", "sda", "nvme0n1")) and not p[2][-1].isdigit():
                r += int(p[5]); w += int(p[9])  # sectors
    return r * 512, w * 512


def freqs():
    out = []
    for i in range(os.cpu_count() or 4):
        try:
            with open(f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq") as f:
                out.append(int(f.read()) // 1000)  # MHz
        except OSError:
            out.append(None)
    return out


def temp_c():
    """Hottest readable zone: the Pi has one, the Jetson has cpu/gpu/soc."""
    best = None
    for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        try:
            t = int(open(f"{z}/temp").read()) / 1000
        except (OSError, ValueError):
            continue
        if 0 < t < 200 and (best is None or t > best):
            best = t
    return round(best, 1) if best is not None else None


def vcgencmd(*args):
    try:
        return subprocess.run(["vcgencmd", *args], capture_output=True,
                              text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def rails():
    """{rail: watts} for whichever sensor this board has, plus the total.

    Returns (watts_by_rail, total_w, source)."""
    adc = vcgencmd("pmic_read_adc")
    if adc:
        pairs = {}
        for name, kind, val in _ADC.findall(adc):
            a, v = pairs.get(name, (None, None))
            pairs[name] = (float(val), v) if kind == "A" else (a, float(val))
        w = {k: round(a * v, 4) for k, (a, v) in pairs.items() if a is not None and v is not None}
        return w, round(sum(w.values()), 3), "pmic"
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            if open(f"{h}/name").read().strip() != "ina3221":
                continue
        except OSError:
            continue
        w, total = {}, None
        for i in (1, 2, 3):
            try:
                label = open(f"{h}/in{i}_label").read().strip()
                mv = int(open(f"{h}/in{i}_input").read())
                ma = int(open(f"{h}/curr{i}_input").read())
            except (OSError, ValueError):
                continue
            w[label] = round(mv * ma / 1e6, 4)
            if label == "VDD_IN":   # board total; the others are subsets of it
                total = w[label]
        return w, round(total if total is not None else sum(w.values()), 3), "ina3221"
    return {}, None, "none"


def gpu():
    """(load_pct, MHz) on the Jetson; (None, None) on the Pi."""
    load = freq = None
    for p in ("/sys/devices/platform/gpu.0/load",
              "/sys/class/devfreq/17000000.gpu/device/load"):
        try:
            load = int(open(p).read().strip()) / 10.0   # per-mille
            break
        except (OSError, ValueError):
            continue
    try:
        freq = int(open("/sys/class/devfreq/17000000.gpu/cur_freq").read()) // 10**6
    except (OSError, ValueError):
        pass
    return load, freq


def pid_of(name):
    try:
        r = subprocess.run(["pgrep", "-n", "-x", name], capture_output=True, text=True)
        return int(r.stdout.strip()) if r.returncode == 0 else None
    except (OSError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--proc", default="llama-server",
                    help="process to track; re-resolved every sample, so a "
                         "server restart mid-run is followed rather than lost")
    args = ap.parse_args()

    rail_names = sorted(rails()[0])
    ncpu = os.cpu_count() or 4
    cols = (["ts_epoch", "ts_iso", "cpu_pct"] + [f"cpu{i}_pct" for i in range(ncpu)]
            + [f"cpu{i}_mhz" for i in range(ncpu)]
            + ["temp_c", "throttled", "mem_used_mb", "mem_avail_mb", "swap_used_mb",
               "disk_read_kbs", "disk_write_kbs", "proc_pid", "proc_cpu_pct",
               "proc_rss_mb", "gpu_pct", "gpu_mhz", "power_w"]
            + [f"w_{r}" for r in rail_names])

    prev_cpu, prev_disk, prev_proc, prev_t = cpu_times(), diskstats(), None, time.time()
    pid = pid_of(args.proc)
    if pid:
        prev_proc = proc_times(pid)[0]

    stop = {"now": False}
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.__setitem__("now", True))

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        while not stop["now"]:
            time.sleep(max(0.0, args.interval - 0.02))
            now = time.time()
            dt = now - prev_t

            cpu = cpu_times()
            pct = []
            for (t0, i0), (t1, i1) in zip(prev_cpu, cpu):
                dtot, didle = t1 - t0, i1 - i0
                pct.append(round(100 * (dtot - didle) / dtot, 1) if dtot else 0.0)
            prev_cpu = cpu

            dr, dw = diskstats()
            disk = [round((dr - prev_disk[0]) / dt / 1024, 1),
                    round((dw - prev_disk[1]) / dt / 1024, 1)]
            prev_disk = (dr, dw)

            npid = pid_of(args.proc)
            if npid != pid:  # restarted: counters are not comparable
                pid, prev_proc = npid, (proc_times(npid)[0] if npid else None)
            pcpu = prss = None
            if pid:
                t, rss = proc_times(pid)
                if t is not None:
                    if prev_proc is not None:
                        pcpu = round(100 * (t - prev_proc) / CLK / dt, 1)
                    prev_proc = t
                    prss = round(rss / 2**20, 1) if rss else None

            m = meminfo()
            watts, total, _src = rails()
            gload, gmhz = gpu()
            thr = (vcgencmd("get_throttled").strip().split("=") + [""])[1]

            w.writerow([round(now, 3), time.strftime("%Y-%m-%dT%H:%M:%S"),
                        pct[0], *pct[1:1 + ncpu], *freqs()[:ncpu],
                        temp_c(), thr,
                        round((m["MemTotal"] - m["MemAvailable"]) / 1024),
                        round(m["MemAvailable"] / 1024),
                        round((m.get("SwapTotal", 0) - m.get("SwapFree", 0)) / 1024),
                        *disk, pid or "", pcpu if pcpu is not None else "",
                        prss if prss is not None else "",
                        gload if gload is not None else "",
                        gmhz if gmhz is not None else "", total]
                       + [watts.get(r, "") for r in rail_names])
            fh.flush()
            prev_t = now
    return 0


if __name__ == "__main__":
    sys.exit(main())
