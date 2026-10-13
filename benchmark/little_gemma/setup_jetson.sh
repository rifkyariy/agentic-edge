#!/usr/bin/env bash
# Build little-gemma's CUDA int8 runner on the Jetson Orin Nano, pinned and
# patched, so the S3 rows are reproducible from this repo alone.
#
#   ./little_gemma/setup_jetson.sh            # clone/checkout, patch, build
#
# Result: ~/build/little-gemma/build/run-cuda-i8 (sm_87), plus BUILD_INFO next
# to it recording the upstream commit and the patch hash.
#
# The patch (agentic-edge.patch) changes only the socket server in run.c, to
# drive it with the same MMLU-Pro task config as the llama.cpp rows:
#   * SERVE_GEN 1024 -> 2048, the answer budget both llama.cpp rows use
#     (AGENTS.md rule 5; a 1024 cap would truncate long chains of thought).
#   * -raw: the client sends the fully rendered chat prompt. Upstream wraps
#     every line as a fresh user turn, which cannot express lm-eval's
#     system + 5 few-shot pairs + question; lg_openai_shim.py renders it.
#   * under -raw, the prompt is tokenized once, whole (upstream's dictation
#     path tokenizes space-split pieces as they arrive), and the context
#     budget is counted in tokens rather than characters — an 11k-char
#     MMLU-Pro prompt is ~2.4k tokens but was refused as "context full".
# Nothing in the forward pass, sampling, tokenizer or kernels is touched.
#
#   AE=1 ./little_gemma/setup_jetson.sh       # the proposed engine (S9)
#
# builds the same pin with ae.patch on top, in its own tree
# (~/build/little-gemma-ae), so the S3 binary is never rebuilt under it.
# ae.patch adds three switches, all off by default and all greedy-exact:
# -ngram (prompt-lookup drafts through the MTP verify), -reuse (shared-prefix
# KV snapshots across requests) and -block N (verify width on the command
# line). The kernels are untouched; the prefix-save buffers are allocated once.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PIN="${LG_COMMIT:-aee759d}"           # cortexist/little-gemma, 2026-09 main
SRC=~/build/little-gemma
PATCHES="agentic-edge.patch"
[ "${AE:-0}" = 1 ] && { SRC=~/build/little-gemma-ae; PATCHES="agentic-edge.patch ae.patch"; }
CMAKE=~/build/cmake/bin/cmake         # no cmake on PATH, no sudo: the one llama.cpp used
export PATH=/usr/local/cuda/bin:$PATH

[ -d "$SRC/.git" ] || git clone https://github.com/cortexist/little-gemma.git "$SRC"
cd "$SRC"
git fetch -q origin
git checkout -q -- .                  # drop a previous application of the patches
git checkout -q "$PIN"
for p in $PATCHES; do git apply "$HERE/$p"; done

"$CMAKE" -S . -B build -DCMAKE_BUILD_TYPE=Release -DLG_CUDA_ARCH=87
"$CMAKE" --build build --config Release --target run-cuda-i8 -j"$(nproc)"

{
  echo "upstream: https://github.com/cortexist/little-gemma @ $(git rev-parse HEAD)"
  for p in $PATCHES; do echo "patch:    $p sha256 $(sha256sum "$HERE/$p" | cut -c1-16)"; done
  echo "arch:     sm_87, $(nvcc --version | tail -1)"
  echo "built:    $(date -Is)"
} > build/BUILD_INFO
cat build/BUILD_INFO
ls -la build/run-cuda-i8
