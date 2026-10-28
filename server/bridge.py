#!/usr/bin/env python3
"""
bridge.py - local HTTP bridge for the browser voice widget.

Fully local. The browser talks ONLY to this bridge on localhost. The bridge:
  - serves the widget GUI (static files in ../web) so there is one URL to open
  - /config        : browser fetches its config here (agents, kokoro, stt) - nothing baked into the JS
  - /agent  (SSE)  : text in -> runs the selected Pi agent session -> streams the reply sentence-by-sentence
  - /tts           : text in -> 24 kHz WAV out (Kokoro, reusing the voice-loop config)
  - /stt   (POST)  : OPTIONAL server-side STT (mlx-whisper / parakeet) when the GUI picks a server model
  - /models ...    : model manager (list / select / download-progress) backed by models_catalog.json
  - /settings (POST): GUI settings panel writes the config file through here

Config precedence (low -> high): localhost defaults < config.json < env vars.
The GUI settings panel writes config.json, so GUI > file for anything it sets.

Nothing company-specific is hardcoded. Reuses Kokoro from the existing voice-loop when
`kokoro.voice_loop_path` points at it; otherwise loads Kokoro-82M the same way (local paths, HF_HUB_OFFLINE).
"""
import io
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import threading
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
IS_WIN = os.name == "nt"


