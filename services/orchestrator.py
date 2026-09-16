#!/usr/bin/env python3
"""Orchestrator. The only component that knows the conversation flow.

Reads finalised utterances from the ASR socket, streams a reply from any
OpenAI-compatible LLM, splits it into clauses, and writes those to the TTS
socket as they arrive — so speech starts before generation finishes.

The LLM seam is plain OpenAI /v1/chat/completions, so llama.cpp, LiteRT-LM and
anything else speaking that API swap by changing $VA_LLM_URL alone.
"""
import contextlib, json, os, queue, re, socket, sys, threading, time
import urllib.error, urllib.request

ASR_SOCK = os.environ.get("VA_ASR_SOCK", "/run/voice-agent/asr.sock")
TTS_SOCK = os.environ.get("VA_TTS_SOCK", "/run/voice-agent/tts.sock")
LLM_URL = os.environ.get("VA_LLM_URL", "http://127.0.0.1:8080/v1/chat/completions")
LLM_MODEL = os.environ.get("VA_LLM_MODEL", "local")
CONFIG_FILE = os.environ.get("VA_CONFIG_FILE", "/etc/voice-agent/config.env")
RUNTIME_FILE = os.environ.get("VA_RUNTIME_FILE", "/etc/voice-agent/runtime.env")


def live_int(key, default):
    """Read per turn, runtime overrides first, so the UI can change the token
    budget without restarting this process."""
    for path in (RUNTIME_FILE, CONFIG_FILE):
        with contextlib.suppress(Exception):
            with open(path) as f:
                for line in f:
                    if line.strip().startswith(key + "="):
                        return int(line.split("=", 1)[1].strip())
    return default
SYSTEM_FILE = os.environ.get("VA_LLM_SYSTEM", "")
HISTORY_TURNS = int(os.environ.get("VA_HISTORY_TURNS", "6"))
BARGE_IN = os.environ.get("VA_BARGE_IN", "1") == "1"
# Long enough to cover loading E4B (~4GB) off the SD card after a model switch.
LLM_WAIT_TRIES = int(os.environ.get("VA_LLM_WAIT_TRIES", "40"))
LLM_WAIT_SLEEP = float(os.environ.get("VA_LLM_WAIT_SLEEP", "3"))

# A clause ends at punctuation followed by space, or runs long enough to flush
# anyway. The system prompt is what makes these appear early; see README.
CLAUSE = re.compile(r"[^,.!?;:]*[,.!?;:]+\s+")
FLUSH_CHARS = int(os.environ.get("VA_FLUSH_CHARS", "90"))
# A real answer to a factual question is a few clauses. Seen on this model:
# it re-states the same fact with slightly different wording each time while
# narrating its own compliance with the system prompt ("Wait, I must not
# offer further help... let me rephrase...") — each restatement differs
# enough in exact wording to dodge the repeat check below, which needs a
# near-identical clause to fire. This is a blunt but unconditional backstop:
# a real answer is a handful of clauses, so this only ever cuts off a
# generation that has clearly gone wrong.
MAX_SPOKEN_CLAUSES = int(os.environ.get("VA_MAX_SPOKEN_CLAUSES", "14"))

EVENT_SOCK = os.environ.get("VA_EVENT_SOCK", "")
TOOLS_SOCK = os.environ.get("VA_TOOLS_SOCK", "")
MAX_TOOL_ROUNDS = int(os.environ.get("VA_MAX_TOOL_ROUNDS", "3"))
# How much of a tool's returned text to forward to the UI as evidence. The
# model reads all of it; this is only what the inspector shows.
EVIDENCE_CHARS = int(os.environ.get("VA_EVIDENCE_CHARS", "4000"))

utterances: "queue.Queue[str]" = queue.Queue()
interrupt = threading.Event()

_subs, _subs_lock = [], threading.Lock()


def publish(_kind, **fields):
    """Observability seam. JSON lines on $VA_EVENT_SOCK; no-op if unset.
    Observers get the conversation without reaching into this process.

    The parameter is _kind so that no event field name can ever collide with
    it — passing kind=... used to raise "multiple values for argument".
    """
    if not EVENT_SOCK:
        return
    data = (json.dumps({"type": _kind, "t": time.time(), **fields}) + "\n").encode()
    with _subs_lock:
        for c in list(_subs):
            try:
                c.sendall(data)
            except OSError:
                _subs.remove(c)


