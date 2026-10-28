#!/usr/bin/env bash
# Stops only the voice-widget bridge (python ... bridge.py started from this repo's server/ dir).
cd "$(dirname "$0")/server"
PIDS="$(pgrep -f "python[0-9.]* bridge.py" | while read -r p; do [[ "$(readlink -f /proc/$p/cwd)" == "$PWD" ]] && echo "$p"; done)"
if [[ -z "$PIDS" ]]; then echo "Bridge not running."; exit 0; fi
kill $PIDS && echo "Stopped bridge (pid $PIDS)."
