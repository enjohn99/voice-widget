#!/usr/bin/env bash
# One-command install for macOS (Apple Silicon focus; the bridge/widget are cross-platform, the mlx STT path is Mac-only).
# Idempotent: safe to re-run. Creates a venv, installs deps, copies config. Model weights are fetched separately.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> voice-widget setup"

# 1. system deps (macOS/Homebrew). Kokoro needs espeak-ng (GPL-3.0, installed as a SEPARATE system binary).
if [[ "$(uname)" == "Darwin" ]]; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew not found. Install it from https://brew.sh then re-run."; exit 1
  fi
  for pkg in espeak-ng portaudio; do
    brew list "$pkg" >/dev/null 2>&1 || { echo "   brew install $pkg"; brew install "$pkg"; }
  done
fi

# 2. python 3.10-3.12 (kokoro requires <3.13)
PY=""
for c in python3.12 python3.11 python3.10; do command -v "$c" >/dev/null 2>&1 && { PY="$(command -v "$c")"; break; }; done
if [[ -z "$PY" ]]; then
  if [[ "$(uname)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
    brew install python@3.12; PY="$(brew --prefix)/bin/python3.12"
  else
    echo "Need Python 3.10-3.12 (kokoro supports <3.13). Install it and re-run."; exit 1
  fi
fi
echo "==> using $($PY --version) at $PY"

# 3. venv + deps (idempotent)
[[ -d .venv ]] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
pip install -r server/requirements.txt
pip install huggingface_hub   # setup-time only; runtime stays offline (HF_HUB_OFFLINE=1)

# 4. config
[[ -f server/config.json ]] || cp server/config.example.json server/config.json
[[ -f server/.env ]] || cp server/.env.example server/.env

echo ""
echo "==> setup complete."
echo "   Next: fetch models (downloads weights, not bundled in the repo):"
echo "     source .venv/bin/activate"
echo "     python server/fetch_models.py --kokoro --voice af_heart"
echo "     python server/fetch_models.py --stt-browser whisper-base-onnx"
echo "   Then start:  ./run.command   (or: ./server/run.sh)"
