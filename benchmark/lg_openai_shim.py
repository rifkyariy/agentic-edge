#!/usr/bin/env python3
"""An OpenAI-style /v1/chat/completions endpoint in front of little-gemma.

    python3 lg_openai_shim.py --engine ~/build/little-gemma/build/run-cuda-i8 \\
        -m ~/research/models/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf \\
        --thinking off --port 8080

little-gemma serves raw token streams over a Unix socket and has no HTTP at
all; lm-eval only speaks HTTP. This launches the engine (patched, with -raw:
see little_gemma/setup_jetson.sh), renders each request's messages with
Gemma 4's chat template exactly as llama-server renders them, sends the
prompt, and returns the reply the way llama-server returns it with
--reasoning-format none: the text as generated, thinking-channel markers
inline, the closing <turn|> removed.

The rendering is checked byte-for-byte against llama-server's own
/apply-template output (tests/fixtures/gemma4_template.json), for both
-rea off and -rea on. The two differ only by "<|think|>\\n" at the start of the
system turn, which is what --thinking on adds here.

Serving flags, and the llama.cpp flags they stand in for:
  --thinking off|on   -rea off|on           (<|think|> in the system turn)
  --think N           --reasoning-budget N  (engine -think; -1 unlimited)
  context 8192        -c 8192               (SERVE_SEQ, compiled in)
  answer cap 2048     max_gen_toks 2048     (SERVE_GEN, patched)
Decoding is greedy, the engine's default; there is no prompt cache to limit.

stdlib only, like everything else that runs on the boards.
"""
import argparse
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EOT = "<turn|>"
CAP = " [SERVE_GEN cap]"          # what the engine appends to a capped turn
FRAME_MAGIC, FRAME_TEXT = 0x01, ord("T")
FRAME_MAX = 4096                  # the engine ends the session on a longer T frame
CHUNK = 1024                      # well inside FRAME_MAX, whatever the encoding


def render(messages, thinking):
    """Gemma 4's chat template, as llama-server applies it. Content is trimmed
    (the MMLU-Pro system prompt ends in a newline that llama-server drops);
    assistant turns are "model" turns; the prompt ends on an open model turn.
    BOS is left to the engine's tokenizer, as llama-server leaves it to its."""
    out = []
    msgs = list(messages)
    if thinking:
        if msgs and msgs[0].get("role") == "system":
            first = msgs.pop(0)
            out.append("<|turn>system\n<|think|>\n%s<turn|>\n" % _text(first).strip())
        else:
            # Unverified against llama-server: no request so far has lacked a
            # system message. Refuse rather than guess the template.
            raise ValueError("--thinking on needs a system message to carry <|think|>")
    for m in msgs:
        role = {"assistant": "model"}.get(m.get("role"), m.get("role"))
        if role not in ("system", "user", "model"):
            raise ValueError("unsupported role %r" % m.get("role"))
        out.append("<|turn>%s\n%s<turn|>\n" % (role, _text(m).strip()))
    out.append("<|turn>model\n")
    return "".join(out)


def _text(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):                       # [{"type": "text", "text": ...}]
        if any(p.get("type") != "text" for p in c):
            raise ValueError("only text content is served here")
        return "".join(p.get("text", "") for p in c)
    return ""


def frames(text):
    """The prompt as 'T' frames, then the empty line that closes the turn."""
    data = text.encode("utf-8")
    out = bytearray()
    for i in range(0, len(data), CHUNK):
        part = data[i:i + CHUNK]
        out += struct.pack("<BBHHI", FRAME_MAGIC, FRAME_TEXT, 0, 0, len(part)) + part
    out += b"\n"
    return bytes(out)


def clean(raw, stops):
    """The reply as llama-server returns it: cut at the first stop string (not
    included), without the closing <turn|>. Returns (text, finish_reason)."""
    finish = "stop"
    text = raw
    cut = [text.find(s) for s in stops if s and s in text]
    if cut:
        return text[:min(cut)], "stop"
    if CAP in text:
        text, finish = text.split(CAP, 1)[0], "length"
    i = text.find(EOT)
    if i >= 0:
        text = text[:i]
    return text, finish


def ask(sock_path, prompt, stops, timeout):
    """One conversation: send the prompt, read until <turn|> or a stop string.
    Closing early on a stop string makes the engine's next send fail, which
    ends its turn at the next token — as llama-server stops at a stop string."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(sock_path)
        s.sendall(frames(prompt))
        s.shutdown(socket.SHUT_WR)                # one turn; the session ends after it
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            text = buf.decode("utf-8", errors="ignore")
            if EOT in text or any(st and st in text for st in stops):
                break
    finally:
        s.close()
    return buf.decode("utf-8", errors="replace")


def _die_with_parent():
    """prctl(PR_SET_PDEATHSIG, SIGTERM) in the child, Linux only."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)
    except (OSError, AttributeError):
        pass


