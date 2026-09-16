#!/usr/bin/env python3
"""Web UI service. Serves the page and bridges the Unix sockets to a browser.

Consumes the same contracts as everything else — it is an observer plus an
utterance injector, not a special case:
  reads  $VA_EVENT_SOCK   orchestrator events (JSON lines)
  reads  $VA_ASR_SOCK     transcripts, and WRITES to it to inject a typed turn
  writes $VA_TTS_SOCK     "!clear" for barge-in

Endpoints: GET / (page), GET /events (SSE), POST /say, POST /clear, GET /status.

NOTE: no authentication. $VA_WEB_HOST defaults to 0.0.0.0 so you can open it
from another machine — anyone on the network can then talk to your agent. Set
it to 127.0.0.1 and use an SSH tunnel if that is not what you want.
"""
import json, os, queue, re, socket, subprocess, sys, tempfile, threading, time
import contextlib, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("VA_WEB_HOST", "0.0.0.0")
PORT = int(os.environ.get("VA_WEB_PORT", "8090"))
UI = os.environ.get("VA_WEB_UI", "/opt/voice-agent/ui.html")
ASR_SOCK = os.environ.get("VA_ASR_SOCK", "/run/voice-agent/asr.sock")
TTS_SOCK = os.environ.get("VA_TTS_SOCK", "/run/voice-agent/tts.sock")
EVENT_SOCK = os.environ.get("VA_EVENT_SOCK", "/run/voice-agent/events.sock")
UNITS = ["va-asr", "va-llm", "va-tts", "va-tools", "va-orchestrator"]

# Browser-mic transcription. Uses the same model/binary config as va-asr, so
# changing the model is still a one-line config edit — but note that swapping
# the ASR *binary* means updating va-asr and this file.
ASR_MODEL = os.environ.get("VA_ASR_MODEL", "")
ASR_BIN = os.environ.get("VA_ASR_WHISPER_BIN",
                         "/home/mitlab/whisper.cpp/build/bin/whisper-cli")
ASR_THREADS = os.environ.get("VA_WEB_ASR_THREADS", "4")
MAX_UPLOAD = int(os.environ.get("VA_WEB_MAX_UPLOAD", str(25 * 1024 * 1024)))
CERT = os.environ.get("VA_WEB_CERT", "")
KEY = os.environ.get("VA_WEB_KEY", "")

# Where va-tts drops one wav per clause when VA_TTS_AUDIO_OUT=spool:...
SPOOL = ""
if os.environ.get("VA_TTS_AUDIO_OUT", "").startswith("spool:"):
    SPOOL = os.environ["VA_TTS_AUDIO_OUT"][6:]
SPOOL_KEEP = int(os.environ.get("VA_WEB_SPOOL_KEEP", "40"))

_subs, _lock = [], threading.Lock()


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def fanout(obj):
    with _lock:
        for q in list(_subs):
            with contextlib.suppress(Exception):
                q.put_nowait(obj)


def tail_socket(path, wrap):
    """Reconnecting reader: a service restart must not kill the UI."""
    while True:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(path)
            with s, s.makefile("rb") as f:
                for raw in f:
                    line = raw.decode("utf-8", "replace").strip()
                    if line:
                        fanout(wrap(line))
        except OSError:
            pass
        time.sleep(2)


def _by_mtime(names):
    """Oldest first. Piper's "timestamp" filenames looked monotonic, but its
    counter resets on every process restart (every barge-in respawns it) —
    after a restart the new files' names sort BEFORE the old ones, so the
    trim below deleted brand-new clips as "oldest" before the browser could
    ever fetch them. Actual mtime doesn't have that problem."""
    return sorted(names, key=lambda n: os.path.getmtime(os.path.join(SPOOL, n)))


def watch_spool():
    """Announce each new clause wav so the browser can play it in order."""
    seen = set()
    # Ignore whatever was already there when we started.
    with contextlib.suppress(OSError):
        seen = set(os.listdir(SPOOL))
    while True:
        try:
            # "in-" files are recorded input, not synthesised speech.
            names = _by_mtime(n for n in os.listdir(SPOOL)
                              if n.endswith(".wav") and not n.startswith("in-"))
            for n in names:
                if n in seen:
                    continue
                p = os.path.join(SPOOL, n)
                # Wait until piper has finished writing before announcing.
                if os.path.getsize(p) < 64:
                    continue
                seen.add(n)
                fanout({"type": "audio", "url": "/audio/" + n,
                        "seconds": wav_seconds(p),
                        "bytes": os.path.getsize(p), "t": time.time()})
            # Keep the spool bounded; old clips are already played.
            for group in (names, _by_mtime(n for n in os.listdir(SPOOL)
                                           if n.startswith("in-"))):
                if len(group) > SPOOL_KEEP:
                    for n in group[:-SPOOL_KEEP]:
                        with contextlib.suppress(OSError):
                            os.unlink(os.path.join(SPOOL, n))
                        seen.discard(n)
        except OSError:
            pass
        time.sleep(0.25)


