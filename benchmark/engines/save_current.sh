#!/usr/bin/env bash
# Freeze the llama.cpp build this board's S1/S2 rows were served by, so a
# rerun never depends on ~/llama.cpp staying untouched.
#
#   ./engines/save_current.sh      # on the board; idempotent
#
# Writes <engines>/llama.cpp-<sha>/ with the built binaries, a
# source tarball of that exact commit, and BUILD_INFO (commit, cmake flags).
# The deployed build itself is not modified.
set -euo pipefail
# The Jetson's ~/research is an SSD that refuses symlinks, and llama.cpp's
# shared libraries are symlinks — so its engines live on the eMMC instead.
if [ -d ~/Research ]; then E=~/Research/engines; SRC=~/llama.cpp
else E=~/build/engines; SRC=~/build/llama.cpp; fi
cd "$SRC"
SHA=$(git rev-parse --short=7 HEAD)
git diff --quiet HEAD || { echo "refusing: $SRC has local changes" >&2; exit 1; }
DST=$E/llama.cpp-$SHA
[ -f "$DST/BUILD_INFO" ] && { cat "$DST/BUILD_INFO"; exit 0; }
mkdir -p "$DST"
cp -a build/bin "$DST/bin"
git archive --format=tar.gz --prefix="llama.cpp-$SHA/" HEAD > "$DST/src.tar.gz"
{
  echo "upstream: $(git remote get-url origin) @ $(git rev-parse HEAD)"
  echo "host:     $(hostname), $(uname -m)"
  grep -E '^(CMAKE_BUILD_TYPE|GGML_CUDA|GGML_NATIVE|CMAKE_CUDA_ARCHITECTURES):' build/CMakeCache.txt
  echo "saved:    $(date -Is)"
  echo "sha256:   $(sha256sum "$DST/bin/llama-server" | cut -c1-16) llama-server"
} > "$DST/BUILD_INFO"
cat "$DST/BUILD_INFO"