def event_server():
    with contextlib.suppress(FileNotFoundError):
        os.unlink(EVENT_SOCK)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(EVENT_SOCK)
    os.chmod(EVENT_SOCK, 0o666)
    srv.listen(8)
    while True:
        conn, _ = srv.accept()
        with _subs_lock:
            _subs.append(conn)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def connect(path, tries=60):
    for _ in range(tries):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(path)
            return s
        except OSError:
            time.sleep(1)
    raise SystemExit(f"orchestrator: could not connect to {path}")


def asr_reader():
    """Reconnecting: restarting va-asr must not deafen us permanently."""
    while True:
        try:
            s = connect(ASR_SOCK)
            log(f"orchestrator: attached to {ASR_SOCK}")
            with s, s.makefile("rb") as f:
                for raw in f:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line or line.startswith("~"):
                        continue  # partials are for display, not for answering
                    if BARGE_IN:
                        interrupt.set()
                    utterances.put(line)
        except OSError as e:
            log("orchestrator: asr socket error:", e)
        log("orchestrator: ASR stream closed, reattaching")
        time.sleep(2)


def tools_rpc(request, timeout=90):
    """One request, one reply, one connection. Absent service = no tools, which
    must degrade to a plain answer rather than breaking the turn."""
    if not TOOLS_SOCK:
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        with s, s.makefile("rwb") as f:
            s.connect(TOOLS_SOCK)
            f.write((json.dumps(request) + "\n").encode())
            f.flush()
            line = f.readline()
        return json.loads(line.decode("utf-8", "replace")) if line else None
    except (OSError, json.JSONDecodeError) as e:
        log("orchestrator: tools rpc failed:", e)
        return None


def tool_schema():
    d = tools_rpc({"op": "list"}, timeout=10)
    return (d or {}).get("tools") or []


class Mouth:
    """Reconnecting writer. va-tts restarting must not kill this process —
    independent restartability is the whole point of the split."""

    def __init__(self):
        self.sock = None

    def _send(self, payload):
        for attempt in (1, 2):
            try:
                if self.sock is None:
                    self.sock = connect(TTS_SOCK)
                self.sock.sendall(payload)
                return
            except OSError as e:
                with contextlib.suppress(OSError):
                    self.sock.close()
                self.sock = None
                if attempt == 2:
                    log("orchestrator: tts unreachable:", e)
                    publish("error", message=f"tts unreachable: {e}")

    def say(self, text):
        text = text.strip()
        if text:
            self._send((text + "\n").encode())

    def clear(self):
        self._send(b"!clear\n")


# Narration instead of action: the model says it will look something up rather
# than emitting a tool call, so nothing is ever looked up. Never speak these.
PROMISE = re.compile(
    r"(?i)\b(?:i(?:'ll| will| am going to| need to| should)|let me)\b[^.!?]{0,70}"
    r"\b(?:search|look (?:it|that|this) up|check|find out|browse)\b"
    r"|\bi (?:do not|don't) have (?:that|this|the|access)\b"
    r"|\bi (?:cannot|can't) (?:search|access|browse|look)\b")

# The model starts grading its own obedience out loud, then re-answers, then
# grades that too: "Let me know if you want details. (Self correction: do not
# offer further help.) My apologies, I cannot add extra sentences like that.
# Let me rephrase my answer. … Wait, I must stop as soon as I have answered."
# Each restatement is worded differently, so the repeat check never fires.
# The answer is already complete by the time this starts, so the whole turn is
# cut here and everything after it dropped.
META = re.compile(
    r"(?i)\bself[-\s]?correction\b|\blet me rephrase\b|\bmy apologies\b"
    r"|\bi cannot add\b|\bmy previous (?:response|answer)\b"
    r"|\bwait,? (?:i|this|that|my)\b|\bcorrection:\b"
    r"|\b(?:i|that) (?:must|should) (?:stop|not offer)\b"
    r"|\bas per (?:the|my) instructions\b|\bper the rules\b"
    r"|\b(?:do not|don't) (?:ask me|offer further)\b"
    # The sign-off the prompt already bans. It is always last, so cutting the
    # turn here loses nothing but the filler — and it is what the model then
    # notices and starts apologising for.
    r"|\blet me know if you (?:want|need|have|would)\b"
    r"|\banything else\b|\bhope (?:that|this) helps\b")

