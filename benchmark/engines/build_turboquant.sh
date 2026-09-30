#!/usr/bin/env bash
# Build the TurboQuant KV-cache fork of llama.cpp (S8) beside the deployed
# build, pinned, never over it.
#
#   ./engines/build_turboquant.sh
#
# Result: <engines>/llama.cpp-turboquant-<sha>/build/bin/llama-server
# CPU on the Pi, CUDA sm_87 on the Jetson — the same flags each board's
# baseline build used. Adds KV types turbo2/turbo3/turbo4 (-ctk/-ctv).
set -euo pipefail
PIN="${TQ_COMMIT:-bcb85fc3ae85efa0f5f392c6c880dfc524923860}"   # TheTom/llama-cpp-turboquant, feature/turboquant-kv-cache, 2026-09-28
# ~/build/engines on the Jetson: its ~/research SSD refuses symlinks.
if [ -d ~/Research ]; then E=~/Research/engines; CMAKE=cmake; CUDA=OFF
else E=~/build/engines; CMAKE=~/build/cmake/bin/cmake; CUDA=ON; export PATH=/usr/local/cuda/bin:$PATH; fi
SRC=$E/llama.cpp-turboquant-${PIN:0:7}
[ -d "$SRC/.git" ] || git clone -q https://github.com/TheTom/llama-cpp-turboquant.git "$SRC"
cd "$SRC"
git fetch -q origin "$PIN" 2>/dev/null || true
git checkout -q "$PIN"
ARGS=(-DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DGGML_CUDA=$CUDA)
[ "$CUDA" = ON ] && ARGS+=(-DCMAKE_CUDA_ARCHITECTURES=87)
"$CMAKE" -S . -B build "${ARGS[@]}" >/dev/null
"$CMAKE" --build build --config Release --target llama-server llama-cli -j"$(nproc)"
{
  echo "upstream: https://github.com/TheTom/llama-cpp-turboquant @ $(git rev-parse HEAD)"
  echo "host:     $(hostname), $(uname -m), cuda=$CUDA"
  echo "built:    $(date -Is)"
} > build/BUILD_INFO
cat build/BUILD_INFO
ls -la build/bin/llama-server