def send_line(path, line):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    with s:
        s.connect(path)
        s.sendall((line + "\n").encode())


def wav_seconds(path):
    import wave
    with contextlib.suppress(Exception):
        with wave.open(path) as w:
            return round(w.getnframes() / w.getframerate(), 2)
    return None


def transcribe_upload(blob, info):
    """Browser audio (webm/opus, mp4/aac, whatever MediaRecorder produced) ->
    16k mono wav via ffmpeg -> whisper. Fills `info` with real timings."""
    src = dst = None
    t_start = time.time()
    try:
        fd, src = tempfile.mkstemp(suffix=".bin")
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        fd, dst = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", src,
             "-ar", "16000", "-ac", "1", dst],
            capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            log("web: ffmpeg failed:", r.stderr.strip()[-200:])
            return ""
        info["decode_s"] = round(time.time() - t_start, 2)
        info["audio_s"] = wav_seconds(dst)
        # Keep the converted wav so the UI can replay exactly what whisper heard.
        # "in-" prefixed, so the clause watcher does not mistake it for speech out.
        if SPOOL:
            with contextlib.suppress(OSError):
                os.makedirs(SPOOL, exist_ok=True)
                name = f"in-{int(time.time() * 1000)}.wav"
                with open(dst, "rb") as s, open(os.path.join(SPOOL, name), "wb") as o:
                    o.write(s.read())
                info["url"] = "/audio/" + name
        t_asr = time.time()
        r = subprocess.run(
            [ASR_BIN, "-m", ASR_MODEL, "-f", dst, "-t", ASR_THREADS, "-nt", "-np"],
            capture_output=True, text=True, timeout=600)
        info["asr_s"] = round(time.time() - t_asr, 2)
        if info["audio_s"]:
            info["asr_rtf"] = round(info["asr_s"] / info["audio_s"], 2)
        if r.returncode != 0:
            log("web: whisper failed:", r.stderr.strip()[-200:])
            return ""
        text = " ".join(r.stdout.split())
        return "" if text in ("[BLANK_AUDIO]", "[SILENCE]") else text
    except (OSError, subprocess.SubprocessError) as e:
        log("web: transcribe error:", e)
        return ""
    finally:
        for p in (src, dst):
            if p:
                with contextlib.suppress(OSError):
                    os.unlink(p)


CONFIG_FILE = os.environ.get("VA_CONFIG_FILE", "/etc/voice-agent/config.env")
# Choices made in the UI live here, not in config.env. config.env holds deployed
# defaults and gets overwritten when the code is redeployed; this file does not,
# so a model or reasoning choice survives both restarts and deploys.
RUNTIME_FILE = os.environ.get("VA_RUNTIME_FILE", "/etc/voice-agent/runtime.env")
MODELS_DIR = os.environ.get("VA_MODELS_DIR", "/home/mitlab/models")


def _read(path, key):
    with contextlib.suppress(OSError):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    return None


def config_value(key):
    """Runtime override wins, then the deployed default, then our own env
    (which is only a snapshot from whenever this service last started)."""
    v = _read(RUNTIME_FILE, key)
    if v is None:
        v = _read(CONFIG_FILE, key)
    return v if v is not None else os.environ.get(key, "")


def describe(path):
    """Best-effort label from the filename. Cheap and honest — no GGUF parse."""
    n = os.path.basename(path)
    fam = "Gemma 4 E2B" if "E2B" in n else "Gemma 4 E4B" if "E4B" in n else \
          "Gemma 4 12B" if "12B" in n else "Qwen3 4B" if "qwen3-4b" in n.lower() else n
    quant = next((q for q in ("Q4_K_XL", "Q4_K_M", "Q4_0", "Q2_K_XL", "Q8_0")
                  if q.lower() in n.lower()), "")
    qat = "QAT" if "qat" in n.lower() else ""
    size = 0
    with contextlib.suppress(OSError):
        size = os.path.getsize(path)
    return {"path": path, "name": n, "family": fam, "quant": quant,
            "qat": bool(qat), "gib": round(size / 2**30, 2) if size else None}


