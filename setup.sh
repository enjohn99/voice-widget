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
elif [[ "$(uname)" == "Linux" ]]; then
  # espeak-ng is GPL-3.0: installed by YOU from the distro, never bundled. We only detect it (no sudo).
  if command -v espeak-ng >/dev/null 2>&1 || ldconfig -p 2>/dev/null | grep -q libespeak-ng; then
    echo "==> espeak-ng found"
  else
    echo "!! espeak-ng not found (Kokoro needs it). Install with ONE of:"
    echo "     sudo apt install espeak-ng        # Debian/Ubuntu"
    echo "     sudo dnf install espeak-ng        # Fedora/RHEL"
    echo "     sudo pacman -S espeak-ng          # Arch"
    echo "   Continuing; TTS will fail until it is installed."
  fi
fi

# 2. python 3.10-3.12 (kokoro requires <3.13)
PY=""
for c in python3.12 python3.11 python3.10; do command -v "$c" >/dev/null 2>&1 && { PY="$(command -v "$c")"; break; }; done
if [[ -z "$PY" ]]; then
  if [[ "$(uname)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
    brew install python@3.12; PY="$(brew --prefix)/bin/python3.12"
  else
    if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,13) else 1)'; then
      echo "!! Found $(python3 --version), but Kokoro requires Python <3.13. Install 3.12 alongside it:"
    else
      echo "!! Need Python 3.10-3.12 (Kokoro requires <3.13). Install one:"
    fi
    echo "     sudo apt install python3.12 python3.12-venv   # Ubuntu (deadsnakes PPA on older releases)"
    echo "     sudo dnf install python3.12                   # Fedora"
    echo "     pyenv install 3.12 && pyenv local 3.12        # any distro"
    echo "   then re-run ./setup.sh"; exit 1
  fi
fi
echo "==> using $($PY --version) at $PY"

# 3. venv + deps (idempotent)
[[ -d .venv ]] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
# Linux: install the CPU torch wheel first, otherwise pip pulls the multi-GB CUDA build.
# (NVIDIA users: pip install torch --index-url https://download.pytorch.org/whl/cu124)
if [[ "$(uname)" == "Linux" ]]; then
  pip install torch --index-url https://download.pytorch.org/whl/cpu
fi
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
echo "   Then start:  ./run.command (mac) | ./run-linux.sh (Linux) | ./server/run.sh (foreground)"
