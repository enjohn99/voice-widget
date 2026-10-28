#!/usr/bin/env bash
# Double-clickable launcher for macOS (Finder). Starts the bridge and opens the widget in the default browser.
# Basic use = double-click this file, grant mic permission, pick an agent, talk. No Terminal needed.
cd "$(dirname "$0")"
PORT="$(python3 - <<'PYEOF' 2>/dev/null || echo 8730
import json,os
try:
    c=json.load(open("server/config.json"))
    print(c.get("server",{}).get("port",8730))
except Exception:
    print(8730)
PYEOF
)"
[[ -d .venv ]] && source .venv/bin/activate
# start bridge in the background
(./server/run.sh >/tmp/voice-widget.log 2>&1 &) 
# wait for it to come up, then open the browser (localhost = secure context, so getUserMedia works)
for i in {1..30}; do
  if curl -s "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then break; fi
  sleep 0.3
done
open "http://127.0.0.1:${PORT}/"
echo "Voice widget running at http://127.0.0.1:${PORT}/  (log: /tmp/voice-widget.log)"
