# agentic-edge

An on-device voice agent for a Raspberry Pi 5, running Gemma 4 (E2B/E4B QAT)
through [little-gemma](https://github.com/cortexist/little-gemma) — speech in,
tool-augmented reasoning, speech out — plus the benchmarking work that led to
those engine and model choices.

## Layout

- **[`voice-agent/`](voice-agent/)** — the running system: six independent
  systemd services (ASR, LLM, TTS, orchestrator, tools, web UI) that speak
  plain text/JSON protocols over Unix sockets, so any one engine can be
  swapped without touching the others. Organised by kind
  (`services/`, `web/`, `config/`, `systemd/`, `tests/`) with `deploy.sh`
  mapping that onto the Pi's flat `/opt/voice-agent` + `/etc/voice-agent`
  layout. See [`voice-agent/README.md`](voice-agent/README.md) for the
  architecture, service protocols, and the web UI's live pipeline inspector.
- **[`gemma4-pi5-benchmarks.md`](gemma4-pi5-benchmarks.md)** — comparison of
  little-gemma vs. llama.cpp vs. LiteRT-LM running Gemma 4 E2B/E4B on the Pi 5,
  covering throughput, response quality, and why the deployed configuration
  ended up where it did.
- **[`benchmark/`](benchmark/)** — the follow-on, repeatable version of that
  comparison: a stdlib-only harness that runs a fixed test-case suite against
  any of four architectures (llama.cpp, LiteRT-LM, little-gemma, this
  project's own modular pipeline) across devices, models, quantizations,
  CUDA on/off, MTP, and thinking mode, and aggregates the results into one
  comparison table. Clone the repo, edit a config, run — see
  [`benchmark/README.md`](benchmark/README.md).

## Hardware

Raspberry Pi 5 (8GB), running headless. No microphone or speaker attached —
the web UI's browser mic and TTS playback stand in for those.

## Status

Under active development; not hardened for exposure beyond a trusted LAN (the
web UI has no authentication).
