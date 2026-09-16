#!/usr/bin/env python3
"""TTS service. Text in on a Unix socket, audio out.

SEAM: clients connect to $VA_TTS_SOCK and write UTF-8 lines.
  "text"    -> speak this clause (queued, spoken in order)
  "!clear"  -> stop immediately and drop queued audio (barge-in)
To swap TTS engines, replace only this file. Nothing upstream changes.

Audio sink is $VA_TTS_AUDIO_OUT:
  alsa:default          play through an ALSA device on the Pi
  file:/tmp/out.raw     append raw PCM to a file (works with no speaker)
  spool:/path/dir       one wav per clause, for the web UI to fetch and play

piper is kept resident: its stdout is wired straight into the sink, so clauses
stream out back-to-back and the 60MB voice is loaded once, not per clause.
"""
import json, os, socket, subprocess, sys, threading, contextlib

SOCK = os.environ.get("VA_TTS_SOCK", "/run/voice-agent/tts.sock")
VOICE = os.environ["VA_TTS_VOICE"]
SINK = os.environ.get("VA_TTS_AUDIO_OUT", "file:/tmp/va-tts.raw")
PIPER = os.environ.get("VA_TTS_PIPER_BIN", "/home/mitlab/voice/venv/bin/piper")

_lock = threading.Lock()
_proc = {"piper": None, "sink": None}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def sample_rate():
    with contextlib.suppress(Exception):
        with open(VOICE + ".json") as f:
            return int(json.load(f)["audio"]["sample_rate"])
    return 22050


def start_chain():
    """piper (resident) -> sink. Called at boot and after every !clear."""
    rate = sample_rate()

    if SINK.startswith("spool:"):
        # piper writes one wav per input line into a directory while staying
        # resident, so there is no per-clause model load and no need to find
        # audio boundaries in a raw stream.
        d = SINK[6:]
        os.makedirs(d, exist_ok=True)
        os.chmod(d, 0o755)
        piper = subprocess.Popen(
            [PIPER, "-m", VOICE, "-d", d, "--output-dir-naming", "timestamp"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _proc["piper"], _proc["sink"] = piper, None
        log(f"tts: chain up, {rate}Hz -> spool {d}")
        return

    piper = subprocess.Popen(
        [PIPER, "-m", VOICE, "--output-raw"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    if SINK.startswith("alsa:"):
        sink = subprocess.Popen(
            ["aplay", "-D", SINK[5:], "-q", "-r", str(rate), "-f", "S16_LE", "-c", "1"],
            stdin=piper.stdout, stderr=subprocess.DEVNULL,
        )
    elif SINK.startswith("file:"):
        out = open(SINK[5:], "ab")
        sink = subprocess.Popen(["cat"], stdin=piper.stdout, stdout=out,
                                stderr=subprocess.DEVNULL)
    else:
        raise SystemExit("tts: set VA_TTS_AUDIO_OUT to alsa:, file: or spool:")
    piper.stdout.close()  # the sink owns the read end now
    _proc["piper"], _proc["sink"] = piper, sink
    log(f"tts: chain up, {rate}Hz -> {SINK}")


def stop_chain():
    for k in ("piper", "sink"):
        p = _proc.get(k)
        if p and p.poll() is None:
            p.kill()
            with contextlib.suppress(Exception):
                p.wait(timeout=5)
    _proc["piper"] = _proc["sink"] = None


def speak(text):
    with _lock:
        p = _proc["piper"]
        if not p or p.poll() is not None:
            log("tts: piper died, restarting")
            stop_chain()
            start_chain()
            p = _proc["piper"]
        try:
            p.stdin.write((text + "\n").encode())
            p.stdin.flush()
        except OSError as e:
            log("tts: write failed:", e)


def clear():
    """Barge-in. Killing the chain is the only way to drop audio already
    inside piper's and aplay's buffers."""
    with _lock:
        log("tts: clear")
        stop_chain()
        start_chain()


def handle(conn):
    with conn, conn.makefile("rb") as f:
        for raw in f:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            if line == "!clear":
                clear()
            else:
                log(f"tts: speak {line[:60]!r}")
                speak(line)


def main():
    os.makedirs(os.path.dirname(SOCK), exist_ok=True)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(SOCK)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    os.chmod(SOCK, 0o666)
    srv.listen(8)
    start_chain()
    log(f"tts: listening on {SOCK}")
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    try:
        main()
    finally:
        stop_chain()
