# Voice Widget — local browser voice loop for Pi agents

A browser-based voice widget (STT + TTS) that talks to a local Pi agent. Fully local by default:
in-browser WASM Whisper for speech-to-text, a small local Python bridge that runs your Pi agent and
Kokoro TTS, and audio that starts playing on the **first sentence** of the reply. UX modeled on
OpenWhisper's floating pill. Agent/Kokoro/model settings are all config-driven — nothing is hardcoded,
so the same build points at a company deployment or a personal workstation by swapping config.

> Privacy: with the default in-browser WASM STT + local Kokoro, **no audio or text leaves the machine at
> runtime**. The only network access is at *setup* time to download model weights.

## Quick start

**macOS / Linux**
```bash
./setup.sh
.venv/bin/python server/fetch_models.py --kokoro --voice af_heart
.venv/bin/python server/fetch_models.py --stt-browser whisper-base-onnx
./run.command            # opens http://127.0.0.1:8730/
```

**Windows (PowerShell / Explorer)**
```powershell
choco install espeak-ng          # or install espeak-ng.msi (X64) from the espeak-ng GitHub releases
.\setup.bat
.venv\Scripts\python server\fetch_models.py --kokoro --voice af_heart
.venv\Scripts\python server\fetch_models.py --stt-browser whisper-base-onnx
.\run.bat                # opens http://127.0.0.1:8730/
```

**Licensing in one line:** this code is MIT; Kokoro is Apache-2.0; Whisper and whisper.cpp are MIT;
espeak-ng is GPL-3.0 and is always **installed separately, never bundled**. Details below and in
`THIRD_PARTY_LICENSES.md`.

---

## Architecture

```
            ┌──────────────────────── Browser tab (localhost) ────────────────────────┐
            │  Floating pill GUI (index.html / widget.js / widget.css)                 │
            │   • mic capture (getUserMedia)                                           │
            │   • in-browser WASM Whisper STT  ── whisper-worker.js (transformers.js)  │
            │   • partial transcript display + live waveform                          │
            │   • agent-session dropdown, settings drawer, model-manager.js            │
            │   • audio queue: play sentence N while sentence N+1 synthesizes          │
            └───────▲───────────────── fetch /config /agent(SSE) /tts /models ─────────┘
                    │ (HTTP, 127.0.0.1 only — secure context, so getUserMedia works)
            ┌───────┴──────────────────── Local bridge (server/bridge.py, FastAPI) ────┐
            │  /config   → browser config (agents, kokoro, stt, active models)         │
            │  /agent    → spawn Pi session, parse pi --mode json, split to sentences, │
            │              stream {delta|sentence|done} as SSE                         │
            │  /tts      → Kokoro 24kHz WAV per sentence (reuses voice-loop config)    │
            │  /stt      → OPTIONAL server mlx-whisper/Parakeet (Apple Silicon)        │
            │  /models*  → catalog list / select / download-progress (SSE)            │
            │  /settings → GUI writes config.json here                                 │
            │  SessionRegistry: id → {cmd, mode, cwd, context}                         │
            └───────┬───────────────────────────────┬─────────────────────────────────┘
                    │ subprocess per session         │ in-process
            ┌───────▼────────┐              ┌────────▼─────────┐
            │  Pi agent      │              │  Kokoro-82M      │
            │  pi --mode json│              │  KPipeline, af_* │
            │  (per cwd)     │              │  24kHz, MPS/CPU  │
            └────────────────┘              └──────────────────┘
```

**Data flow for one turn:** mic → WASM Whisper (partials shown live) → on final transcript POST `/agent`
→ bridge runs the selected Pi session → Pi's `text_delta`s are reassembled and split into sentences →
each `sentence` SSE event triggers a `/tts` fetch → the returned 24kHz WAV is pushed to the browser audio
queue → playback starts as soon as sentence 1 is ready while later sentences synthesize in parallel.

**Latency strategy:** (1) partial transcripts stream to the UI every ~2s; (2) the bridge splits the reply
incrementally with an early first-clause flush, so the first spoken audio starts long before the agent
finishes; (3) the browser keeps an audio queue and plays sentence N while fetching/decoding N+1.

### Config approach (company vs personal, one build)

Precedence, low → high: **built-in localhost defaults → `config.json` → environment variables → GUI
settings panel** (the GUI writes `config.json`). The browser bakes in nothing; it calls `/config`.

- **Personal workstation:** `config.json` with your home Pi session(s) and local Kokoro. Or just use the
  GUI — defaults are localhost.
