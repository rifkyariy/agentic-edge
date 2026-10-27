#!/usr/bin/env python3
"""Copy finished runs off a board into findings/runs/<board>/<run>/, one
directory per run, in the layout paper_tables.py reads.

    python3 benchmark/collect_runs.py --board jetson --from MITLAB-JETSON:research \\
        mmlupro100-ae-full-e2b-s1 mmlupro100-lg-e2b-s1 ...
    python3 benchmark/collect_runs.py --board jetson --from ~/staging/research --paper

--from is a results root: an rsync source (host:path) or a local directory
holding stdbench/, measured/ and queue/jobs/ the way a board does. --paper
collects every run the manuscript uses (PAPER_RUNS below).

Per run it writes:

    results.json        lm-eval's results_*.json
    samples.jsonl.gz    every samples_*.jsonl, subjects in name order, one
                        reply per line exactly as lm-eval wrote it
    engine_build.txt    little-gemma runs: upstream pin and patch hashes
    engine.log.gz       verify-width sweeps (ae_gate.py): the engine's stderr
    replay.json         replay_lookup.py output; bench.md: llama-bench output
    server.log.gz       llama.cpp runs: llama-server's own log, with its
                        per-request timings and n-gram draft-acceptance lines
    measured/           run_measured.sh output — summary.json, meta.json,
                        requests.csv, command.log, telemetry.csv.gz
    queue/              the queue job that ran it — events.jsonl, and
                        fingerprint.json: the serving command line captured
                        while live, diffed against baselines.json

A board keeps one measured/ directory per label; a stdbench run
mmlupro100-X pairs with the measured label mmlupro-X. Stdlib only.
"""
import argparse
import glob
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAPER_RUNS = (
    [f"mmlupro100-{row}{m}-{s}"
     for row in ("", "lg-", "ae-full-", "ae-ngram-", "ae-reuse-", "ngram-n3m3-")
     for m in ("e2b", "e4b") for s in ("s1", "s2", "s3")]
    + ["mmlupro100-ae-full-r2-e2b-s1",          # the repeat, Sec. V / Table IV
       "mmlupro100-ngram-n3m2-e2b-s1",          # llama.cpp n-gram, width 3
       "mmlupro100-ngram-default-e2b-s1"]       # llama.cpp n-gram, stock
    + [f"ae-sweep-{m}-b{b}" for m in ("e2b", "e4b") for b in (0, 2, 3, 4)]
    + ["ae-sweep-e2b-b0-r2", "ae-sweep-e2b-b2-r2"]
)
# The Pi's part of the manuscript: the llama.cpp baseline (Table VIII), the
# thinking-on runs whose replies Table VII replays, the replays themselves
# (replay_lookup.py, all run on the Pi's tokenizer), and the batched-verify
# cost of Sec. VII. The agent-prompt replays ran too and come along.
PAPER_PI = (
    [f"mmlupro100-{m}-{s}{t}" for t in ("", "-think") for m in ("e2b", "e4b") for s in ("s1", "s2", "s3")]
    + ["replay-lookup-pi", "replay-lookup-lg-e2b", "replay-e4b-think", "pi-verify-cost-e2b",
       "replay-bfcl-reference", "replay-agentic-llama-bfcl", "replay-agentic-llama-ifeval"]
)
# The six -reuse runs that failed at startup (flag parsing, Sec. VI-D); kept
# because every run is reported. On the board under stdbench/failed/.
PAPER_FAILED = [f"mmlupro100-ae-reuse-{m}-{s}-flagsbug"
                for m in ("e2b", "e4b") for s in ("s1", "s2", "s3")]


def gz(src, dst):
    with open(src, "rb") as f, gzip.GzipFile(dst, "wb", mtime=0) as g:
        shutil.copyfileobj(f, g)


def label_of(run):
    """mmlupro100-ae-full-e2b-s1 -> mmlupro-ae-full-e2b-s1; sweeps keep their name."""
    return "mmlupro-" + run[len("mmlupro100-"):] if run.startswith("mmlupro100-") else run


def fetch(src, runs, failed, tmp):
    """Mirror just what is needed from a board (or a local root) into tmp."""
    if ":" not in src.split("/")[0]:
        return os.path.expanduser(src)
    inc = ["+ /%s/" % r for r in runs] + ["+ /failed/"] + ["+ /failed/%s/" % r for r in failed]
    keep = ["--include=results_*.json", "--include=samples_*.jsonl", "--include=engine_build.txt",
            "--include=engine.log", "--include=server.log", "--include=replay.json", "--include=bench.md"]
    with open(os.path.join(tmp, "inc"), "w") as f:
        f.write("\n".join(inc) + "\n")
    subprocess.run(["rsync", "-a", "--prune-empty-dirs", "--include-from", os.path.join(tmp, "inc"),
                    "--include=*/", *keep, "--exclude=*", src + "/stdbench/", tmp + "/stdbench/"], check=True)
    subprocess.run(["rsync", "-a", src + "/measured/", tmp + "/measured/",
                    "--include=*/", "--include=*.json", "--include=*.csv", "--include=*.log",
                    "--exclude=*"], check=True)
    os.makedirs(os.path.join(tmp, "queue"), exist_ok=True)
    subprocess.run(["rsync", "-a", src + "/queue/jobs/", tmp + "/queue/jobs/"], check=True)
    return tmp