def list_models():
    cur = config_value("VA_LLM_MODEL_PATH")
    out = []
    with contextlib.suppress(OSError):
        for n in sorted(os.listdir(MODELS_DIR)):
            if n.endswith(".gguf") and not n.startswith("mtp-"):
                out.append(describe(os.path.join(MODELS_DIR, n)))
    return {"current": cur, "models": out}


def llm_props():
    """Ask llama.cpp what it actually loaded, rather than trusting config."""
    import urllib.request
    base = config_value("VA_LLM_URL").split("/v1/")[0]
    with contextlib.suppress(Exception):
        with urllib.request.urlopen(base + "/props", timeout=3) as r:
            d = json.load(r)
            dm = d.get("default_generation_settings") or {}
            return {"n_ctx": dm.get("n_ctx") or d.get("n_ctx"),
                    "model": d.get("model_path") or dm.get("model")}
    return {}


def set_keys(updates):
    """Persist to the runtime file so the choice outlives restarts and deploys."""
    try:
        lines = []
        with contextlib.suppress(OSError):
            with open(RUNTIME_FILE) as f:
                lines = f.readlines()
        if not lines:
            lines = ["# Written by the voice-agent web UI. Overrides config.env.\n",
                     "# Safe to delete — the deployed defaults take over again.\n"]
        done = set()
        out = []
        for line in lines:
            k = line.strip().split("=", 1)[0]
            if k in updates:
                out.append(f"{k}={updates[k]}\n")
                done.add(k)
            else:
                out.append(line)
        out += [f"{k}={v}\n" for k, v in updates.items() if k not in done]
        with open(RUNTIME_FILE, "w") as f:
            f.writelines(out)
    except OSError as e:
        return False, f"state write failed: {e}"
    r = subprocess.run(["sudo", "-n", "systemctl", "restart", "va-llm"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"restart failed: {r.stderr.strip()[:200]}"
    return True, "restarting"


def switch_model(path):
    """Whitelisted by list_models(), then rewrite config and restart va-llm."""
    allowed = {m["path"] for m in list_models()["models"]}
    if path not in allowed:
        return False, "not an allowed model path"
    updates = {"VA_LLM_MODEL_PATH": path}
    # A draft head is model-specific; carrying the old one over would be wrong.
    if config_value("VA_LLM_SPEC_ARGS"):
        args, msg = mtp_args(path)
        if not args:
            updates["VA_LLM_SPEC_ARGS"] = ""
        else:
            updates["VA_LLM_SPEC_ARGS"] = args
    return set_keys(updates)


def mtp_args(model_path):
    """The MTP draft head that matches this model, if it is on disk."""
    n = os.path.basename(model_path)
    tier = "E2B" if "E2B" in n else "E4B" if "E4B" in n else "12B" if "12B" in n else None
    if not tier:
        return "", f"no Gemma 4 MTP head exists for {n}"
    head = os.path.join(MODELS_DIR, f"mtp-gemma-4-{tier}-it.gguf")
    if not os.path.exists(head):
        return "", f"draft head missing: {os.path.basename(head)}"
    return (f"--spec-type draft-mtp --spec-draft-model {head} "
            f"--spec-draft-n-max 3"), "ok"


def set_option(key, value):
    if key == "reasoning":
        if value not in ("on", "off", "auto"):
            return False, "reasoning must be on, off or auto"
        if value == "off":
            return set_keys({"VA_LLM_REASONING": "off",
                             "VA_LLM_REASONING_BUDGET": "-1",
                             "VA_LLM_MAX_TOKENS": "200"})
        # Thinking needs its own headroom AND a cap, or a hard question spends
        # the entire budget reasoning and returns no answer at all.
        return set_keys({"VA_LLM_REASONING": value,
                         "VA_LLM_REASONING_BUDGET": "320",
                         "VA_LLM_MAX_TOKENS": "700"})
    if key == "mtp":
        if value not in ("on", "off"):
            return False, "mtp must be on or off"
        if value == "off":
            return set_keys({"VA_LLM_SPEC_ARGS": ""})
        args, msg = mtp_args(config_value("VA_LLM_MODEL_PATH"))
        if not args:
            return False, msg
        return set_keys({"VA_LLM_SPEC_ARGS": args})
    return False, "unknown option"


# Crest/badge proxy. Loading these straight from the browser is flaky — one
# transient failure and the <img> is gone — and it also needs the browser to
# reach the internet. The Pi fetches them reliably, so proxy and cache.
IMG_HOSTS = {"img.sofascore.com", "upload.wikimedia.org",
             "thumb.wikimedia.org", "media.formula1.com",
             "raw.githubusercontent.com"}
_img_cache, _img_lock = {}, threading.Lock()


def proxy_image(url):
    with _img_lock:
        hit = _img_cache.get(url)
    if hit:
        return hit
    host = urllib.parse.urlparse(url).hostname or ""
    if host not in IMG_HOSTS:
        return None
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux aarch64)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            blob = r.read(400_000)
            ctype = r.headers.get("Content-Type", "image/png")
    except (urllib.error.URLError, OSError) as e:
        log("web: image proxy failed:", e)
        return None
    with _img_lock:
        if len(_img_cache) > 200:
            _img_cache.clear()
        _img_cache[url] = (blob, ctype)
    return blob, ctype


def llm_ready():
    """systemd says "active" the moment it forks, but llama-server answers 503
    while it loads several GB. Ask it directly."""
    import urllib.error, urllib.request
    base = config_value("VA_LLM_URL").split("/v1/")[0]
    try:
        with urllib.request.urlopen(base + "/health", timeout=3) as r:
            return r.status == 200
    except urllib.error.HTTPError:
        return False          # 503 -> still loading
    except Exception:
        return False


def statuses():
    out = {}
    for u in UNITS:
        r = subprocess.run(["systemctl", "is-active", u],
                           capture_output=True, text=True)
        out[u] = r.stdout.strip() or "unknown"
    if out.get("va-llm") == "active" and not llm_ready():
        out["va-llm"] = "loading"
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                with open(UI, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, b"ui.html missing", "text/plain")
        elif self.path == "/status":
            self._send(200, json.dumps(statuses()))
        elif self.path == "/models":
            self._send(200, json.dumps(list_models()))
        elif self.path == "/config":
            # What the pipeline is actually configured to do, for the inspector.
            self._send(200, json.dumps({
                "llm_url": config_value("VA_LLM_URL"),
                "llm_threads": config_value("VA_LLM_THREADS"),
                "llm_ctx": config_value("VA_LLM_CTX"),
                "max_tokens": config_value("VA_LLM_MAX_TOKENS"),
                "model": describe(config_value("VA_LLM_MODEL_PATH")),
                "asr_model": os.path.basename(config_value("VA_ASR_MODEL")),
                "asr_threads": config_value("VA_ASR_THREADS"),
                "tts_voice": os.path.basename(config_value("VA_TTS_VOICE")),
                "tts_sink": config_value("VA_TTS_AUDIO_OUT"),
                "flush_chars": config_value("VA_FLUSH_CHARS"),
                "history_turns": config_value("VA_HISTORY_TURNS"),
                "barge_in": config_value("VA_BARGE_IN") == "1",
                "search_backend": config_value("VA_SEARCH_BACKEND"),
                "search_results": config_value("VA_SEARCH_RESULTS"),
                "fetch_chars": config_value("VA_FETCH_CHARS"),
                "max_tool_rounds": config_value("VA_MAX_TOOL_ROUNDS"),
                # Live state, plus the measured reason for the default.
                "reasoning": config_value("VA_LLM_REASONING") or "off",
                "reasoning_note":
                    "On improved E2B arithmetic 7/10 -> 10/10, but costs ~250 "
                    "output tokens before the answer: ~30s on E2B, ~68s on E4B.",
                "mtp": "on" if config_value("VA_LLM_SPEC_ARGS") else "off",
                "mtp_note":
                    "Measured slower on this CPU: little-gemma 0.96x, "
                    "LiteRT-LM 0.69x (E4B) and 0.55x (E2B). Verify costs ~N "
                    "tokens for N drafts when all 4 cores are already busy.",
                "props": llm_props(),
            }))
        elif self.path == "/events":
            self.stream_events()
        elif self.path.startswith("/audio/"):
            self.serve_clip(self.path[len("/audio/"):])
        elif self.path.startswith("/img?"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got = proxy_image((q.get("u") or [""])[0])
            if not got:
                return self._send(404, b"no image", "text/plain")
            blob, ctype = got
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(blob)
        else:
            self._send(404, b"not found", "text/plain")

    def serve_clip(self, name):
        # Strip any path and allow only the names piper generates, so a crafted
        # URL cannot walk out of the spool directory.
        name = os.path.basename(name)
        if not SPOOL or not re.fullmatch(r"[0-9A-Za-z_-]{1,64}\.wav", name):
            return self._send(404, b"not found", "text/plain")
        path = os.path.join(SPOOL, name)
        try:
            with open(path, "rb") as f:
                self._send(200, f.read(), "audio/wav")
        except OSError:
            self._send(404, b"gone", "text/plain")

    def stream_events(self):
        q: "queue.Queue[dict]" = queue.Queue(maxsize=500)
        with _lock:
            _subs.append(q)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                try:
                    obj = q.get(timeout=15)
                    payload = f"data: {json.dumps(obj)}\n\n"
                except queue.Empty:
                    payload = ": keepalive\n\n"   # keeps proxies from timing out
                self.wfile.write(payload.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _lock:
                if q in _subs:
                    _subs.remove(q)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)

        if self.path == "/audio":
            if n <= 0 or n > MAX_UPLOAD:
                return self._send(413, json.dumps({"error": "bad size"}))
            blob = self.rfile.read(n)
            if not ASR_MODEL:
                return self._send(500, json.dumps({"error": "VA_ASR_MODEL unset"}))
            fanout({"type": "state", "state": "transcribing"})
            info = {"source": "microphone", "bytes": n,
                    "mime": self.headers.get("Content-Type") or "?",
                    "asr_engine": "whisper.cpp",
                    "asr_model": os.path.basename(ASR_MODEL),
                    "asr_threads": ASR_THREADS}
            text = transcribe_upload(blob, info)
            info["text"] = text
            fanout({"type": "input", **info})
            if not text:
                fanout({"type": "state", "state": "idle"})
                return self._send(200, json.dumps({"ok": True, "text": ""}))
            try:
                send_line(ASR_SOCK, text)   # onto the utterance bus
            except OSError as e:
                return self._send(502, json.dumps({"error": f"asr: {e}"}))
            return self._send(200, json.dumps({"ok": True, "text": text}))

        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, json.dumps({"error": "bad json"}))

        if self.path == "/say":
            text = (body.get("text") or "").strip().replace("\n", " ")
            if not text:
                return self._send(400, json.dumps({"error": "empty text"}))
            try:
                send_line(ASR_SOCK, text)
            except OSError as e:
                return self._send(502, json.dumps({"error": f"asr: {e}"}))
            fanout({"type": "input", "source": "typed", "text": text})
            self._send(200, json.dumps({"ok": True}))
        elif self.path == "/model":
            ok, msg = switch_model((body.get("path") or "").strip())
            fanout({"type": "system", "text": f"model switch: {msg}"})
            self._send(200 if ok else 400, json.dumps({"ok": ok, "message": msg}))
        elif self.path == "/option":
            ok, msg = set_option((body.get("key") or "").strip(),
                                 (body.get("value") or "").strip())
            fanout({"type": "system",
                    "text": f"{body.get('key')} -> {body.get('value')}: {msg}"})
            self._send(200 if ok else 400, json.dumps({"ok": ok, "message": msg}))
        elif self.path == "/clear":
            try:
                send_line(TTS_SOCK, "!clear")
            except OSError as e:
                return self._send(502, json.dumps({"error": f"tts: {e}"}))
            fanout({"type": "state", "state": "idle"})
            self._send(200, json.dumps({"ok": True}))
        else:
            self._send(404, json.dumps({"error": "not found"}))


def main():
    threading.Thread(target=tail_socket, args=(
        EVENT_SOCK, lambda l: json.loads(l)), daemon=True).start()
    threading.Thread(target=tail_socket, args=(
        ASR_SOCK, lambda l: {"type": "heard", "text": l, "t": time.time()}),
        daemon=True).start()
    if SPOOL:
        threading.Thread(target=watch_spool, daemon=True).start()
        log(f"web: serving clause audio from {SPOOL}")
    if HOST == "0.0.0.0":
        log("web: WARNING listening on all interfaces, no auth")
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    scheme = "http"
    if CERT and KEY:
        # Browser mic needs a secure context. Either serve HTTPS with a cert
        # (self-signed is fine, you just accept the warning once), or reach the
        # plain-HTTP port through an SSH tunnel so the origin is localhost.
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(CERT, KEY)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        scheme = "https"
    log(f"web: {scheme}://{HOST}:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
