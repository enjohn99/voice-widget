#!/usr/bin/env bash
# Linux launcher (equivalent of run.command / run.bat): starts the bridge hidden in the background,
# waits for /health, then opens the widget in the default browser (or prints the URL).
set -u
cd "$(dirname "$0")"
[[ -f server/config.json ]] || cp server/config.example.json server/config.json
PY=".venv/bin/python"; [[ -x "$PY" ]] || PY="$(command -v python3)"
PORT="$("$PY" -c 'import json;print(json.load(open("server/config.json")).get("server",{}).get("port",8730))' 2>/dev/null || echo 8730)"
PORT="${BRIDGE_PORT:-$PORT}"
URL="http://127.0.0.1:${PORT}/"
LOG=/tmp/voice-widget.log
if curl -fs "${URL}health" >/dev/null 2>&1; then
  echo "Bridge already running on port ${PORT}."
else
  # bridge.py loads server/.env itself
  (cd server && nohup "../$PY" bridge.py >"$LOG" 2>&1 &)
  for _ in $(seq 1 60); do curl -fs "${URL}health" >/dev/null 2>&1 && break; sleep 0.3; done
  curl -fs "${URL}health" >/dev/null 2>&1 || { echo "Bridge did not start; see $LOG"; tail -n 20 "$LOG"; exit 1; }
fi
if command -v xdg-open >/dev/null 2>&1 && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
  xdg-open "$URL" >/dev/null 2>&1 &
  echo "Opened $URL  (log: $LOG; stop with ./stop-linux.sh)"
else
  echo "Open this in your browser: $URL  (xdg-open/display not available; log: $LOG; stop with ./stop-linux.sh)"
fi
