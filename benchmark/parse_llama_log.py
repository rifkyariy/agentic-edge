#!/usr/bin/env python3
"""Per-request token timings from llama-server's journal, as CSV.

    python3 parse_llama_log.py --since 2026-09-20T22:00:00 --until ... --out run/requests.csv

llama-server prints two timing lines per request (prompt eval and generation).
This pairs them by task id and stamps each with the journal's own clock, so the
rows line up with telemetry.csv on ts_epoch and every sample can be attributed
to prefill, decode, or idle.
"""
import argparse
import calendar
import csv
import re
import subprocess
import sys
import time

# 22:31:04 host llama-server[123]: 31.17.731 I slot print_timing: id 0 | task 57 |
#   prompt eval time = 25967.91 ms / 1170 tokens ( 22.19 ms per token, 45.06 tokens per second)
LINE = re.compile(
    r"^(?P<ts>\S+)\s+\S+\s+llama-server\[\d+\]:.*?"
    r"id\s+(?P<slot>\d+)\s+\|\s+task\s+(?P<task>\d+)\s+\|\s+"
    r"(?P<kind>prompt eval time|eval time|total time)\s+=\s+"
    r"(?P<ms>[\d.]+)\s+ms(?:\s+/\s+(?P<tokens>\d+)\s+tokens"
    r".*?(?P<tok_s>[\d.]+)\s+tokens per second)?")

# little-gemma's engine (via lg_openai_shim.py and stamp.py) logs one line per
# turn, after it ends; its "in" count and time are the prefill, ttft included:
# 2026-09-25T18:30:01+0800 host little-gemma[0]: turn: 1097 in 0.69s (1580.8 tok/s),
#   71 out 2.62s (27.1 tok/s), ttft 0.69s
LG_TURN = re.compile(
    r"^(?P<ts>\S+)\s+\S+\s+little-gemma\[\d+\]:\s*turn: (?P<pt>\d+) in (?P<ps>[\d.]+)s "
    r"\((?P<ptps>[\d.]+) tok/s\), (?P<gt>\d+) out (?P<gs>[\d.]+)s \((?P<gtps>[\d.]+) tok/s\)")


def epoch(ts):
    """journalctl -o short-iso stamps, e.g. 2026-09-20T22:31:04+0800."""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            t = time.strptime(ts, fmt)
            return calendar.timegm(t) - (t.tm_gmtoff or 0) if t.tm_gmtoff else time.mktime(t)
        except ValueError:
            continue
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--unit", default="va-llm")
    ap.add_argument("--file", default=None,
                    help="read a stamp.py-prefixed server log instead of the journal")
    ap.add_argument("--since", default=None)
    ap.add_argument("--until", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.file:
        with open(args.file, errors="replace") as f:
            log = f.read()
    else:
        if not args.since:
            sys.exit("--since is required when reading the journal")
        cmd = ["journalctl", "-u", args.unit, "--since", args.since,
               "-o", "short-iso", "--no-pager"]
        if args.until:
            cmd += ["--until", args.until]
        log = subprocess.run(cmd, capture_output=True, text=True).stdout

    tasks = {}
    for line in log.splitlines():
        lg = LG_TURN.match(line)
        if lg:                                    # a whole request on one line
            task = str(len(tasks))
            tasks[task] = {
                "task": task, "slot": "0", "ts_iso": lg["ts"], "end_iso": lg["ts"],
                "prompt_ms": float(lg["ps"]) * 1000, "prompt_tokens": int(lg["pt"]),
                "prompt_tok_s": float(lg["ptps"]),
                "gen_ms": float(lg["gs"]) * 1000, "gen_tokens": int(lg["gt"]),
                "gen_tok_s": float(lg["gtps"]),
            }
            continue
        m = LINE.match(line)
        if not m:
            continue
        d = tasks.setdefault(m["task"], {"task": m["task"], "slot": m["slot"]})
        kind = {"prompt eval time": "prompt", "eval time": "gen",
                "total time": "total"}[m["kind"]]
        d[f"{kind}_ms"] = float(m["ms"])
        if m["tokens"]:
            d[f"{kind}_tokens"] = int(m["tokens"])
            d[f"{kind}_tok_s"] = float(m["tok_s"])
        d.setdefault("ts_iso", m["ts"])
        d["end_iso"] = m["ts"]

    rows = []
    for d in tasks.values():
        e = epoch(d["end_iso"])
        prompt_ms, gen_ms = d.get("prompt_ms", 0.0), d.get("gen_ms", 0.0)
        rows.append({
            "task": int(d["task"]), "slot": int(d["slot"]),
            "end_epoch": round(e, 3) if e else "",
            "end_iso": d["end_iso"],
            # llama-server logs on completion, so the request began this far back
            "start_epoch": round(e - (prompt_ms + gen_ms) / 1000, 3) if e else "",
            "prompt_tokens": d.get("prompt_tokens", ""), "prompt_ms": prompt_ms or "",
            "prompt_tok_s": d.get("prompt_tok_s", ""),
            "gen_tokens": d.get("gen_tokens", ""), "gen_ms": gen_ms or "",
            "gen_tok_s": d.get("gen_tok_s", ""),
            "total_ms": d.get("total_ms", round(prompt_ms + gen_ms, 2)),
        })
    rows.sort(key=lambda r: r["end_epoch"] or 0)

    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else
                           ["task", "slot", "end_epoch", "end_iso", "start_epoch",
                            "prompt_tokens", "prompt_ms", "prompt_tok_s",
                            "gen_tokens", "gen_ms", "gen_tok_s", "total_ms"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} requests -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
