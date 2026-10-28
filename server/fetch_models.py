#!/usr/bin/env python3
"""fetch_models.py - download model weights at SETUP time (never committed to the repo).
Runtime stays offline; this is the only component that touches the network, by design.

  python fetch_models.py --kokoro --voice af_heart        # Kokoro-82M weights + one voice
  python fetch_models.py --stt-browser whisper-base-onnx  # transformers.js ONNX whisper into web/models
  python fetch_models.py --id mlx-whisper-large-v3-turbo --progress-json   # by catalog id (used by the GUI)
"""
import argparse, json, os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG = json.loads((HERE / "models_catalog.json").read_text())["models"]
MODELS_DIR = Path(os.environ.get("KOKORO_MODEL_DIR") or (Path.home() / ".voice-loop" / "models"))


def emit(obj, progress_json):
    if progress_json:
        print(json.dumps(obj), flush=True)
    else:
        print(f"  {obj}", flush=True)


def fetch_kokoro(voice, pj):
    from huggingface_hub import snapshot_download
    emit({"id": "kokoro-82m", "pct": 5, "msg": "downloading Kokoro-82M"}, pj)
    d = snapshot_download("hexgrad/Kokoro-82M", local_dir=str(MODELS_DIR / "Kokoro-82M"),
                          allow_patterns=["config.json", "kokoro-v1_0.pth", f"voices/{voice}.pt"])
    emit({"id": "kokoro-82m", "pct": 100, "done": True, "path": d}, pj)


def fetch_stt_server(repo, pj, cid):
    from huggingface_hub import snapshot_download
    emit({"id": cid, "pct": 5, "msg": f"downloading {repo}"}, pj)
    d = snapshot_download(repo, local_dir=str(MODELS_DIR / repo.split("/")[-1]))
    emit({"id": cid, "pct": 100, "done": True, "path": d}, pj)


def fetch_stt_browser(cid, repo, pj):
    # transformers.js resolves ONNX models from HF at first use; to keep runtime offline we pre-stage
    # them under web/models/whisper/<id> and point env.localModelPath there in the worker.
    from huggingface_hub import snapshot_download
    dest = HERE.parent / "web" / "models" / "whisper" / cid
    emit({"id": cid, "pct": 5, "msg": f"staging {repo} for in-browser use"}, pj)
    snapshot_download(repo, local_dir=str(dest),
                      allow_patterns=["*.json", "*.txt", "onnx/*.onnx", "*.onnx"])
    emit({"id": cid, "pct": 100, "done": True, "path": str(dest)}, pj)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kokoro", action="store_true")
    ap.add_argument("--voice", default="af_heart")
    ap.add_argument("--stt-browser", dest="stt_browser")
    ap.add_argument("--id")
    ap.add_argument("--progress-json", action="store_true")
    a = ap.parse_args()
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if a.id:
            m = next((x for x in CATALOG if x["id"] == a.id), None)
            if not m:
                emit({"error": f"unknown id {a.id}"}, a.progress_json); sys.exit(1)
            if m["role"] == "tts":
                fetch_kokoro(a.voice, a.progress_json)
            elif m["role"] == "stt-server":
                fetch_stt_server(m["source"], a.progress_json, a.id)
            else:
                fetch_stt_browser(a.id, m["source"], a.progress_json)
        elif a.kokoro:
            fetch_kokoro(a.voice, a.progress_json)
        elif a.stt_browser:
            m = next((x for x in CATALOG if x["id"] == a.stt_browser), None)
            fetch_stt_browser(a.stt_browser, m["source"], a.progress_json)
        else:
            print("nothing to do; see --help")
    except Exception as ex:
        emit({"error": repr(ex)}, a.progress_json); sys.exit(1)


if __name__ == "__main__":
    main()