- **Company deployment:** ship a `config.json` (or set `BRIDGE_AGENTS`, `BRIDGE_TOKEN`, `BRIDGE_PORT` env
  vars) pointing at the work repo's Pi session + a shared token. No code changes.
- **Multiple agents at once:** the `agents` array is a list of named **session bindings**, each with its own
  `cwd`/command/context. The widget's dropdown switches between them live, so one widget can drive several
  Pi deployments (e.g. `work` → `/repos/app`, `personal` → `~/projects`).

---

## File structure

```
voice-widget/
├── setup.sh                 # one-command install (venv + deps + config)
├── run.command              # double-clickable macOS launcher (starts bridge, opens browser)
├── setup.ps1 / setup.bat    # Windows install (py launcher, venv, CPU torch, deps)
├── run.ps1 / run.bat        # double-clickable Windows launcher
├── stop.bat                 # stops the Windows bridge
├── LICENSE                  # MIT (your code)
├── NOTICE                   # attribution
├── THIRD_PARTY_LICENSES.md  # verified licenses + GPL/espeak-ng redistribution notes
├── .gitignore
├── .github/workflows/release.yml  # tag v* → per-OS source zips on a GitHub Release (no weights, no espeak-ng)
├── server/
│   ├── bridge.py            # FastAPI bridge: /config /agent /tts /stt /models* /settings + static serve
│   ├── fetch_models.py      # SETUP-time weight downloader (Kokoro, Whisper ONNX, mlx, Parakeet)
│   ├── mock_pi.py           # echo mock agent for offline testing
│   ├── models_catalog.json  # per-role model catalog (name, role, source, size, license)
│   ├── config.example.json  # copy → config.json; documented, localhost defaults
│   ├── .env.example         # every config key as an env override
│   ├── requirements.txt
│   ├── run.sh               # headless/advanced start (mac/Linux)
│   └── run.ps1              # headless/advanced start (Windows)
└── web/
    ├── index.html           # OpenWhisper-style floating pill + settings/model drawer
    ├── widget.css           # pill, waveform, status states, drawer, model rows
    ├── widget.js            # mic, WASM STT, /agent SSE, Kokoro audio queue, GUI wiring
    ├── whisper-worker.js    # transformers.js Whisper in a module worker (offline)
    └── model-manager.js     # list/select/download models with progress
```

---

## Setup — macOS/Linux and Windows

| Step | macOS / Linux | Windows 10/11 |
|---|---|---|
| 1. Prereqs | Python 3.10–3.12, Homebrew (mac) | Python 3.10–3.12 from python.org with the **py launcher** (`winget install Python.Python.3.12`) |
| 2. espeak-ng (GPL, separate install) | `setup.sh` runs `brew install espeak-ng` (Linux: `apt install espeak-ng`) | `choco install espeak-ng` **or** the `espeak-ng.msi` (X64) from github.com/espeak-ng/espeak-ng/releases |
| 3. Install | `./setup.sh` | double-click `setup.bat` (or `powershell -ExecutionPolicy Bypass -File .\setup.ps1`) |
| 4. Fetch models | `.venv/bin/python server/fetch_models.py --kokoro --voice af_heart`<br>`.venv/bin/python server/fetch_models.py --stt-browser whisper-base-onnx` | `.venv\Scripts\python server\fetch_models.py --kokoro --voice af_heart`<br>`.venv\Scripts\python server\fetch_models.py --stt-browser whisper-base-onnx` |
| 5. Launch | double-click `run.command` (or `./server/run.sh`) | double-click `run.bat` (or `.\server\run.ps1`); stop with `stop.bat` |
| 6. Use | open `http://127.0.0.1:8730/`, allow mic, pick agent, talk | same |

`fetch_models.py` is pure Python with `pathlib` paths, so the same flags work on both OSes; only the
interpreter path differs.

### Mac ↔ Windows differences