class Engine:
    def __init__(self, args):
        self.args = args
        self.argv = [args.engine, "-m", args.model, "-raw",
                     "-think", str(args.think), "-s", args.sock]
        self.lock = threading.Lock()              # the engine serves one conversation at a time
        self.proc = None
        self.served = 0

    def start(self):
        # stderr is inherited: the run script pipes it through stamp.py, and
        # parse_llama_log.py reads the engine's per-turn "turn:" lines from it.
        # The engine must never outlive the shim: an orphan keeps the model
        # resident, and the next load is refused for lack of memory (seen on
        # the Jetson, 2026-09-25). PDEATHSIG covers a SIGKILLed shim too.
        self.proc = subprocess.Popen(self.argv, stdout=sys.stderr,
                                     preexec_fn=_die_with_parent)

    def ready(self):
        if self.proc is None or self.proc.poll() is not None:
            return False
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(self.args.sock)
            s.close()                             # an empty session: the engine logs start/end, nothing else
            return True
        except OSError:
            return False

    def props(self):
        return {"engine": "little-gemma", "model_path": self.args.model,
                "engine_args": " ".join(self.argv),
                "thinking": "on" if self.args.thinking == "on" else "off",
                "think": self.args.think, "served": self.served}


def handler(engine, log):
    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):
            pass

        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                ok = engine.ready()
                return self._send(200 if ok else 503, {"status": "ok" if ok else "loading"})
            if self.path == "/props":
                return self._send(200, engine.props())
            if self.path == "/v1/models":
                return self._send(200, {"object": "list", "data": [
                    {"id": os.path.basename(engine.args.model), "object": "model"}]})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
                return self._send(404, {"error": "not found"})
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                prompt = render(req["messages"], engine.args.thinking == "on")
            except (ValueError, KeyError, TypeError) as e:
                return self._send(400, {"error": {"message": str(e)}})
            stops = req.get("stop") or []
            if isinstance(stops, str):
                stops = [stops]
            if req.get("temperature") not in (None, 0, 0.0) or req.get("stream"):
                return self._send(400, {"error": {"message":
                    "greedy, non-streaming only: the engine runs without -temp"}})
            t0 = time.time()
            with engine.lock:
                try:
                    raw = ask(engine.args.sock, prompt, stops, engine.args.timeout)
                except OSError as e:
                    return self._send(503, {"error": {"message": "engine: %s" % e}})
                engine.served += 1
            text, finish = clean(raw, stops)
            print("shim: request %d  %d prompt chars  %d reply chars  %.2fs  %s"
                  % (engine.served, len(prompt), len(text), time.time() - t0, finish),
                  file=log, flush=True)
            self._send(200, {
                "id": "lg-%d" % engine.served, "object": "chat.completion",
                "created": int(t0), "model": req.get("model", "little-gemma"),
                "choices": [{"index": 0, "finish_reason": finish,
                             "message": {"role": "assistant", "content": text}}],
                "usage": {},
            })
    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", required=True, help="run-cuda-i8 built with the agentic-edge patch")
    ap.add_argument("-m", "--model", required=True)
    ap.add_argument("--thinking", choices=("off", "on"), default="off")
    ap.add_argument("--think", type=int, default=-1,
                    help="engine -think: reasoning budget in tokens, -1 unlimited")
    ap.add_argument("--sock", default="/tmp/lg-bench.sock")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--timeout", type=float, default=3600)
    args = ap.parse_args()

    engine = Engine(args)
    engine.start()
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: engine.proc.terminate())
    srv = ThreadingHTTPServer((args.host, args.port), handler(engine, sys.stderr))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("shim: %s on http://%s:%d, engine: %s"
          % ("thinking " + args.thinking, args.host, args.port, " ".join(engine.argv)),
          file=sys.stderr, flush=True)
    try:
        rc = engine.proc.wait()                   # the shim lives exactly as long as the engine
    except KeyboardInterrupt:
        engine.proc.terminate()
        rc = engine.proc.wait()
    srv.shutdown()
    print("shim: engine exited rc=%s" % rc, file=sys.stderr, flush=True)
    return rc or 0


if __name__ == "__main__":
    sys.exit(main())
