// whisper-worker.js - in-browser Whisper STT via transformers.js (WASM/WebGPU).
// Runs OFFLINE: models are pre-staged under web/models/whisper by fetch_models.py, so no network at runtime.
// Loaded as a module worker. Falls back to the CDN only if you explicitly allow it (online).
import { pipeline, env } from 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.0.0';

// Keep it offline: look for locally staged models first. Set allowRemote=true only for first-time online fetch.
env.allowRemoteModels = false;
env.localModelPath = '/models/whisper/';
env.backends.onnx.wasm.numThreads = Math.min(4, (self.navigator?.hardwareConcurrency || 4));

let transcriber = null;
let modelId = 'onnx-community/whisper-base';

self.onmessage = async (e) => {
  const { type } = e.data;
  if (type === 'init') {
    modelId = e.data.modelId || modelId;
    env.allowRemoteModels = !!e.data.allowRemote;
    try {
      transcriber = await pipeline('automatic-speech-recognition', modelId, { quantized: true });
      self.postMessage({ type: 'ready' });
    } catch (err) {
      self.postMessage({ type: 'error', error: String(err) });
    }
  } else if (type === 'transcribe') {
    if (!transcriber) { self.postMessage({ type: 'error', error: 'not ready' }); return; }
    try {
      // e.data.audio is Float32Array mono @16kHz. chunk_length_s enables streaming-ish partials.
      const out = await transcriber(e.data.audio, {
        language: 'en', task: 'transcribe', chunk_length_s: 30, stride_length_s: 5,
      });
      self.postMessage({ type: e.data.final ? 'final' : 'partial', text: (out.text || '').trim() });
    } catch (err) {
      self.postMessage({ type: 'error', error: String(err) });
    }
  }
};