| Thing | macOS / Linux | Windows |
|---|---|---|
| Python launcher | `python3.12` / `python3` | `py -3.12` (setup), then `.venv\Scripts\python.exe` |
| venv activate | `source .venv/bin/activate` | `.venv\Scripts\Activate.ps1` (PowerShell) / `.venv\Scripts\activate.bat` (cmd) |
| venv interpreter | `.venv/bin/python` | `.venv\Scripts\python.exe` |
| Run a script | `./setup.sh`, `./run.command` | `setup.bat`, `run.bat` (or `.\setup.ps1`) |
| Path separator | `/` | `\` (Python code uses `pathlib`; `/` also works in config.json) |
| Home dir / models | `~/.voice-loop/models` | `%USERPROFILE%\.voice-loop\models` (same `Path.home()` code) |
| config.json / .env | `server/config.json`, `server/.env` | `server\config.json`, `server\.env` (same place, repo-relative) |
| `.env` loading | `run.sh` sources it; bridge also loads it | bridge loads it itself (no `source` in cmd/PowerShell) |
| Log file | `/tmp/voice-widget.log` | `%TEMP%\voice-widget.log` |
| Open URL | `open URL` | `start "" URL` / `Start-Process URL` |
| Stop bridge | Ctrl+C / `pkill -f bridge.py` | `stop.bat` / Task Manager |
| Pi command | `pi` on PATH | `pi.cmd` (npm shim); bridge resolves it via `shutil.which`. Quote paths with spaces: `"C:/Tools/pi.cmd" --mode json {text}` |
| espeak-ng lookup | found on system lib path | bridge auto-sets `PHONEMIZER_ESPEAK_LIBRARY` to `C:\Program Files\eSpeak NG\libespeak-ng.dll` if unset |
| Launch gatekeeping | Gatekeeper: right-click → Open once | SmartScreen / Mark-of-the-Web (below) |
| Script policy | n/a | PowerShell execution policy — `.bat` wrappers pass `-ExecutionPolicy Bypass` for that run only |
| Torch | MPS (Apple GPU) or CPU | CPU wheel (setup default) or CUDA wheel for NVIDIA |
| Server STT | mlx-whisper / Parakeet (Apple Silicon) | not available; use in-browser Whisper (see below) |

### Windows notes
- **SmartScreen / downloaded files:** a `.bat` from a downloaded ZIP carries Mark-of-the-Web. Windows may
  show "Windows protected your PC" → click **More info → Run anyway**, or before extracting:
  right-click the ZIP → Properties → tick **Unblock**. (Cloning with git avoids it.) This is the
  equivalent of the Mac Gatekeeper right-click → Open step.
- **espeak-ng wiring:** phonemizer on Windows looks for `espeak-ng.dll`, but the installer ships
  `libespeak-ng.dll`, so it often reports "espeak not installed". The bridge sets
  `PHONEMIZER_ESPEAK_LIBRARY=C:\Program Files\eSpeak NG\libespeak-ng.dll` and
  `PHONEMIZER_ESPEAK_PATH=C:\Program Files\eSpeak NG\espeak-ng.exe` automatically when that file exists.
  For a non-default install, set them in `server\.env` **without quotes** (a quoted value is read as a
  relative path and fails). Check with `"C:\Program Files\eSpeak NG\espeak-ng.exe" --version`.
- **Kokoro / torch:** `pip install kokoro` works on Windows with Python 3.10–3.12 (not 3.13). `setup.ps1`
  installs the CPU torch wheel first (~200 MB instead of multi-GB CUDA); swap in the `cu124` index for an
  NVIDIA GPU. Kokoro-82M is fast enough on CPU for sentence-by-sentence speech.
- **Speech-to-text on Windows:** mlx-whisper and Parakeet-MLX are Apple-Silicon-only. On Windows use the
  **in-browser Whisper** (default, offline). If a server-side engine is wanted later, the Windows-native
  options are **faster-whisper** (CTranslate2, CPU/CUDA, MIT) or **whisper.cpp** (MIT) behind `/stt`; these
  are not wired in yet (`/stt` returns 501 on non-Mac).
- Microphone: Settings → Privacy & security → Microphone → allow for your browser. `http://127.0.0.1`
  is a secure context on Windows browsers too.

## GUI & launcher

The floating pill is the default entry point — no config-file editing needed for basic use.
- **Mic button** (start/stop), **live partial transcript**, **live waveform**, status states
  (idle / listening / transcribing / agent thinking / speaking).
- **Agent-session dropdown** to switch Pi deployments.
- **Settings drawer** (⚙): General (bridge URL, STT mode), Sessions (add/edit bindings → writes config),
  Models (manager), Voice (voice picker, speed, volume). All changes POST to `/settings`, which writes
  `config.json` under the hood.
- **Launcher:** `run.command` is a double-clickable Finder file that starts the bridge and opens the widget
  in the default browser. To make it double-clickable: `chmod +x run.command` (done), then in Finder
  right-click → Open the first time to clear Gatekeeper. Basic use = launch + grant mic + pick agent + talk,
  no Terminal.

## Model manager (per role)