# Claiming a source when no tool ran. The prompt asks the model not to, but a
# small quantised model does it anyway, so the truth is asserted structurally:
# the orchestrator knows whether anything was actually fetched.
# Questions we refuse to answer from weights. Asking the model nicely does not
# work — it answered "score of man city vs man united" from memory and invented a
# citation — so these force tool_choice="required" on the first round.
NEEDS_TOOL = re.compile(
    r"(?i)\b(?:scores?|results?|who won|final score|full[- ]?time|standings?|"
    r"league table|fixtures?|kick[-\s]?off|lineups?|"
    # Up to two words may sit between "next"/"upcoming" and the noun —
    # "upcoming football match", "upcoming match for chelsea", "next premier
    # league game" — a team or sport name in between must not defeat this.
    r"next (?:\w+\s+){0,2}(?:match|game|fixture|race)|"
    r"upcoming (?:\w+\s+){0,2}(?:match|game|fixture)|"
    r"play next|when (?:do|does|is|are) .* play|"
    r"f1|formula\s*(?:1|one)|grand prix|\bgp\b|pole position|podium|"
    r"qualifying|fastest lap|who won|"
    r"latest news|breaking|headlines?|what happened|news (?:about|on)|"
    r"currently|right now|as of today|latest|newest|most recent|"
    r"today|yesterday|this (?:week|morning|evening)|"
    # money and markets
    r"exchange rate|conversion rate|currency rate|currency|forex|"
    r"how much is|how many|convert|worth in|"
    r"rate of|stock price|share price|market cap|inflation|"
    # other live facts
    r"weather|forecast|temperature)\b"
    r"|\bvs\.?\b|\bversus\b"
    # A currency pair. No \b before the code: "5000ntd to idr" has no boundary
    # between the digits and the letters, which is exactly how people type it.
    r"|(?<![a-z])[a-z]{3}\s*(?:to|into|in|→|/|-)\s*[a-z]{3}(?![a-z])"
    # Currency words, for "how many rupiah is 5000 taiwan dollars"
    r"|\b(?:rupiah|rupee|ringgit|baht|yen|yuan|won|peso|dirham|riyal|"
    r"dollars?|euros?|pounds?|francs?)\b")

# Nothing to look up: making something, transforming text, or opinion. These
# get NO tools at all, which also keeps the schema out of the prefill.
CREATIVE = re.compile(
    r"(?i)\b(?:write|compose|draft|make up|invent|imagine|pretend|"
    r"role[-\s]?play|brainstorm|rephrase|reword|rewrite|summari[sz]e|"
    r"translate|poem|haiku|limerick|sonnet|short story|joke|riddle|"
    r"song|lyrics|tell me a story)\b")


def classify(text):
    """live = must look it up; creative = nothing to look up; open = let the
    model decide. Deliberately a regex: an LLM classification round would cost
    another full prefill, which is 20-40s on this board."""
    if NEEDS_TOOL.search(text):
        return "live"
    if CREATIVE.search(text):
        return "creative"
    return "open"


# What KIND of live question this is, in the order it gets tested. Only used to
# explain the decision in the UI — the routing itself is classify() above plus
# forced_tool() below — so a miss here costs nothing but a vaguer label.
CATEGORIES = (
    ("race_result", "Formula 1 race result",
     r"(?i)(?:\bf1\b|formula\s*(?:1|one)|grand prix|\bgp\b)"
     r"(?!.*\b(?:next|upcoming|when)\b)"),
    ("race_next", "Upcoming Formula 1 race",
     r"(?i)(?:\bf1\b|formula\s*(?:1|one)|grand prix|\bgp\b).*"
     r"\b(?:next|upcoming|when)\b|\bnext race\b"),
    ("fixture", "Upcoming football fixture",
     r"(?i)\bnext (?:\w+\s+){0,2}(?:match|game|fixture)\b"
     r"|\bupcoming (?:\w+\s+){0,2}(?:match|game|fixture)\b"
     r"|\bplay next\b|\bwhen (?:do|does|is|are)\b.*\bplay\b|\bfixtures?\b"),
    ("match_result", "Football score / result",
     r"(?i)\b(?:scores?|results?|final score|full[- ]?time|who won|standings?"
     r"|league table|lineups?)\b|\bvs\.?\b|\bversus\b"),
    ("currency", "Currency / exchange rate",
     r"(?i)\bexchange rate\b|\bconversion rate\b|\bcurrency\b|\bforex\b"
     r"|\bconvert\b|\bworth in\b|\brate of\b"
     r"|(?<![a-z])[a-z]{3}\s*(?:to|into|in|→|/|-)\s*[a-z]{3}(?![a-z])"
     r"|\b(?:rupiah|rupee|ringgit|baht|yen|yuan|peso|dirham|riyal)\b"),
    ("market", "Market / price",
     r"(?i)\bstock price\b|\bshare price\b|\bmarket cap\b|\binflation\b"),
    ("weather", "Weather",
     r"(?i)\bweather\b|\bforecast\b|\btemperature\b"),
    ("news", "Breaking news / current events",
     r"(?i)\blatest news\b|\bbreaking\b|\bheadlines?\b|\bwhat happened\b"
     r"|\bnews (?:about|on)\b"),
    ("recency", "Something that changes over time",
     r"(?i)\bcurrently\b|\bright now\b|\bas of today\b|\blatest\b|\bnewest\b"
     r"|\bmost recent\b|\btoday\b|\byesterday\b|\bthis (?:week|morning|evening)\b"),
)


