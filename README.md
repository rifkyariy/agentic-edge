# Voice agent — modular services

Four independent systemd services. Each speaks one dumb text protocol, so any
one can be replaced without touching the others.

```
mic/wav ──► va-asr ──asr.sock──► va-orchestrator ──tts.sock──► va-tts ──► speaker/file
                                        │
                                   HTTP │ OpenAI /v1/chat/completions
                                        ▼
                                     va-llm
```

Config lives in **one file**: `/etc/voice-agent/config.env`. Code lives in
`/opt/voice-agent/`. Change a value, restart that one service.

This repo is organised by kind, not by how it lands on the Pi — every
systemd unit hardcodes a flat `/opt/voice-agent/*` or `/etc/voice-agent/*`
path, so `deploy.sh` is what maps one layout onto the other:

```
services/     the five Python services (asr, tts, tools, orchestrator, web)
web/          ui.html — the browser UI, no build step
config/       config.env (defaults) and system-prompt.txt
systemd/      the va-*.service unit files
tests/        node tests/test-readable.js — checks web/ui.html directly
deploy.sh     ./deploy.sh [target...]  — see the script header for targets
```

## Tools (web search)

`va-tools` executes what the model asks for. Two tools: `web_search` and
`fetch_page`. Backend is **DuckDuckGo HTML — no API key, no browser.** A headless
Chromium would starve the LLM on four shared cores, so pages are fetched over
HTTP and reduced to text. `VA_SEARCH_BACKEND=searx` + `VA_SEARX_URL` swaps it.

Verified working: *"Charlie Kirk, the conservative activist, died on September 10,
2025 … assassinated while speaking at Utah Valley University"* — a fact well past
the model's training cutoff, retrieved and attributed.

### Three things that had to be right, and were not at first

**Ground the date every turn.** Without it the model treats anything after its
cutoff as *the future* and refuses: "I cannot search for events on September
tenth, two thousand twenty-five." The orchestrator now appends today's date to
the system message and states that any date up to today is in the past.

**`"content": None` on the assistant tool-call turn.** The OpenAI shape requires
it. Omitting it renders a malformed assistant turn in the chat template, and the
next reply comes back incoherent — unrelated searches, nonsense answers.

**Narration is not action.** The model would say "I will search the web to find
…" as ordinary text and then never call anything, so nothing was looked up. Such
clauses are now matched, kept out of the speech stream, and the next round is
re-asked with `tool_choice: "required"`.

### Intent classification

Every turn is classified before the model sees it:

| intent | what happens |
|---|---|
| **live** | scores, news, rates, prices, weather, "latest/today/currently" → `tool_choice: "required"` |
| **creative** | poem, story, joke, translate, summarise, rewrite → **no tools offered at all** |
| **open** | everything else → tools offered, model decides |

It is a keyword rule, not another model call: an LLM classification round costs a
full prefill, 20–40s on this board. The UI states which branch a turn took, so a
misclassification is visible rather than silent. `creative` also keeps the tool
schema out of the prefill entirely.

**Pre-tool guesses are discarded.** On a `live` turn the model sometimes answers
first and calls the tool second — it once said "one hundred seventy nine point
seven" before looking up a rate that was actually 1,797. Clauses produced before
a required tool call are held, and dropped if the call arrives (`dropped 3
pre-tool clause(s)`), so a guess never reaches the speaker.

### Exchange rates: `currency_rate`

Yahoo's chart endpoint, no key, arbitrary pairs — ECB-based sources (Frankfurter)
omit TWD entirely, which rules them out here. One call returns the current rate
and a daily series, so the card draws a real chart rather than a decoration.

The card shows the converted amount in large type, the change over the window
coloured up/down, the rate line, a sparkline, and high/low with arrows.

**Do not use `meta.regularMarketPrice`** — Yahoo rounds it to 4 decimals, which
turns IDR/USD 0.0000567 into 0.0001 and made 1,000,000 IDR come out as $100
instead of $57. The last point of the series carries full precision.

### Football results: `match_result`

Search snippets **do not contain scores** — every result page renders them in
JS. Asked for "latest score of AS Roma vs Torino", the model had the fixture date
from a snippet and invented "Roma zero, Torino one". The real result was Torino
0–2 Roma; it got the scoreline and the teams wrong.

So scores get their own tool. It finds the Sofascore match page and reads the
`__NEXT_DATA__` payload the page embeds, which carries real structured data:
teams and IDs, full-time and half-time score, status, goal scorers with minutes,
cards, and penalty shootouts. Crests come from `img.sofascore.com`
(`api.sofascore.app` returns 403 for images — wrong host).