- **STT** splits into two execution paths, both exposed in the GUI:
  - *In-browser (offline, lower accuracy)* — WASM Whisper via transformers.js, runs in the tab, no bridge
    round-trip for audio.
  - *Server mlx-whisper / Parakeet (faster, more accurate, needs the bridge)* — audio posts to `/stt`;
    Apple-Silicon only. Parakeet is English-only.
- **TTS** — Kokoro voice picker (`af_heart`, …) + speed + volume. Defaults inherit from your voice-loop.
- **LLM** — set by your Pi agent, not this tool. The bridge reads/displays Pi's configured model; where Pi
  accepts a model flag, you can bake it into a session's `cmd` per binding. Honest limit: it's display-only
  unless Pi exposes a per-invocation model flag.
- The manager shows Installed vs Available, size, license, a Download button (streamed progress), and a
  Select/active toggle. Weights are fetched on demand by `fetch_models.py` — **never committed to the repo**.

---

## Packaging & distribution

- **Public-ready repo**: permissive (MIT) static widget + Python bridge. One-command `setup.sh`, separate
  `fetch_models.py` for weights, and the bridge serves the widget so a third party runs one command and
  opens one URL. A `pipx`/`pip` console entrypoint for the bridge is a straightforward add (expose
  `bridge:main` as `voice-widget-bridge`).
- **Dependencies**: pip-installed = fastapi, uvicorn, anyio, numpy, soundfile, kokoro (pulls torch, misaki,
  transformers, spacy). Downloaded at setup = Kokoro weights (~330MB), Whisper ONNX (~145MB base / ~42MB
  tiny), optional mlx-whisper (~1.6GB) / Parakeet (~1.2GB). Shipped in repo = source only, **no weights,
  no GPL binaries**. System (macOS brew) = espeak-ng, portaudio. Cross-platform: the bridge + widget +
  in-browser STT. Mac-only: mlx-whisper/Parakeet server STT and MPS acceleration.
- **Windows packaging:** the bridge can be frozen into a `voice-widget.exe` with PyInstaller
  (`pyinstaller --onedir server/bridge.py --add-data "web;web"`). Feasible, but heavy (torch makes it
  ~1 GB onedir) and onefile startup is slow, so the venv + `run.bat` path is the recommended Windows route.
  **Same GPL caveat:** do **not** put `libespeak-ng.dll`/`espeak-ng-data` (or phonemizer's bundled espeak
  loader) inside the .exe/installer — the user installs espeak-ng themselves (choco/MSI). Unsigned .exe
  files also hit SmartScreen; code-signing removes that.
- **Licensing verdict** (verified against upstream Oct 2026; details in `THIRD_PARTY_LICENSES.md`):
  - Kokoro-82M weights **Apache-2.0**; `kokoro` **Apache-2.0**; `misaki` **Apache-2.0**; Whisper (openai) &
    whisper.cpp **MIT**; transformers.js **Apache-2.0**; Parakeet weights **CC-BY-4.0** (attribution).
  - **espeak-ng + phonemizer-fork are GPL-3.0-or-later.** Kokoro loads them at runtime. OK: install them
    **separately** (brew / the user's own venv) — arm's-length/dynamic use imposes no GPL obligation on this
    repo's MIT code. **Not OK:** bundling them into a redistributed binary (PyInstaller/.app/Docker) — that
    makes the combined work GPL. So keep espeak-ng and all weights as **download/install at setup**, and the
    repo stays cleanly MIT.
  - Recommended license for Eon's own code: **MIT** (shipped as `LICENSE`) — compatible with all of the above.
  - Attribution checklist: keep `LICENSE`/`NOTICE`/`THIRD_PARTY_LICENSES.md`; credit Kokoro, misaki, Whisper,
    transformers.js, and OpenWhisper (UX); add NVIDIA CC-BY-4.0 credit if Parakeet is enabled.
- **Blockers / caveats**: WASM Whisper model size (first-load weight download); Kokoro's espeak-ng system
  dependency; macOS mic permission + the localhost secure-context requirement for `getUserMedia`; and Pi
  itself is the user's own agent (this tool is agent-agnostic via config, so that's fine). Kokoro's *first*
  run historically downloads weights — we force local paths + `HF_HUB_OFFLINE=1`, and `fetch_models.py` does
  the download at setup, so **runtime stays offline**.

## Credits
UX inspired by [OpenWhisper](https://github.com/malukenho/OpenWhisper) (MIT). TTS by
[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0). STT by
[OpenAI Whisper](https://github.com/openai/whisper) (MIT) via
[transformers.js](https://github.com/huggingface/transformers.js) (Apache-2.0).