def _load_dotenv(path=HERE / ".env"):
    """Cross-platform .env loader (run.sh sources it on Mac/Linux; Windows launchers rely on this).
    Never overrides variables already set in the real environment."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _wire_espeak_windows():
    """espeak-ng is installed SEPARATELY (GPL-3.0, never bundled). On Windows phonemizer often can't find
    libespeak-ng.dll on its own, so point it at the standard install location if the user hasn't.
    Also strip stray quotes: phonemizer treats a quoted value as a relative path and fails."""
    if not IS_WIN:
        return
    for k in ("PHONEMIZER_ESPEAK_LIBRARY", "PHONEMIZER_ESPEAK_PATH"):
        if os.environ.get(k):
            os.environ[k] = os.environ[k].strip().strip('"')
    if not os.environ.get("PHONEMIZER_ESPEAK_LIBRARY"):
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            dll = Path(base) / "eSpeak NG" / "libespeak-ng.dll"
            if dll.exists():
                os.environ["PHONEMIZER_ESPEAK_LIBRARY"] = str(dll)
                os.environ.setdefault("PHONEMIZER_ESPEAK_PATH", str(dll.with_name("espeak-ng.exe")))
                break


def _split_cmd(cmd):
    """Split a session command. POSIX shlex mangles Windows backslash paths, so use non-POSIX mode there."""
    if IS_WIN:
        return [p[1:-1] if len(p) > 1 and p[0] == p[-1] and p[0] in "\"'" else p
                for p in shlex.split(cmd, posix=False)]
    return shlex.split(cmd)


_load_dotenv()
_wire_espeak_windows()
DEFAULT_CONFIG_PATH = Path(os.environ.get("BRIDGE_CONFIG", HERE / "config.json"))
CATALOG_PATH = HERE / "models_catalog.json"

# ----------------------------------------------------------------------------- config
DEFAULTS = {
    "server": {"host": "127.0.0.1", "port": 8730, "serve_widget": True, "widget_dir": str(HERE.parent / "web")},
    "auth": {"require_token": False, "token": ""},
    "stt": {"backend": "transformers-js", "model_id": "onnx-community/whisper-base",
            "model_assets_url": "/models/whisper", "allow_web_speech_fallback": False},
    "kokoro": {"enabled": True, "voice": "af_heart", "speed": 1.0, "lang_code": "a",
               "sample_rate": 24000, "device": "auto", "model_dir": "", "voice_loop_path": ""},
    "agents": [{"id": "default", "name": "Local agent", "cmd": "pi --mode json {text}",
                "mode": "pi-json", "cwd": "", "system": ""}],
}


def _deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _env_overrides():
    """Env vars override the file. Keep this list documented in .env.example."""
    o = {"server": {}, "auth": {}, "stt": {}, "kokoro": {}}
    e = os.environ.get
    if e("BRIDGE_HOST"): o["server"]["host"] = e("BRIDGE_HOST")
    if e("BRIDGE_PORT"): o["server"]["port"] = int(e("BRIDGE_PORT"))
    if e("BRIDGE_TOKEN"):
        o["auth"]["require_token"] = True
        o["auth"]["token"] = e("BRIDGE_TOKEN")
    if e("KOKORO_VOICE"): o["kokoro"]["voice"] = e("KOKORO_VOICE")
    if e("KOKORO_SPEED"): o["kokoro"]["speed"] = float(e("KOKORO_SPEED"))
    if e("KOKORO_DEVICE"): o["kokoro"]["device"] = e("KOKORO_DEVICE")
    if e("KOKORO_MODEL_DIR"): o["kokoro"]["model_dir"] = e("KOKORO_MODEL_DIR")
    if e("VOICE_LOOP_PATH"): o["kokoro"]["voice_loop_path"] = e("VOICE_LOOP_PATH")
    if e("STT_MODEL_ID"): o["stt"]["model_id"] = e("STT_MODEL_ID")
    agents_json = e("BRIDGE_AGENTS")
    if agents_json:
        try:
            o["agents"] = json.loads(agents_json)
        except ValueError:
            pass
    return {k: v for k, v in o.items() if v}


def load_config(path=DEFAULT_CONFIG_PATH):
    cfg = dict(DEFAULTS)
    if Path(path).is_file():
        try:
            cfg = _deep_merge(cfg, json.loads(Path(path).read_text()))
        except ValueError as ex:
            print(f"[bridge] WARNING: bad config {path}: {ex}; using defaults", file=sys.stderr)
    cfg = _deep_merge(cfg, _env_overrides())
    return cfg


def save_config(cfg, path=DEFAULT_CONFIG_PATH):
    # Never persist the env-only auth token by accident; persist the structured config as-is.
    Path(path).write_text(json.dumps(cfg, indent=2))


# ----------------------------------------------------------------------------- sentence splitting
_ABBREV = {"mr", "mrs", "ms", "dr", "st", "vs", "etc", "e.g", "i.e", "fig", "inc", "ltd", "jr", "sr"}


class SentenceSplitter:
    """Incremental splitter: feed(chunk)->list[sentence], flush() at end.
    Lightweight copy of the voice-loop splitter so playback can start on the first sentence."""
    def __init__(self, max_len=300, early_clause_min=60):
        self.buf, self.max_len, self.early_clause_min, self._emitted = "", max_len, early_clause_min, False

    @staticmethod
    def _is_boundary(text, i):
        j = i
        while j > 0 and not text[j - 1].isspace():
            j -= 1
        tok = text[j:i].lstrip("(\"'[").lower()
        if tok in _ABBREV or (len(tok) == 1 and tok.isalpha()) or re.fullmatch(r"(\w\.)+\w", tok or ""):
            return False
        return True

    def _clean(self, raw):
        t = re.sub(r"[*_`#>]+", "", raw).strip()
        return t

    def _scan(self, text, out, final):
        start, i, n = 0, 0, len(text)
        while i < n:
            c = text[i]
            if c == "\n":
                s = self._clean(text[start:i])
                if s and re.search(r"\w", s):
                    out.append(s); self._emitted = True
                start = i + 1
            elif c in ".!?…":
                k = i + 1
                while k < n and text[k] in ".!?…\"')]”’":
                    k += 1
                if k >= n:
                    break
                if text[k].isspace():
                    if c in "!?…" or self._is_boundary(text, i):
                        s = self._clean(text[start:k])
                        if s and re.search(r"\w", s):
                            out.append(s); self._emitted = True
                        start = k
                i = k - 1
            i += 1
        rest = text[start:]
        if not final and not self._emitted and len(rest) >= self.early_clause_min:
            m = [x for x in re.finditer(r"[,;:]\s", rest) if x.end() >= 30]
            if m:
                s = self._clean(rest[:m[-1].end()])
                if s:
                    out.append(s); self._emitted = True
                rest = rest[m[-1].end():]
        return rest

    def feed(self, chunk):
        out = []
        self.buf += chunk
        self.buf = self._scan(self.buf, out, final=False)
        return out

    def flush(self):
        out = []
        s = self._clean(self._scan(self.buf, out, final=True))
        if s and re.search(r"\w", s):
            out.append(s)
        self.buf = ""
        return out


def pi_delta(line):
    """Parse one JSONL line of `pi --mode json` into reply text (text_delta events)."""
    line = line.strip()
    if not line.startswith("{"):
        return ""
    try:
        ev = json.loads(line)
    except ValueError:
        return ""
    if ev.get("type") == "message_update":
        e = ev.get("assistantMessageEvent") or {}
        if e.get("type") == "text_delta":
            return e.get("delta", "")
    return ""


# ----------------------------------------------------------------------------- Kokoro TTS
class KokoroEngine:
    """Reuses the voice-loop Kokoro setup. If cfg.voice_loop_path is set and importable, we use its
    KokoroTTS class verbatim; otherwise we load Kokoro-82M the same way (local files, HF_HUB_OFFLINE)."""
    def __init__(self, cfg):
        self.cfg = cfg["kokoro"]
        self.sr = int(self.cfg.get("sample_rate", 24000))
        self._tts = None
        self._lock = threading.Lock()

    def _default_model_dir(self):
        d = self.cfg.get("model_dir")
        if d:
            return Path(d)
        # same default location the voice-loop uses: ~/.voice-loop/models/Kokoro-82M
        return Path.home() / ".voice-loop" / "models" / "Kokoro-82M"

    def load(self):
        if self._tts is not None:
            return
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        vlp = self.cfg.get("voice_loop_path")
        if vlp and Path(vlp).exists():
            sys.path.insert(0, str(Path(vlp).parent))
            try:
                import voice_loop  # type: ignore
                self._tts = voice_loop.KokoroTTS(
                    voice=self.cfg["voice"], speed=float(self.cfg["speed"]),
                    device=None if self.cfg["device"] == "auto" else self.cfg["device"],
                    lang_code=self.cfg["lang_code"]).load()
                print(f"[bridge] Kokoro loaded via voice_loop ({vlp}) on {self._tts.device}")
                return
            except Exception as ex:
                print(f"[bridge] voice_loop import failed ({ex!r}); loading Kokoro standalone", file=sys.stderr)
        self._tts = _StandaloneKokoro(self._default_model_dir(), self.cfg).load()
        print(f"[bridge] Kokoro loaded standalone on {self._tts.device}")

    def synth_wav(self, text):
        """Return a complete 24 kHz mono 16-bit WAV (bytes) for one sentence."""
        import numpy as np
        with self._lock:
            self.load()
            chunks = [c for c in self._tts.synth(text) if c is not None and len(c)]
        audio = np.concatenate(chunks) if chunks else np.zeros(1, dtype="float32")
        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(self.sr); w.writeframes(pcm)
        return buf.getvalue()


class _StandaloneKokoro:
    """Mirror of voice_loop.KokoroTTS: KModel + KPipeline from LOCAL paths, so no hub calls at runtime."""
    def __init__(self, model_dir, cfg):
        self.d = Path(model_dir); self.cfg = cfg; self.device = "cpu"

    def _pick_device(self):
        pref = self.cfg.get("device", "auto")
        if pref and pref != "auto":
            return pref
        try:
            import torch
            if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
                return "mps"
        except Exception:
            pass
        return "cpu"

    def load(self):
        from kokoro import KModel, KPipeline
        voice = self.cfg["voice"]
        cfg, wts, vp = self.d / "config.json", self.d / "kokoro-v1_0.pth", self.d / "voices" / f"{voice}.pt"
        for need in (cfg, wts, vp):
            if not need.exists():
                raise SystemExit(f"Missing {need}. Run: python server/fetch_models.py --kokoro --voice {voice}")
        self.device = self._pick_device()
        model = KModel(repo_id="hexgrad/Kokoro-82M", config=str(cfg), model=str(wts)).eval()
        try:
            model = model.to(self.device)
            self.pipe = KPipeline(lang_code=self.cfg["lang_code"], repo_id="hexgrad/Kokoro-82M", model=model)
            self._voice = str(vp)
            if self.device != "cpu":
                list(self.synth("ok"))
        except Exception as ex:
            print(f"[bridge] Kokoro on {self.device} failed ({ex!r}); CPU", file=sys.stderr)
            self.device = "cpu"; model = model.to("cpu")
            self.pipe = KPipeline(lang_code=self.cfg["lang_code"], repo_id="hexgrad/Kokoro-82M", model=model)
            self._voice = str(vp)
        return self

    def synth(self, text):
        import numpy as np
        for r in self.pipe(text, voice=self._voice, speed=float(self.cfg["speed"])):
            if r.audio is not None:
                yield r.audio.detach().cpu().numpy().astype(np.float32)


# ----------------------------------------------------------------------------- Pi agent sessions
class SessionRegistry:
    """id -> agent binding (cmd/mode/cwd/context). One widget can target many deployments."""
    def __init__(self, agents):
        self.agents = {a["id"]: a for a in agents}

    def get(self, session_id):
        return self.agents.get(session_id) or next(iter(self.agents.values()), None)

    def list_public(self):
        return [{"id": a["id"], "name": a.get("name", a["id"]), "cwd": a.get("cwd", "")}
                for a in self.agents.values()]


def run_agent_stream(binding, text):
    """Generator of SSE event dicts. Spawns the session's command, parses its output, splits to sentences."""
    cmd, mode, cwd = binding["cmd"], binding.get("mode", "pi-json"), (binding.get("cwd") or None)
    parts = _split_cmd(cmd)
    argv = [p.replace("{text}", text) for p in parts] if any("{text}" in p for p in parts) else parts + [text]
    # Windows: npm installs `pi` as pi.cmd; CreateProcess won't find it without resolving PATHEXT.
    exe = shutil.which(argv[0]) if argv else None
    if exe:
        argv[0] = exe
    sp = SentenceSplitter()
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, cwd=cwd, text=True, bufsize=1,
                                encoding="utf-8", errors="replace")
    except FileNotFoundError:
        yield {"type": "error", "text": f"Command not found: {argv[0]!r}. Is Pi on PATH?"}
        yield {"type": "done"}
        return
    try:
        for line in proc.stdout:
            delta = line if mode == "text" else pi_delta(line)
            if not delta:
                continue
            yield {"type": "delta", "text": delta}
            for s in sp.feed(delta):
                yield {"type": "sentence", "text": s}
        for s in sp.flush():
            yield {"type": "sentence", "text": s}
    finally:
        try:
            proc.stdout.close(); proc.wait(timeout=5)
        except Exception:
            proc.kill()
    yield {"type": "done"}