The UI renders a card from **that payload only**, so nothing on it can be
something the model made up, and rows with no data are simply absent rather than
guessed. The spoken reply now matches: "The score was two to zero, Roma won."

The card shows the competition logo, round, status, kickoff time, both crests,
the scoreline, half-time, venue and city, and goal scorers on its face.
**Bookings are not on the face** — a count sits bottom-right next to the source
link and opens an accordion. Penalty shootouts, when present, list beside goals.

Two traps worth remembering. Logos: `img.sofascore.com` serves crests and
competition badges (`/unique-tournament/{id}/image`); `api.sofascore.app` 403s
them and `/tournament/{id}/image` is a 404. And any element toggled with
`hidden` needs an explicit `[hidden] { display: none }` rule, because a class
rule setting `display` out-specifies the UA stylesheet — the same bug that once
made the model-switch modal impossible to close.

Filler words break the page lookup: "sofascore Torino **against** Roma" returns a
preview article, while "sofascore Torino Roma" returns the match. The tool strips
vs/against/score/result/latest and tries several query forms before giving up.

This is scraping, not an API. If they change the markup the tool returns "no
readable match data" and the model falls back to `web_search` — it degrades to
no answer, never to a fabricated one.

**History poisons itself.** Once the model had stated the wrong score, later
turns repeated it confidently without calling any tool. The system prompt now
says a score always requires `match_result` and that a score stated earlier in
the conversation must not be trusted.

### Repetition loops

Greedy decoding (`temperature: 0`) with no penalty degenerates: one turn ended
"I am here for you. I hope you are well. I am ready to help you further…" until
the token budget ran out. llama.cpp leaves `repeat_penalty` **off** by default,
and little-gemma's own docs record 8,098 tokens of the same sentence from this.

Three guards: `repeat_penalty 1.12` + `repeat_last_n 256` +
`presence_penalty 0.4` on every request; the system prompt forbids sign-offs and
offers of further help, which is the filler these loops feed on; and the
orchestrator cuts the turn off after a clause repeats twice, publishing
`looping` so the UI says so rather than reading it aloud twenty times.

### Knowing what "latest" means

The tool resolves "latest" against the clock, not the model's guess: it fetches
every candidate match page, keeps those already kicked off with a score, and
takes the most recent. It reports `days_ago` against today and sets
`maybe_not_latest` beyond 4 days, which the card shows as "most recent match
that could be verified — a newer one may exist".

**This is best-effort, not authoritative, and it is the weakest part of the
build.** The candidate set comes from DuckDuckGo, whose index does not reliably
rank a club's newest fixture: "real madrid latest result" returned the 6-day-old
Inter match and the 2-day-old Rayo Vallecano match on two identical calls minutes
apart. Widening to five query variants found more fixtures but tripped DDG's rate
limit, after which every query — including "python programming" — came back as an
HTTP 202 challenge page.

Everything else was tried and blocked: Sofascore's own search and API (403),
ESPN's public API (403), team pages carry no fixture list, match pages carry no
schedule. **Correct "latest result for team X" needs a fixture feed**, e.g.
`football-data.org`'s free tier (`/teams/{id}/matches?status=FINISHED&limit=1`).
That needs a key, which the current design deliberately avoids. Swapping it in
would touch only the tool; the card, classifier and UI stay as they are.

### Cost

Every tool round re-prefills the whole growing context, which is the expensive
part here. A search turn measured ~26s to first spoken word on E4B versus ~2s
without tools. Results are deliberately capped (`VA_SEARCH_RESULTS`,
`VA_SEARCH_SNIPPET`, `VA_FETCH_CHARS`) because each fetched character is prefill
the model has to read back. `VA_MAX_TOOL_ROUNDS` bounds the loop; the final round
is offered no tools so a turn always ends in an answer.

### Safety

Search results and page text are **untrusted input to a language model**. They
arrive wrapped in an envelope marking them as data, and the system prompt tells
the model never to follow instructions found inside them. `fetch_page` refuses
non-http(s) schemes and any host resolving to a private, loopback, link-local or
reserved address, so a crafted result cannot aim the agent at `192.168.x` or a
metadata endpoint. Verified: `192.168.1.1`, `localhost` and `file://` all refused,
`https://example.com` allowed. The blast radius stays small because a reply only
ever reaches a speaker — never another tool, never a shell.

