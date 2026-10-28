#!/usr/bin/env python3
"""Mock Pi agent for offline testing. Emits `pi --mode json` text_delta events that echo the input,
so the bridge /agent SSE path can be exercised without a real Pi install.
Usage (matches config cmd 'python mock_pi.py --mode json {text}'):  python mock_pi.py --mode json "hello there"
"""
import json, sys, time

def main():
    args = [a for a in sys.argv[1:] if a not in ("--mode", "json", "text")]
    text = args[-1] if args else "nothing"
    reply = f"You said: {text}. Here is a second sentence to prove sentence streaming works! And a third one."
    for tok in reply.split(" "):
        print(json.dumps({"type": "message_update",
                          "assistantMessageEvent": {"type": "text_delta", "delta": tok + " "}}), flush=True)
        time.sleep(0.02)

if __name__ == "__main__":
    main()