# ----------------------------------------------------------------------------- model manager
def load_catalog():
    try:
        return json.loads(CATALOG_PATH.read_text()).get("models", [])
    except Exception:
        return []


def models_dir():
    return Path(os.environ.get("KOKORO_MODEL_DIR") or (Path.home() / ".voice-loop" / "models"))


def model_installed(m):
    """Heuristic install check by role."""
    md = models_dir()
    if m["role"] == "tts":
        return (md / "Kokoro-82M" / "kokoro-v1_0.pth").exists()
    if m["role"] == "stt-server":
        return (md / m["source"].split("/")[-1]).exists()
    if m["role"] == "stt-browser":
        # browser models live in web/models/whisper/<id>; the bridge just reports presence
        return (HERE.parent / "web" / "models" / "whisper" / m["id"]).exists()
    return False


def models_state(active):
    out = []
    for m in load_catalog():
        d = dict(m); d["installed"] = model_installed(m); d["active"] = active.get(m["role"]) == m["id"]
        out.append(d)
    return out


# ----------------------------------------------------------------------------- FastAPI app
def build_app(cfg):
    from fastapi import FastAPI, Request, Response
    from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, PlainTextResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="voice-widget bridge")
    state = {
        "cfg": cfg,
        "registry": SessionRegistry(cfg["agents"]),
        "kokoro": KokoroEngine(cfg) if cfg["kokoro"].get("enabled") else None,
        "active_models": {"stt-browser": cfg["stt"].get("model_id", "whisper-base-onnx"),
                          "stt-server": None, "tts": "kokoro-82m"},
    }

    def check_auth(request: Request):
        a = state["cfg"]["auth"]
        if a.get("require_token") and request.headers.get("x-bridge-token") != a.get("token"):
            return False
        return True

    @app.get("/health")
    def health():
        return {"ok": True, "kokoro": bool(state["kokoro"]), "agents": len(state["cfg"]["agents"])}

    @app.get("/config")
    def get_config():
        c = state["cfg"]
        # Browser-safe subset only. No tokens, no filesystem paths beyond the STT asset URL.
        return {
            "agents": state["registry"].list_public(),
            "kokoro": {"enabled": bool(state["kokoro"]), "voice": c["kokoro"]["voice"],
                       "speed": c["kokoro"]["speed"], "sample_rate": c["kokoro"]["sample_rate"],
                       "voices": next((m.get("voices", []) for m in load_catalog() if m["role"] == "tts"), [])},
            "stt": {"backend": c["stt"]["backend"], "model_id": c["stt"]["model_id"],
                    "model_assets_url": c["stt"]["model_assets_url"],
                    "allow_web_speech_fallback": c["stt"].get("allow_web_speech_fallback", False)},
            "active_models": state["active_models"],
        }

    @app.post("/settings")
    async def post_settings(request: Request):
        if not check_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        state["cfg"] = _deep_merge(state["cfg"], body)
        save_config(state["cfg"])
        state["registry"] = SessionRegistry(state["cfg"]["agents"])
        if state["cfg"]["kokoro"].get("enabled"):
            state["kokoro"] = KokoroEngine(state["cfg"])
        return {"ok": True}

    @app.get("/models")
    def list_models():
        return {"models": models_state(state["active_models"]), "models_dir": str(models_dir())}

    @app.post("/models/select")
    async def select_model(request: Request):
        body = await request.json()
        role, mid = body.get("role"), body.get("id")
        if role not in state["active_models"]:
            return JSONResponse({"error": "bad role"}, status_code=400)
        state["active_models"][role] = mid
        if role == "stt-browser":
            state["cfg"]["stt"]["model_id"] = mid
            save_config(state["cfg"])
        return {"ok": True, "active_models": state["active_models"]}

    @app.post("/models/download")
    async def download_model(request: Request):
        body = await request.json()
        mid = body.get("id")
        m = next((x for x in load_catalog() if x["id"] == mid), None)
        if not m:
            return JSONResponse({"error": "unknown model"}, status_code=404)

        def gen():
            # Real downloads happen via fetch_models.py; here we stream progress of that process,
            # or (when invoked with mock=1) a simulated progress for offline testing.
            if body.get("mock"):
                for p in range(0, 101, 20):
                    yield f"data: {json.dumps({'id': mid, 'pct': p})}\n\n"
                yield f"data: {json.dumps({'id': mid, 'done': True})}\n\n"
                return
            cmd = [sys.executable, str(HERE / "fetch_models.py"), "--id", mid, "--progress-json"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, bufsize=1,
                                    encoding="utf-8", errors="replace")
            for line in proc.stdout:
                line = line.strip()
                if line:
                    yield f"data: {line}\n\n"
            proc.wait()
            yield f"data: {json.dumps({'id': mid, 'done': proc.returncode == 0})}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/agent")
    async def agent(request: Request):
        if not check_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        text = (body.get("text") or "").strip()
        binding = state["registry"].get(body.get("session_id"))
        if not binding:
            return JSONResponse({"error": "no agent sessions configured"}, status_code=400)
        if not text:
            return JSONResponse({"error": "empty text"}, status_code=400)

        def gen():
            for ev in run_agent_stream(binding, text):
                yield f"data: {json.dumps(ev)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/tts")
    async def tts(request: Request):
        if not check_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if not state["kokoro"]:
            return JSONResponse({"error": "tts disabled"}, status_code=400)
        body = await request.json()
        text = (body.get("text") or "").strip()
        if not text:
            return Response(status_code=204)
        if body.get("voice"):
            state["kokoro"].cfg["voice"] = body["voice"]; state["kokoro"]._tts = None
        if body.get("speed"):
            state["kokoro"].cfg["speed"] = float(body["speed"]); state["kokoro"]._tts = None
        wav = await run_in_thread(state["kokoro"].synth_wav, text)
        return Response(content=wav, media_type="audio/wav")

    @app.post("/stt")
    async def stt(request: Request):
        # OPTIONAL server-side STT path (mlx-whisper / parakeet). Stubbed import so the bridge
        # starts on Linux/box; real transcription only runs on Apple Silicon with the model installed.
        if not check_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            import numpy as np, soundfile as sf  # noqa
        except Exception:
            return JSONResponse({"error": "server STT deps not installed"}, status_code=501)
        return JSONResponse({"error": "server-side STT not enabled in this build; use in-browser WASM STT"},
                            status_code=501)

    # serve the widget GUI last so /api routes win
    if cfg["server"].get("serve_widget"):
        wdir = Path(cfg["server"]["widget_dir"])
        if not wdir.is_absolute():
            wdir = (HERE / wdir).resolve()
        if wdir.is_dir():
            app.mount("/", StaticFiles(directory=str(wdir), html=True), name="widget")
    return app


async def run_in_thread(fn, *a):
    import anyio
    return await anyio.to_thread.run_sync(lambda: fn(*a))


def main():
    cfg = load_config()
    app = build_app(cfg)
    import uvicorn
    host, port = cfg["server"]["host"], int(cfg["server"]["port"])
    print(f"[bridge] http://{host}:{port}  (widget + /config + /agent + /tts + /models)")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
