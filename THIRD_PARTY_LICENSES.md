# Third-party licenses & redistribution notes

All facts below were verified against the upstream repos/model cards (Oct 2026), not asserted from memory.

## Summary table

| Component | Role | License | Ship in repo? |
|---|---|---|---|
| **Kokoro-82M** (`hexgrad/Kokoro-82M`) | TTS weights | **Apache-2.0** | No — download at setup |
| `kokoro` (pip) | TTS inference lib | Apache-2.0 | pip-installed |
| `misaki` (pip) | Kokoro G2P | **Apache-2.0** | pip-installed |
| `phonemizer-fork` + bundled **espeak-ng** (via `espeakng-loader`) | phoneme fallback that Kokoro loads at runtime | **GPL-3.0-or-later** | **Do NOT bundle** — user installs `brew install espeak-ng`; pip loader is pulled transitively |
| OpenAI Whisper weights | STT weights | **MIT** | No — download at setup |
| `whisper.cpp` / `ggml` | optional WASM STT | **MIT** | source only if forked |
| `transformers.js` | in-browser STT runtime | **Apache-2.0** | loaded from CDN or vendored |
| Parakeet TDT 0.6B | optional server STT weights | **CC-BY-4.0** (attribution) | No — download at setup |
| FastAPI / uvicorn / numpy / soundfile / torch | bridge deps | MIT / BSD-3 | pip-installed |

## The espeak-ng / GPL question (the important one)

Kokoro's `misaki[en]` pulls in `phonemizer-fork` (GPL-3.0-or-later) and an `espeakng-loader` that bundles a
prebuilt **espeak-ng** shared library (GPL-3.0-or-later). Kokoro loads this at runtime for out-of-dictionary English words.

Conclusion for redistribution:
- **Using it privately is unaffected** — private use is not distribution; no copyleft obligation.
- **This repo ships NO GPL code or binaries.** It ships permissive (MIT) code only. espeak-ng is installed
  **separately** by the end user (`brew install espeak-ng`) or pulled into *their* venv by pip. That is
  arm's-length aggregation / dynamic use (like calling `ffmpeg`), which does **not** impose GPL terms on this
  repo's MIT code.
- **Do NOT bundle** espeak-ng/phonemizer into a redistributed binary (PyInstaller app, Docker image, .app with
  the venv inside). Doing so makes the combined work a GPL-3.0 distribution and triggers source-availability
  obligations. Keep weights and espeak-ng as **download-at-setup**, not shipped artifacts, and the MIT license
  on this repo is clean. (Apache-2.0 is one-way compatible with GPL-3.0, so even a bundled build is *possible*,
  but then it must go out under GPL-compatible terms — avoid it.)

## Attribution checklist when redistributing
1. Keep `LICENSE` (MIT, your code), `NOTICE`, and this file.
2. Credit Kokoro, misaki, Whisper, transformers.js, and OpenWhisper (UX inspiration) in the README.
3. If you enable Parakeet, add the NVIDIA CC-BY-4.0 attribution.
4. Never commit model weights; the fetch script downloads them into the user's own environment.

## Windows
Same rule: espeak-ng (GPL-3.0) is installed by the user via `choco install espeak-ng` (community package)
or the official `espeak-ng.msi` from github.com/espeak-ng/espeak-ng/releases. `setup.ps1` only *checks*
for it. Never ship `libespeak-ng.dll` or `espeak-ng-data` inside a PyInstaller .exe or Windows installer.