def jobs_by_label(root):
    """label -> the last queue job that completed it."""
    out = {}
    for d in sorted(glob.glob(os.path.join(root, "queue", "jobs", "*"))):
        label, done = None, False
        try:
            with open(os.path.join(d, "events.jsonl")) as f:
                for line in f:
                    e = json.loads(line)
                    label = e.get("label", label)
                    done = done or (e.get("event") == "completed" and e.get("exit_code") == 0)
        except OSError:
            continue
        if label and done:
            out[label] = d
    return out


def measured_dir(root, label, failed=False):
    base = os.path.join(root, "measured", "failed" if failed else "")
    hits = sorted(glob.glob(os.path.join(base, label + "-2026*")))
    hits = [h for h in hits if failed == h.endswith("-flagsbug")]
    if not hits and label.endswith("-s1"):    # the Pi's first runs predate the subset tag
        return measured_dir(root, label[:-3], failed)
    return hits[-1] if hits else None


def collect(root, run, out, jobs, failed=False):
    src = os.path.join(root, "stdbench", "failed" if failed else "", run)
    os.makedirs(out, exist_ok=True)
    res = sorted(glob.glob(os.path.join(src, "**", "results_*.json"), recursive=True))
    if res:
        shutil.copy(res[-1], os.path.join(out, "results.json"))
    samples = sorted(glob.glob(os.path.join(src, "**", "samples_*.jsonl"), recursive=True))
    if samples:
        with gzip.GzipFile(os.path.join(out, "samples.jsonl.gz"), "wb", mtime=0) as g:
            for s in samples:
                with open(s, "rb") as f:
                    shutil.copyfileobj(f, g)
    for name in ("engine_build.txt", "replay.json", "bench.md"):
        if os.path.exists(os.path.join(src, name)):
            shutil.copy(os.path.join(src, name), os.path.join(out, name))
    # little-gemma's server.log is the shim's and duplicates requests.csv;
    # llama-server's carries what nothing else does (draft acceptance)
    keep_server = failed or not any(t in run for t in ("-lg-", "-ae-"))
    for name in ("engine.log", "server.log"):
        if os.path.exists(os.path.join(src, name)) and (name == "engine.log" or keep_server):
            gz(os.path.join(src, name), os.path.join(out, name + ".gz"))
    label = label_of(run[:-len("-flagsbug")] if failed else run)
    m = measured_dir(root, label, failed)
    if m:
        os.makedirs(os.path.join(out, "measured"), exist_ok=True)
        for name in ("summary.json", "meta.json", "requests.csv", "command.log"):
            if os.path.exists(os.path.join(m, name)):
                shutil.copy(os.path.join(m, name), os.path.join(out, "measured", name))
        if os.path.exists(os.path.join(m, "telemetry.csv")):
            gz(os.path.join(m, "telemetry.csv"), os.path.join(out, "measured", "telemetry.csv.gz"))
        with open(os.path.join(out, "measured", "SOURCE"), "w") as f:
            f.write(os.path.basename(m) + "\n")
    j = None if failed else jobs.get(label)
    if j:
        os.makedirs(os.path.join(out, "queue"), exist_ok=True)
        for name in ("events.jsonl", "fingerprint.json"):
            if os.path.exists(os.path.join(j, name)):
                shutil.copy(os.path.join(j, name), os.path.join(out, "queue", name))
    have = sorted(os.listdir(out))
    print("%-40s %s" % (run, " ".join(have)))
    return bool(res or m)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", required=True, help="pi | jetson — the directory under findings/runs/")
    ap.add_argument("--from", dest="src", required=True, help="results root: host:path or a local dir")
    ap.add_argument("--paper", action="store_true", help="collect every run the manuscript uses (per board)")
    ap.add_argument("runs", nargs="*")
    args = ap.parse_args()
    paper = {"jetson": (PAPER_RUNS, PAPER_FAILED), "pi": (PAPER_PI, [])}.get(args.board, ([], []))
    runs = list(args.runs) + (list(paper[0]) if args.paper else [])
    failed = list(paper[1]) if args.paper else []
    if not runs:
        ap.error("name runs, or pass --paper")
    dest = os.path.join(ROOT, "findings", "runs", args.board)
    with tempfile.TemporaryDirectory() as tmp:
        root = fetch(args.src, runs, failed, tmp)
        jobs = jobs_by_label(root)
        missing = [r for r in runs if not collect(root, r, os.path.join(dest, r), jobs)]
        missing += [r for r in failed if not collect(root, r, os.path.join(dest, "failed", r), jobs, True)]
    if missing:
        print("nothing found for: " + " ".join(missing), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
