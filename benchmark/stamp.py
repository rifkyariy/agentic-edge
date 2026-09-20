#!/usr/bin/env python3
"""Prefix stdin lines with a journal-style timestamp.

    llama-server ... 2>&1 | python3 stamp.py > server.log

The Pi reads llama-server's per-request timings out of systemd's journal, which
stamps every line. The Jetson runs the server directly, so this reproduces the
same shape and parse_llama_log.py --file can read either source.
"""
import sys, time

host = __import__("os").uname().nodename
for line in sys.stdin:
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {host} llama-server[0]: {line}",
          end="", flush=True)
