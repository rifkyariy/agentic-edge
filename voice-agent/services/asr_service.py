#!/usr/bin/env python3
"""ASR service. Audio in, newline-delimited transcript out.

SEAM: clients connect to $VA_ASR_SOCK and read UTF-8 lines.
  "text"   -> a finalised utterance
  "~text"  -> a partial (best guess so far, may change)
To swap ASR engines, replace only this file. Nothing downstream changes.

Audio source is $VA_ASR_AUDIO_IN:
  file:/path/to.wav     replay a wav (works with no microphone attached)
  alsa:plughw:1,0       capture from an ALSA device
"""
import os, socket, subprocess, sys, threading, wave, contextlib, tempfile, time

SOCK = os.environ.get("VA_ASR_SOCK", "/run/voice-agent/asr.sock")
SRC = os.environ.get("VA_ASR_AUDIO_IN", "")
MODEL = os.environ["VA_ASR_MODEL"]
WCLI = os.environ.get("VA_ASR_WHISPER_BIN", "/home/mitlab/whisper.cpp/build/bin/whisper-cli")
THREADS = os.environ.get("VA_ASR_THREADS", "1")
CHUNK = float(os.environ.get("VA_ASR_CHUNK_SEC", "5"))

_clients, _lock = [], threading.Lock()


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def broadcast(line):
    data = (line + "\n").encode()
    with _lock:
        for c in list(_clients):
            try:
                c.sendall(data)
            except OSError:
                _clients.remove(c)
                with contextlib.suppress(OSError):
                    c.close()


def client_reader(conn):
    """A client may also WRITE a line, which is re-broadcast as an utterance.
    That makes this socket the utterance bus, so a web UI or a script can
    inject a typed turn on a machine with no microphone."""
    with contextlib.suppress(OSError), conn.makefile("rb") as f:
        for raw in f:
            line = raw.decode("utf-8", "replace").strip()
            if line:
                log(f"asr: injected {line!r}")
                broadcast(line)


def accept_loop(srv):
    while True:
        conn, _ = srv.accept()
        with _lock:
            _clients.append(conn)
        log("asr: client attached")
        threading.Thread(target=client_reader, args=(conn,), daemon=True).start()


def transcribe(path):
    r = subprocess.run(
        [WCLI, "-m", MODEL, "-f", path, "-t", THREADS, "-nt", "-np"],
        capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0:
        log("asr: whisper failed:", r.stderr.strip()[-200:])
        return ""
    # -nt strips timestamps; whisper still emits bracketed non-speech tags,
    # which we keep deliberately — the model should know it heard a door slam.
    return " ".join(r.stdout.split())


def chunks_from_wav(path):
    """Yield CHUNK-second mono 16k wav files, so a recording behaves like a mic."""
    with wave.open(path) as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1:
            log(f"asr: expected 16k mono, got {w.getframerate()}Hz "
                f"{w.getnchannels()}ch — resample it first")
        n = int(w.getframerate() * CHUNK)
        while True:
            frames = w.readframes(n)
            if not frames:
                return
            fd, tmp = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            with wave.open(tmp, "wb") as o:
                o.setnchannels(w.getnchannels())
                o.setsampwidth(w.getsampwidth())
                o.setframerate(w.getframerate())
                o.writeframes(frames)
            yield tmp


def chunks_from_alsa(device):
    while True:
        fd, tmp = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        subprocess.run(
            ["arecord", "-D", device, "-f", "S16_LE", "-r", "16000", "-c", "1",
             "-d", str(int(CHUNK)), "-q", tmp],
            check=False,
        )
        yield tmp


def main():
    os.makedirs(os.path.dirname(SOCK), exist_ok=True)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(SOCK)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    os.chmod(SOCK, 0o666)
    srv.listen(8)
    threading.Thread(target=accept_loop, args=(srv,), daemon=True).start()
    log(f"asr: listening on {SOCK}, source {SRC!r}")

    if SRC.startswith("file:"):
        source = chunks_from_wav(SRC[5:])
    elif SRC.startswith("alsa:"):
        source = chunks_from_alsa(SRC[5:])
    else:
        log(f"asr: set VA_ASR_AUDIO_IN to file:... or alsa:...")
        return 2

    for tmp in source:
        try:
            text = transcribe(tmp)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
        if text and text not in ("[BLANK_AUDIO]", "[SILENCE]"):
            log(f"asr: {text!r}")
            broadcast(text)
    # A file source ends; a mic source never does.
    log("asr: audio source exhausted")
    while SRC.startswith("file:"):
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