def categorise(text, kind):
    """(slug, human label, the words that triggered it). Explains the routing
    decision to the UI: the point is that a wrong classification should be
    visible, not buried."""
    if kind == "creative":
        m = CREATIVE.search(text)
        return "creative", "Make something (no lookup)", m.group(0) if m else ""
    if kind == "live":
        for slug, label, pat in CATEGORIES:
            m = re.search(pat, text)
            if m:
                return slug, label, m.group(0).strip()
        m = NEEDS_TOOL.search(text)
        return "live_other", "Needs current data", m.group(0).strip() if m else ""
    return "knowledge", "Answerable from the model's own knowledge", ""

# tool_choice="required" only forces *a* tool call — and on a long-enough
# history this small model evades even that: asked for Real Madrid's latest
# result it re-read its OWN earlier answer out of the history and repeated a
# six-day-old score, calling nothing, so no card was drawn either. Pinning the
# exact function is the only thing that has held, and llama.cpp honours a
# named tool_choice reliably only when that schema is the sole one on offer.
CATEGORY_TOOL = {
    "race_result": "f1_result", "race_next": "f1_result",
    "match_result": "match_result", "fixture": "match_result",
    "currency": "currency_rate", "weather": "weather_forecast",
}


def forced_tool(text, category=None):
    """Specific function name to pin tool_choice to, or True for "any tool
    required", or False. Only called once classify() already said "live"."""
    return CATEGORY_TOOL.get(category) or True


CCY = re.compile(r"(?i)(?<![a-z])([a-z]{3})\s*(?:to|into|in|→|/|-)\s*([a-z]{3})(?![a-z])")
AMOUNT = re.compile(r"(\d[\d,.]*)")
# Words that are about the asking, not about the subject.
STRIP_F1 = re.compile(r"(?i)\b(f1|formula\s*(?:1|one)|grand prix|gp|race|result|"
                      r"results|last|latest|who|won|the|of|in|at|show|me|tell|"
                      r"about|what|was|is|for|please)\b")


def fallback_args(tool, text, category):
    """Arguments for a pinned tool the model refused to call.

    llama.cpp does not reliably honour a named tool_choice — replaying a
    request pinned to weather_forecast, with that as the only schema, came
    back as plain text inventing "scattered thunderstorms, thirty-one point
    seven degrees" for Singapore. The lookup was already decided by the
    classifier, so the orchestrator performs it rather than letting a 4B
    model's grammar compliance decide whether the user gets real data.

    Returns None when the arguments cannot be recovered from the question, in
    which case the normal retry path applies instead of a wrong call.
    """
    if tool == "weather_forecast":
        # The tool geocodes and strips the question words itself.
        return {"place": text}
    if tool == "match_result":
        return {"query": text,
                "when": "next" if category in ("fixture", "race_next") else "past"}
    if tool == "f1_result":
        race = " ".join(STRIP_F1.sub(" ", text).split())
        return {"race": race} if race else {}
    if tool == "currency_rate":
        m = CCY.search(text)
        if not m:
            return None
        args = {"from": m.group(1).upper(), "to": m.group(2).upper()}
        a = AMOUNT.search(text)
        if a:
            with contextlib.suppress(ValueError):
                args["amount"] = float(a.group(1).replace(",", ""))
        return args
    return None

CITES = re.compile(
    r"(?i)\baccording to\b|\bthe search results?\b|\bbased on (?:the )?"
    r"(?:search|results)\b|\bi (?:searched|looked (?:it|this|that) up)\b")