**E2B is weak at this.** It reliably searched but then described the results
instead of extracting the answer ("the search results point to the Raspberry Pi
documentation"). E4B extracts and attributes properly. If you want the agent to
answer from the web, use E4B and accept the latency.

## The three contracts

These are the seams. Honour the contract and any implementation drops in.

**1. ASR → orchestrator** — Unix socket `$VA_ASR_SOCK`, ASR listens.
Newline-delimited UTF-8. A plain line is a finalised utterance; a line starting
with `~` is a partial and is ignored by the orchestrator. Bracketed non-speech
tags (`[door slams]`) are passed through deliberately — the model should know
what it heard, which is the whole reason for using whisper over Gemma's own
audio tower (that one is ASR-only and hears nothing but words).

**2. Orchestrator → LLM** — HTTP POST `$VA_LLM_URL`, OpenAI
`/v1/chat/completions` with `stream: true`. Both llama.cpp and LiteRT-LM speak
this, so switching engines is a URL change. `reasoning_content` deltas are
dropped; only `content` is spoken.

**3. Orchestrator → TTS** — Unix socket `$VA_TTS_SOCK`, TTS listens.
Newline-delimited UTF-8. A plain line is a clause to speak, queued in order.
`!clear` stops immediately and drops queued audio — that is barge-in.

## Web UI (`va-web`)

`http://<pi>:8090` — live transcript, typed injection, barge-in, service status.
Lucide icons from CDN, so the browser needs internet; vendor `lucide.min.js`
locally if you want it fully offline.

| endpoint | does |
|---|---|
| `GET /` | the page |
| `GET /events` | SSE stream of orchestrator events + ASR bus |
| `POST /say` | `{"text": "..."}` — inject a typed turn |
| `POST /audio` | raw audio body from the browser mic → ffmpeg → whisper → bus |
| `POST /clear` | barge-in |
| `GET /status` | per-service state; `va-llm` reports `loading` while weights load |
| `GET /models` | `.gguf` files in `$VA_MODELS_DIR` plus the current one |
| `POST /model` | `{"path": "..."}` — switch model and restart `va-llm` |
| `GET /config` | effective config for the inspector |
| `GET /audio/<name>` | a spooled clip — `in-*.wav` is input, the rest is speech out |

### Where state lives

| file | holds | overwritten by a deploy? |
|---|---|---|
| `/etc/voice-agent/config.env` | deployed defaults | **yes** |
| `/etc/voice-agent/runtime.env` | choices made in the UI | no |

`va-llm.service` loads both, runtime second, so the UI wins. Delete
`runtime.env` and the deployed defaults take over again. This split exists
because the model choice used to live in `config.env` and was silently reverted
every time the code was redeployed.

The orchestrator re-reads the token budget from these files **every turn**, so
changing it needs no restart. Browser-local preferences (mute) sit in
`localStorage`.

### Model switching

The header dropdown lists every `.gguf` found in `$VA_MODELS_DIR`, labelled with
family, quantisation and size. Choosing one opens a confirmation modal showing
the from/to models, the measured decode and prefill rate for the target, and how
long the load will take (~8s per GiB off the SD card). Confirming writes
`runtime.env` and restarts `va-llm`; Escape, Cancel or clicking outside reverts
the dropdown.

Two things make this safe-ish and one thing does not:

- The target path must be one `GET /models` listed, so an arbitrary path cannot
  be injected.
- A turn sent while the new model is still loading is **queued, not lost** — the
  orchestrator retries on 503 for up to `VA_LLM_WAIT_TRIES × VA_LLM_WAIT_SLEEP`
  (default 2 minutes), which is ample for E4B off an SD card.
- **But this endpoint restarts a system service and has no authentication.**
  With `VA_WEB_HOST=0.0.0.0`, anyone on your network can do it. If that matters,
  bind `127.0.0.1` and use the SSH tunnel.

### Reply footer: replay and sources

A reply's footer carries `replay · 7.3s` and, when the answer came from a
search, a `4 sources` label beside it. Clicking the label expands the pages that
were actually read, by title, each a link. One entry per URL, deduplicated.

A reply that used no tools gets **no** sources label — absence is the signal.
And if the model claims a source when nothing was fetched, a `no search ran`
warning chip appears instead: the orchestrator knows whether a tool ran, so the
UI asserts that independently of what the model said.

Sources are collected during the turn but attached when the reply bubble is
created, which may be after the search: attaching on `tool_result` put them on
the *previous* reply, because that is what `lastBotTurn` still pointed at.

Clause boundaries are speech flush points, not line breaks — the text is joined
into flowing prose with a real space in JS (a CSS `content: ' '` collapses at an
inline boundary and produced "Nvidia,according").

## Reply playback

Each agent reply carries its own speaker control inside the bubble: `replay · 2.5s`
when idle, an animated equaliser reading `speaking` while it plays, and clicking
it again stops. There is no separate "speaking" bubble — the control belongs to
the reply it plays. Clips are prefetched as blobs on arrival, and `play()` is
called with no `await` in front of it so a click never falls outside its own
activation window.

### Status balloon

While a turn is in flight the transcript shows a dashed agent balloon naming the
current phase, so a long silence never reads as a hang:

| phase | shown when |
|---|---|
| listening | browser audio is being transcribed |
| loading the model | `va-llm` restarted and is reading weights; turn is queued |
| thinking | prompt sent, waiting for the first token |
| reasoning | the reasoning channel is running — **with a live tail of the text** |
| composing the reply | content tokens started arriving |
| speaking | a clip is playing, with clip N of M |

The reasoning phase is the one that needed this most. With thinking on, a simple
percentage question spent 898 characters and 41s reasoning before saying anything,
and the orchestrator publishes ~8 progress events per second (`chars`, elapsed
`at`, and a 180-char `tail`) so you can watch it work out the answer rather than
stare at an idle screen.

### Pipeline inspector

The right-hand panel breaks the last turn into ten steps, each showing measured
values rather than estimates: input audio (with a player for the exact 16 kHz wav
whisper received), transcription time and realtime factor, prompt assembly, the
verbatim JSON request body, the loaded model, speculative decoding, thinking,
generation timings and token counts, per-clause synthesis with "audio ready"
deltas, and players for every generated clip.

Steps 6 and 7 are **switchable from the panel** (each restarts `va-llm`), and both
defaults are measured on this exact stack, same prompt, both warm:

| MTP | first clause | complete |
|---|---:|---:|
| off | **1.65 s** | **5.28 s** |
| on | 5.46 s | 8.78 s |

MTP is 1.7× slower here *at 100% draft acceptance* — llama.cpp reported
`draft acceptance = 1.00000 (24/24), mean len 4.00`. Acceptance was never the
problem: verifying a block of 4 on four saturated cores costs about four single
tokens, and generating in blocks also delays the first token. On a GPU the same
head wins 1.4–2.4× because the verify pass rides on idle tensor cores.

| thinking | first clause | "7 pens at \$3, paid \$50" |
|---|---:|---|
| off | **1.65 s** | 25 — wrong |
| on | 7.17 s | **29 — correct** |

So thinking genuinely buys accuracy (it fixed E2B's arithmetic 7/10 → 10/10 in the
batch test) and genuinely costs ~4× the time to first spoken word. Off is the
right default for *speech*; turn it on for anything where being wrong matters more
than waiting. Full numbers in `gemma4-pi5-benchmarks.md`.

`VA_LLM_REASONING` and `VA_LLM_SPEC_ARGS` in config.env hold the state. The MTP
draft head is selected to match the loaded model (`mtp-gemma-4-{E2B,E4B,12B}-it.gguf`)
and switching models clears a now-mismatched head automatically.

It is an observer plus an injector — it consumes the same contracts as
everything else. Stop it and the agent runs exactly as before.

### Browser microphone

The Pi has no capture device, so the **browser** is the microphone: click
Record, speak, click again, and the clip is uploaded, converted by ffmpeg,
transcribed by whisper, and injected on the utterance bus. Push-to-talk, not
streaming — good enough without a mic, and it does not pretend to be
prefill-under-speech.

`getUserMedia` only works in a **secure context**, so plain `http://` on a LAN
IP will refuse (the UI detects this and says so). Two ways round it:

```bash
# simplest: tunnel, so the origin is localhost and counts as secure
ssh -L 8090:localhost:8090 MITLAB-EDGE
# then open http://localhost:8090
```

```bash
# or serve HTTPS with a self-signed cert and accept the warning once
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout /opt/voice-agent/key.pem -out /opt/voice-agent/cert.pem -subj "/CN=$(hostname)"
# then set VA_WEB_CERT / VA_WEB_KEY in config.env and restart va-web
```

**There is no authentication.** `VA_WEB_HOST=0.0.0.0` means anyone on your
network can talk to the agent and hear it. Set `127.0.0.1` and use the tunnel
if that is not what you want.

## The fourth contract: events

`$VA_EVENT_SOCK` — the orchestrator publishes JSON lines; observers subscribe.
Unset it and the orchestrator stops publishing, changing nothing else.

```json
{"type":"user","text":"..."}                      a turn it acted on
{"type":"clause","text":"...","at":2.74}          a clause sent to TTS
{"type":"done","first_clause":2.74,"total":4.0}   turn finished
{"type":"state","state":"thinking|idle"}          status
{"type":"error","message":"..."}
```

## Swapping a component

| want to change | do this |
|---|---|
| LLM engine (llama.cpp ↔ LiteRT-LM) | edit `VA_LLM_URL`, swap `ExecStart` in `va-llm.service` |
| model (E2B ↔ E4B) | edit `VA_LLM_MODEL_PATH`, restart `va-llm` |
| ASR engine | point `va-asr.service` `ExecStart` at your script; emit contract 1 |
| TTS engine | point `va-tts.service` `ExecStart` at your script; consume contract 3 |
| audio input | `VA_ASR_AUDIO_IN=alsa:plughw:1,0` or `file:/path.wav` |
| audio output | `VA_TTS_AUDIO_OUT=alsa:default` or `file:/path.raw` |
| voice | `VA_TTS_VOICE=/path/other.onnx` |
| reply style / clause density | edit `/opt/voice-agent/system-prompt.txt` |
| UI look | edit `/opt/voice-agent/ui.html` — plain HTML, no build step |

Nothing above requires editing more than one unit plus config.

## Measured on this Pi 5 (8GB, 4 cores)

| stage | measurement |
|---|---|
| whisper base.en, 4 threads | 2.1s for 3.9s audio (1.8× realtime) |
| LLM first clause, cold | 5.02s (system prompt not yet cached) |
| LLM first clause, warm | **2.23s** |
| full reply, warm | 3.19s |
| piper | resident; 60MB voice loaded once, not per clause |

Cold vs warm is entirely the system prompt prefill. llama.cpp KV-caches it
after the first turn, which is why turn two is 2.2× faster. Keep the system
prompt short — every token in it is paid for on the cold turn.

## Known gaps

- **No microphone attached.** `arecord -l` lists no capture device, so
  `VA_ASR_AUDIO_IN` is a wav file for now. Add a USB mic or reSpeaker array,
  then set `alsa:...`.
- **ASR is chunked, not truly streaming.** `asr_service.py` transcribes fixed
  `VA_ASR_CHUNK_SEC` windows. Real prefill-under-speech needs
  whisper_streaming's LocalAgreement-2 commit semantics, which would replace
  only this one file. Until then the ASR latency is serial, not hidden.
- **`VA_ASR_THREADS=1` will not keep up live.** base.en needs ~2 threads to beat
  realtime on this board. Either raise it (and drop `VA_LLM_THREADS`) or switch
  to `ggml-tiny.en.bin`. There are only 4 cores; ASR, LLM and TTS all want them,
  which is the one real disadvantage versus the Jetson the paper targets, where
  the GPU owned the LLM and left the CPU free.
- **`va-*` services are not enabled at boot** — start them by hand. Note
  `little-gemma.service` *is* enabled and will claim memory on reboot; stop it
  before starting `va-llm`.
- **Don't `rm` the file sink while TTS is running.** The sink process keeps the
  deleted inode open and writes vanish into it. Truncate instead
  (`: > /tmp/va-tts.raw`) or restart `va-tts`. Irrelevant in `alsa:` mode.

## Operating

```bash
sudo systemctl start  va-llm va-tts va-asr va-orchestrator
sudo systemctl stop   va-orchestrator va-asr va-tts va-llm
sudo journalctl -u va-orchestrator -f
```

Pushing a code change:

```bash
./deploy.sh                 # every service + the UI + the system prompt
./deploy.sh orchestrator ui  # just these, restarted after copying
./deploy.sh units            # systemd/*.service -> /etc/systemd/system/, daemon-reload
./deploy.sh config           # config/config.env -> /etc/voice-agent/, diff-reviewed first
```

Talk to a single service without the rest, to test it in isolation:

```bash
# make the mouth speak, no LLM involved
printf 'Hello, this is a test.\n' | nc -U /run/voice-agent/tts.sock
# watch what the ears hear
nc -U /run/voice-agent/asr.sock
```
