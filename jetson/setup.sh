#!/usr/bin/env bash
# One-time dependencies for the voice agent on the Jetson Orin Nano. Run it ON
# the Jetson, as the user the agent runs as. No sudo anywhere: the Jetson has
# no passwordless sudo, so everything lands in $HOME and nothing touches apt.
#
#   whisper.cpp  ~/build/whisper.cpp, CUDA build (sm_87), pinned tag
#   piper        ~/voice/venv (uv-managed Python 3.11 — piper-tts 1.2.0 has
#                no cp312 wheels for piper-phonemize on aarch64)
#   ffmpeg       a static binary from imageio-ffmpeg, linked to ~/voice/bin
#                (the board has none, and the web UI's mic upload needs one)
#   models       whisper base.en + piper en_US-amy-medium, same as the Pi
#
# Re-running is safe: every step skips what is already there.
set -euo pipefail

WHISPER_TAG=v1.9.5
PIPER_VERSION=1.2.0
CMAKE=${CMAKE:-$HOME/build/cmake/bin/cmake}   # the one llama.cpp was built with
UV=${UV:-$HOME/.local/bin/uv}
VOICE=$HOME/voice
export PATH=/usr/local/cuda/bin:$PATH
# The piper-phonemize wheel timed out at uv's default 30s on the lab network.
export UV_HTTP_TIMEOUT=${UV_HTTP_TIMEOUT:-300}

mkdir -p "$HOME/build" "$VOICE/bin" "$VOICE/models/whisper" "$VOICE/models/piper"

echo "==> whisper.cpp $WHISPER_TAG"
if [ ! -x "$HOME/build/whisper.cpp/build/bin/whisper-cli" ]; then
  [ -d "$HOME/build/whisper.cpp" ] || \
    git clone --depth 1 --branch "$WHISPER_TAG" https://github.com/ggml-org/whisper.cpp "$HOME/build/whisper.cpp"
  cd "$HOME/build/whisper.cpp"
  "$CMAKE" -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=87 -DCMAKE_BUILD_TYPE=Release
  "$CMAKE" --build build -j"$(nproc)" --target whisper-cli
fi

echo "==> piper-tts $PIPER_VERSION"
if [ ! -x "$VOICE/venv/bin/piper" ]; then
  [ -x "$VOICE/venv/bin/python" ] || "$UV" venv --python 3.11 "$VOICE/venv"
  "$UV" pip install --python "$VOICE/venv/bin/python" "piper-tts==$PIPER_VERSION" imageio-ffmpeg
fi

echo "==> ffmpeg"
if [ ! -x "$VOICE/bin/ffmpeg" ]; then
  ln -sf "$("$VOICE/venv/bin/python" -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')" \
    "$VOICE/bin/ffmpeg"
fi

echo "==> models"
fetch() {  # url dest
  [ -s "$2" ] && return
  curl -fL --retry 3 -o "$2.part" "$1"
  mv "$2.part" "$2"
}
fetch https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin \
      "$VOICE/models/whisper/ggml-base.en.bin"
P=https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium
fetch "$P/en_US-amy-medium.onnx"      "$VOICE/models/piper/en_US-amy-medium.onnx"
fetch "$P/en_US-amy-medium.onnx.json" "$VOICE/models/piper/en_US-amy-medium.onnx.json"

# va-asr needs a source. No mic is attached and the browser mic goes through
# va-web, so give it one second of silence: whisper hears [BLANK_AUDIO], which
# va-asr drops, instead of replaying a sample utterance on every start.
mkdir -p "$VOICE/samples"
[ -s "$VOICE/samples/silence.wav" ] || sox -n -r 16000 -c 1 -b 16 "$VOICE/samples/silence.wav" trim 0 1

echo "==> check"
"$HOME/build/whisper.cpp/build/bin/whisper-cli" --help >/dev/null 2>&1 && echo "whisper-cli ok"
echo "hello from the jetson" | "$VOICE/venv/bin/piper" -m "$VOICE/models/piper/en_US-amy-medium.onnx" \
  --output_file /tmp/va-piper-check.wav 2>/dev/null && echo "piper ok"
"$VOICE/bin/ffmpeg" -version | head -1