def stream_reply(messages, tools=None, force_tool=False, busy_state="thinking"):
    """Yield ("content"|"thinking"|"finish"|"tool_calls", value) from an
    OpenAI-compatible endpoint. Publishes the exact request and the final usage
    so the UI shows what was really sent rather than a reconstruction."""
    payload_obj = {
        "model": LLM_MODEL, "messages": messages, "stream": True,
        "temperature": 0, "max_tokens": live_int("VA_LLM_MAX_TOKENS", 200),
        "stream_options": {"include_usage": True},
        # Greedy decoding with no penalty degenerates into loops — "I am here
        # for you. I hope you are well." until the budget runs out. llama.cpp
        # leaves repeat_penalty off by default, so set it explicitly.
        "repeat_penalty": 1.12,
        "repeat_last_n": 256,
        "presence_penalty": 0.4,
    }
    if tools:
        payload_obj["tools"] = tools
        if isinstance(force_tool, str):
            payload_obj["tool_choice"] = {
                "type": "function", "function": {"name": force_tool}}
        else:
            payload_obj["tool_choice"] = "required" if force_tool else "auto"
    body = json.dumps(payload_obj).encode()
    publish("request", url=LLM_URL, body=payload_obj, bytes=len(body))

    # A model switch restarts va-llm, which answers 503 for as long as it takes
    # to load the weights (seconds for E2B, longer for E4B). Wait it out instead
    # of dropping the turn.
    r = None
    for attempt in range(LLM_WAIT_TRIES):
        req = urllib.request.Request(
            LLM_URL, data=body, headers={"Content-Type": "application/json"})
        try:
            r = urllib.request.urlopen(req, timeout=600)
            break
        except urllib.error.HTTPError as e:
            if e.code != 503:
                raise
            reason = "model is loading"
        except urllib.error.URLError as e:
            reason = f"llm unreachable ({e.reason})"
        if attempt == 0:
            log(f"orchestrator: {reason}, waiting")
        publish("state", state="loading")
        publish("llm_wait", reason=reason,
                attempt=attempt + 1, of=LLM_WAIT_TRIES)
        time.sleep(LLM_WAIT_SLEEP)
    if r is None:
        raise RuntimeError("llm did not become ready")
    # Clears any "loading" state now the request is actually accepted. The
    # caller chooses the label: a round after tools is reading, not thinking.
    publish("state", state=busy_state)

    calls = {}   # index -> partial tool call, assembled from deltas
    with r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                return
            try:
                d = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if d.get("usage"):
                publish("usage", **d["usage"])
            ch = (d.get("choices") or [{}])[0]
            delta = ch.get("delta") or {}
            for tc in (delta.get("tool_calls") or []):
                slot = calls.setdefault(tc.get("index", 0),
                                        {"id": "", "name": "", "args": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                # Arguments arrive as a stream of JSON fragments.
                slot["args"] += fn.get("arguments") or ""
            if ch.get("finish_reason"):
                if calls:
                    yield "tool_calls", [calls[i] for i in sorted(calls)]
                yield "finish", ch["finish_reason"]
            # Reasoning tokens are not speakable; report them, never speak them.
            if delta.get("reasoning_content"):
                yield "thinking", delta["reasoning_content"]
            if delta.get("content"):
                yield "content", delta["content"]


def main():
    system = None
    if SYSTEM_FILE and os.path.exists(SYSTEM_FILE):
        system = open(SYSTEM_FILE).read().strip()
    history = []
    mouth = Mouth()
    if EVENT_SOCK:
        threading.Thread(target=event_server, daemon=True).start()
    threading.Thread(target=asr_reader, daemon=True).start()
    log("orchestrator: ready")

    while True:
        text = utterances.get()
        # Drain anything that piled up while we were busy; answer the latest.
        while not utterances.empty():
            text = utterances.get_nowait()
        interrupt.clear()
        if BARGE_IN:
            mouth.clear()

        log(f"orchestrator: user {text!r}")
        publish("user", text=text)
        publish("state", state="thinking")
        tools = tool_schema()
        # Ground the date every turn. Without it the model treats anything past
        # its training cutoff as "the future" and refuses to look it up.
        today = time.strftime("%A, %d %B %Y")
        # Exactly what the model was told about now, so the UI can show what
        # "latest" resolved to rather than leaving it implicit.
        publish("grounding", today=today, date=time.strftime("%Y-%m-%d"),
                clock=time.strftime("%H:%M:%S"),
                tz=time.strftime("%Z") or time.tzname[0],
                epoch=int(time.time()), grounded=bool(tools))
        sysmsg = system or ""
        if tools:
            sysmsg += (
                f"\n\nToday is {today}. Your training "
                "data ends well before this. Any date up to today is in the "
                "PAST and can be looked up — never say a past date is in the "
                "future, and never say you cannot access current information.\n"
                "When you need to look something up, call web_search "
                "immediately. Do not announce that you are going to search, and "
                "do not say you will search in your reply — the search happens "
                "only if you actually call the tool.\n"
                "If a search snippet does not contain the answer, call "
                "fetch_page on the most promising URL instead of replying that "
                "the results were unhelpful.\n"
                "Who currently holds a job or title, the latest version of "
                "anything, today's price, a recent result — these always need a "
                "search, because your memory of them is stale.\n"
                "A football score or match result ALWAYS requires calling "
                "match_result. You do not know any score from memory, and "
                "search snippets do not contain scores. If an earlier turn in "
                "this conversation stated a score, do not trust it — check "
                "again with match_result.\n"
                "Never say \"according to\", never name a website, and never "
                "imply you looked something up unless search results appear "
                "above in this conversation. If you did not search, say the "
                "information may be out of date.")
        msgs = ([{"role": "system", "content": sysmsg}] if sysmsg else []) \
            + history[-2 * HISTORY_TURNS:] + [{"role": "user", "content": text}]
        # Itemise the prefill so the UI can show what was assembled and why,
        # instead of only the finished JSON blob.
        publish("prompt", parts=[
            {"role": "system", "label": "System prompt",
             "chars": len(system or ""), "kept": bool(system)},
            {"role": "system", "label": "Date grounding + tool rules",
             "chars": len(sysmsg) - len(system or ""), "kept": bool(tools)},
            {"role": "history", "label": "Conversation history",
             "chars": sum(len(m.get("content") or "")
                          for m in history[-2 * HISTORY_TURNS:]),
             "msgs": len(history[-2 * HISTORY_TURNS:]),
             "of": HISTORY_TURNS, "kept": bool(history)},
            {"role": "user", "label": "This question", "chars": len(text),
             "text": text, "kept": True},
            {"role": "tools", "label": "Tool schemas offered",
             "count": len(tools or []), "kept": bool(tools)},
        ], total_chars=sum(len(m.get("content") or "") for m in msgs))

        buf, spoken, t0, first = "", [], time.time(), None
        think_chars, finish, think_tail, said_writing = 0, None, "", False
        tools_used = []
        recent, repeats, looping = [], 0, False   # loop detection for the turn
        empty_retry = False   # one retry if it answers with nothing after a tool
        try:
          kind = classify(text) if tools else "creative"
          slug, label, evidence = categorise(text, kind)
          offer_tools = None if kind == "creative" else tools
          # The pin follows the category the UI shows, so what it says was
          # decided and what was actually forced can never disagree.
          force_tool = forced_tool(text, slug) if kind == "live" else False
          if isinstance(force_tool, str):
              # llama.cpp's named tool_choice only reliably pins the call when
              # that is the only schema on offer — with all 5 present it has
              # been seen pick a different one anyway. Narrow the menu instead
              # of trusting tool_choice alone.
              offer_tools = [t for t in tools
                              if t["function"]["name"] == force_tool] or tools
          log(f"orchestrator: intent {kind} ({slug})")
          # Not kind=: publish's own first parameter is named kind.
          publish("intent", intent=kind, tools_offered=bool(offer_tools),
                  forced=force_tool, category=slug, category_label=label,
                  evidence=evidence,
                  offered=[t["function"]["name"] for t in (offer_tools or [])],
                  pinned=force_tool if isinstance(force_tool, str) else None)
          for rnd in range(MAX_TOOL_ROUNDS + 1):
            pending = None
            promised = False
            # When a tool call is required, anything the model says before it is
            # a guess. Hold it: speak it only if no tool call actually arrives.
            held = []
            # The final round is offered no tools, so the model cannot keep
            # asking to search and never answer.
            offer = offer_tools if rnd < MAX_TOOL_ROUNDS else None
            for kind, delta in stream_reply(
                    msgs, offer, force_tool,
                    "digesting" if rnd else "thinking"):
                if interrupt.is_set():
                    log("orchestrator: barge-in, abandoning reply")
                    break
                if kind == "finish":
                    finish = delta
                    continue
                if kind == "tool_calls":
                    pending = delta
                    continue
                if kind == "thinking":
                    think_chars += len(delta)
                    # Send a short tail as well as the count, so the UI can show
                    # what it is reasoning about instead of only how much.
                    think_tail = (think_tail + delta)[-180:]
                    publish("thinking", chars=think_chars,
                            at=round(time.time() - t0, 1),
                            tail=think_tail)
                    continue
                if not said_writing:
                    said_writing = True
                    publish("state", state="writing")
                buf += delta
                while True:
                    m = CLAUSE.match(buf)
                    if m and len(m.group(0).strip()) > 1:
                        clause = m.group(0).strip()
                    elif len(buf) >= FLUSH_CHARS and " " in buf:
                        cut = buf.rfind(" ", 0, FLUSH_CHARS)
                        clause, m = buf[:cut].strip(), None
                    else:
                        break
                    buf = buf[len(m.group(0)):] if m else buf[len(clause):]
                    if not clause:
                        continue
                    if offer and PROMISE.search(clause):
                        # Do not speak a promise to search — make it search.
                        promised = True
                        log(f"orchestrator: suppressed narration {clause!r}")
                        publish("narration_suppressed", text=clause)
                        continue
                    if META.search(clause):
                        # It has started narrating its own compliance. The
                        # answer is already said; everything from here is the
                        # self-correction loop, so end the turn.
                        log(f"orchestrator: self-correction, cutting off at "
                            f"{clause!r}")
                        publish("looping", text=clause, reason="self-correction")
                        looping = True
                        break
                    if force_tool:
                        held.append(clause)
                        continue

                    # Safety net for the loop: sampling penalties reduce it,
                    # they do not guarantee it away. Only clauses we actually
                    # speak are tracked — a discarded pre-tool guess used to
                    # poison this and suppress the real answer as a "repeat".
                    norm = re.sub(r"[^a-z0-9 ]", "", clause.lower()).strip()
                    if norm and norm in recent:
                        repeats += 1
                        if repeats >= 2:
                            log(f"orchestrator: repetition loop, cutting off "
                                f"at {clause!r}")
                            publish("looping", text=clause)
                            looping = True
                            break
                        continue
                    recent.append(norm)
                    if len(recent) > 8:
                        recent.pop(0)
                    if len(spoken) >= MAX_SPOKEN_CLAUSES:
                        log("orchestrator: hit clause cap, cutting off")
                        publish("looping", text=clause)
                        looping = True
                        break
                    first = first or time.time() - t0
                    mouth.say(clause)
                    spoken.append(clause)
                    publish("clause", text=clause, at=round(time.time() - t0, 2))

            # The classifier pinned a tool and the model answered anyway —
            # from its own weights or from its earlier replies in the history.
            # Run the lookup here instead of asking it again: the decision was
            # never the model's to make, and everything it said without the
            # data is a guess (held above, dropped below).
            if (not pending and isinstance(force_tool, str)
                    and not interrupt.is_set() and rnd < MAX_TOOL_ROUNDS
                    and not any(t["name"] == force_tool for t in tools_used)):
                fargs = fallback_args(force_tool, text, slug)
                if fargs is not None:
                    log(f"orchestrator: model skipped the pinned tool, "
                        f"calling {force_tool} directly")
                    publish("tool_forced", name=force_tool, arguments=fargs)
                    pending = [{"id": f"forced-{rnd}", "name": force_tool,
                                "args": json.dumps(fargs)}]
                    buf = ""

            if held:
                if pending:
                    # It answered and then looked it up; the answer was a guess.
                    log(f"orchestrator: dropped {len(held)} pre-tool clause(s)")
                    publish("preempted", clauses=len(held),
                            text=" ".join(held)[:200])
                else:
                    for cl in held:
                        first = first or time.time() - t0
                        mouth.say(cl)
                        spoken.append(cl)
                        publish("clause", text=cl, at=round(time.time() - t0, 2))
                held = []

            if not pending and promised and rnd < MAX_TOOL_ROUNDS:
                # It said it would look something up but never called anything.
                # Ask again, this time requiring a tool call.
                log("orchestrator: narration without a tool call, forcing one")
                force_tool = True
                buf = ""
                continue
            force_tool = False
            # A tool call just happened, so this round wasn't "creative" —
            # widen back to the full menu for any follow-up round.
            offer_tools = tools
            if not pending or interrupt.is_set() or looping:
                # Seen on this small model: real tool results come back, and
                # the very next round answers with nothing at all (finish:
                # stop, zero tokens). One retry with a direct nudge, rather
                # than reporting "no answer" when the data was right there.
                if (not pending and not interrupt.is_set() and not looping
                        and not spoken and not buf.strip() and not held
                        and tools_used and finish == "stop" and not empty_retry
                        and rnd < MAX_TOOL_ROUNDS):
                    log("orchestrator: empty reply after tool result, "
                        "retrying once")
                    empty_retry = True
                    msgs.append({"role": "user", "content":
                                 "Answer now, in one or two short spoken "
                                 "sentences, using the result above. Do not "
                                 "call another tool."})
                    continue
                break
            # Tools were requested. Nothing has been spoken yet, so run them and
            # ask again with the results appended to the conversation.
            # "content": None is required by the OpenAI shape for a tool-call
            # turn. Omitting it renders a malformed assistant turn in the chat
            # template, and the model's next reply goes off the rails.
            msgs.append({"role": "assistant", "content": None, "tool_calls": [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["name"], "arguments": c["args"]}}
                for c in pending]})
            for c in pending:
                try:
                    targs = json.loads(c["args"] or "{}")
                except json.JSONDecodeError:
                    targs = {}
                publish("state", state="tool")
                publish("tool_call", name=c["name"], arguments=targs,
                        round=rnd + 1, at=round(time.time() - t0, 1))
                log(f"orchestrator: tool {c['name']} {targs}")
                ts = time.time()
                res = tools_rpc({"op": "call", "id": c["id"],
                                 "name": c["name"], "arguments": targs})
                took = round(time.time() - ts, 2)
                if res is None:
                    res = {"ok": False,
                           "content": "the tools service is unreachable",
                           "meta": {}}
                tools_used.append({"name": c["name"], "arguments": targs,
                                   "ok": bool(res.get("ok")), "took": took,
                                   "meta": res.get("meta") or {},
                                   "chars": len(res.get("content") or "")})
                # The content too, not just its length: this is the evidence
                # the model then reads back, and the only way to tell a wrong
                # answer that was grounded from one the model invented.
                body = res.get("content") or ""
                publish("tool_result", name=c["name"], ok=bool(res.get("ok")),
                        took=took, meta=res.get("meta") or {},
                        chars=len(body),
                        content=body[:EVIDENCE_CHARS],
                        content_truncated=len(body) > EVIDENCE_CHARS)
                msgs.append({"role": "tool", "tool_call_id": c["id"],
                             "name": c["name"],
                             "content": res.get("content") or ""})
            # Not "thinking": the next thing it does is read back everything we
            # just fetched, which is the slow part and worth naming honestly.
            publish("state", state="digesting")
        except Exception as e:
            log("orchestrator: llm error:", e)
            publish("error", message=str(e))
            publish("state", state="idle")
            continue

        if buf.strip() and not interrupt.is_set():
            first = first or time.time() - t0
            mouth.say(buf.strip())
            spoken.append(buf.strip())
            publish("clause", text=buf.strip(), at=round(time.time() - t0, 2))

        reply = " ".join(spoken)
        if reply:
            history += [{"role": "user", "content": text},
                        {"role": "assistant", "content": reply}]
            # Trim here: history[-0:] is the whole list, so HISTORY_TURNS=0
            # (the benchmark's single-turn mode) would otherwise keep everything.
            history = history[-2 * HISTORY_TURNS:] if HISTORY_TURNS > 0 else []
            log(f"orchestrator: first clause at {first:.2f}s, "
                f"reply complete at {time.time() - t0:.2f}s")
            publish("done", first_clause=round(first, 2),
                    total=round(time.time() - t0, 2),
                    interrupted=interrupt.is_set(),
                    clauses=len(spoken), think_chars=think_chars,
                    reply=reply, finish=finish, tools=tools_used,
                    # Ground truth about sourcing, independent of what it said.
                    unverified=bool(CITES.search(reply) and not tools_used))
            if CITES.search(reply) and not tools_used:
                log("orchestrator: reply claims a source but no tool ran")
        elif not interrupt.is_set():
            # Never fail silently. The usual cause is the reasoning channel
            # consuming the whole token budget before reaching an answer.
            budget = live_int("VA_LLM_MAX_TOKENS", 200)
            why = (f"the model used all {budget} output tokens on its reasoning "
                   f"channel ({think_chars} chars) and never reached an answer — "
                   f"raise VA_LLM_MAX_TOKENS, lower the reasoning budget, or "
                   f"turn thinking off") if (finish == "length" and think_chars) \
                else f"the model returned no speakable text (finish: {finish})"
            log(f"orchestrator: empty reply — {why}")
            publish("empty", reason=why, finish=finish,
                    think_chars=think_chars,
                    total=round(time.time() - t0, 2))
        publish("state", state="idle")


if __name__ == "__main__":
    main()
