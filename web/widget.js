// widget.js - mic capture + in-browser WASM Whisper STT (partial streaming) + /agent SSE + Kokoro audio queue.
// Talks ONLY to the local bridge. No cloud unless the user explicitly picks the Web Speech fallback.
(function () {
  const $ = (s) => document.querySelector(s);
  const pill = $('#pill'), statusEl = $('#status'), partialEl = $('#partial');
  const micBtn = $('#micBtn'), agentSel = $('#agentSel'), waveCanvas = $('#wave');

  // Bridge base URL: same origin when the bridge serves the page; overridable in settings.
  let bridge = localStorage.getItem('bridgeUrl') || location.origin;
  let config = null, sttMode = 'transformers-js', voice = 'af_heart', speed = 1.0, volume = 1.0;
  let listening = false, worker = null, audioCtx = null, mediaStream = null, recorder = null;
  let recChunks = [];

  function setState(s, label) {
    pill.classList.remove('listening', 'speaking', 'active');
    if (s === 'listening') pill.classList.add('listening', 'active');
    if (s === 'speaking') pill.classList.add('speaking', 'active');
    if (s !== 'idle') pill.classList.add('active');
    statusEl.textContent = label || s[0].toUpperCase() + s.slice(1);
  }

  // ---------------- config load (nothing baked into JS; fetched from /config) ----------------
  async function loadConfig() {
    try {
      const r = await fetch(bridge + '/config');
      config = await r.json();
    } catch (e) {
      statusEl.textContent = 'Bridge offline'; return;
    }
    agentSel.innerHTML = '';
    (config.agents || []).forEach(a => {
      const o = document.createElement('option'); o.value = a.id; o.textContent = a.name; agentSel.appendChild(o);
    });
    sttMode = config.stt?.backend || 'transformers-js';
    voice = config.kokoro?.voice || 'af_heart';
    speed = config.kokoro?.speed || 1.0;
    window.ModelManager.setBridge(bridge);
    populateVoices(config.kokoro?.voices || []);
  }

  // ---------------- in-browser WASM Whisper ----------------
  function initWorker() {
    if (worker || sttMode !== 'transformers-js') return;
    worker = new Worker('whisper-worker.js', { type: 'module' });
    worker.onmessage = (e) => {
      const { type, text, error } = e.data;
      if (type === 'ready') statusEl.textContent = 'Model ready';
      else if (type === 'partial') { partialEl.textContent = text; }
      else if (type === 'final') { partialEl.textContent = text; if (text) sendToAgent(text); }
      else if (type === 'error') { statusEl.textContent = 'STT error'; console.error(error); }
    };
    worker.postMessage({ type: 'init', modelId: config?.stt?.model_id, allowRemote: false });
  }

  // 16kHz mono Float32 resample for whisper
  function toMono16k(audioBuffer) {
    const srcRate = audioBuffer.sampleRate, src = audioBuffer.getChannelData(0);
    const ratio = srcRate / 16000, len = Math.floor(src.length / ratio);
    const out = new Float32Array(len);
    for (let i = 0; i < len; i++) out[i] = src[Math.floor(i * ratio)];
    return out;
  }

  async function startListening() {
    if (listening) return stopListening();
    listening = true; setState('listening', 'Listening…');
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    drawWave(mediaStream);

    if (sttMode === 'web-speech') return startWebSpeech();   // ONLINE fallback, opt-in only
    initWorker();
    recChunks = [];
    recorder = new MediaRecorder(mediaStream);
    recorder.ondataavailable = (e) => { if (e.data.size) recChunks.push(e.data); };
    recorder.onstop = async () => {
      setState('idle', 'Transcribing…');
      const blob = new Blob(recChunks, { type: recorder.mimeType });
      const buf = await blob.arrayBuffer();
      const decoded = await audioCtx.decodeAudioData(buf);
      const audio = toMono16k(decoded);
      worker.postMessage({ type: 'transcribe', audio, final: true }, [audio.buffer]);
    };
    // periodic partials: emit a chunk every 2s so the user sees live transcript
    recorder.start(2000);
    recorder.addEventListener('dataavailable', async () => {
      if (!listening || recChunks.length === 0) return;
      try {
        const blob = new Blob(recChunks, { type: recorder.mimeType });
        const decoded = await audioCtx.decodeAudioData(await blob.arrayBuffer());
        worker.postMessage({ type: 'transcribe', audio: toMono16k(decoded), final: false });
      } catch (_) {}
    });
  }

  function stopListening() {
    listening = false;
    if (recorder && recorder.state !== 'inactive') recorder.stop();
    if (mediaStream) mediaStream.getTracks().forEach(t => t.stop());
    setState('idle', 'Idle');
  }

  // Online-only fallback, clearly labeled. Uses the browser's cloud STT.
  let sr = null;
  function startWebSpeech() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { statusEl.textContent = 'Web Speech unsupported'; return; }
    sr = new SR(); sr.lang = 'en-US'; sr.interimResults = true; sr.continuous = false;
    sr.onresult = (e) => {
      let txt = ''; for (const r of e.results) txt += r[0].transcript;
      partialEl.textContent = txt;
      if (e.results[e.results.length - 1].isFinal) sendToAgent(txt.trim());
    };
    sr.onend = () => { if (listening) stopListening(); };
    sr.start();
  }

  // ---------------- agent SSE + Kokoro audio queue ----------------
  const audioQueue = []; let playing = false;

  // Fetch in parallel, play strictly in sentence order: each sentence reserves a slot (promise).
  function enqueueTTS(sentence) {
    if (!config?.kokoro?.enabled) return;
    const p = fetch(bridge + '/tts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: sentence, voice, speed }),
    }).then(async r => {
      if (!r.ok) return null;
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      return audioCtx.decodeAudioData(await r.arrayBuffer());
    }).catch(e => { console.error('tts', e); return null; });
    audioQueue.push(p);
    if (!playing) playNext();
  }

  function playNext() {
    if (audioQueue.length === 0) { playing = false; if (!listening) setState('idle', 'Idle'); return; }
    playing = true;
    audioQueue.shift().then(buffer => {
    if (!buffer) { playNext(); return; }
    setState('speaking', 'Speaking…');
    const src = audioCtx.createBufferSource(); src.buffer = buffer;
    const gain = audioCtx.createGain(); gain.gain.value = volume;
    src.connect(gain).connect(audioCtx.destination);
    src.onended = playNext; src.start();
    });
  }

  function sendToAgent(text) {
    if (!text) return;
    partialEl.textContent = text;
    setState('idle', 'Agent thinking…');
    const sessionId = agentSel.value;
    fetch(bridge + '/agent', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, text }),
    }).then(async (resp) => {
      const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = '', reply = '';
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, idx).replace(/^data: /, ''); buf = buf.slice(idx + 2);
          if (!line.trim()) continue;
          const ev = JSON.parse(line);
          if (ev.type === 'sentence') enqueueTTS(ev.text);       // start speaking on first sentence
          else if (ev.type === 'delta') { reply += ev.text; partialEl.textContent = reply.slice(-80); }
          else if (ev.type === 'error') statusEl.textContent = ev.text;
        }
      }
    }).catch(e => { statusEl.textContent = 'Agent error'; console.error(e); });
  }

  // ---------------- waveform ----------------
  function drawWave(stream) {
    const ac = audioCtx; const an = ac.createAnalyser(); an.fftSize = 256;
    ac.createMediaStreamSource(stream).connect(an);
    const data = new Uint8Array(an.frequencyBinCount); const ctx = waveCanvas.getContext('2d');
    (function loop() {
      if (!listening) { ctx.clearRect(0, 0, waveCanvas.width, waveCanvas.height); return; }
      an.getByteTimeDomainData(data);
      ctx.clearRect(0, 0, waveCanvas.width, waveCanvas.height);
      ctx.lineWidth = 2; ctx.strokeStyle = '#22d3ee'; ctx.beginPath();
      const slice = waveCanvas.width / data.length;
      for (let i = 0; i < data.length; i++) {
        const y = (data[i] / 255) * waveCanvas.height, x = i * slice;
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.stroke(); requestAnimationFrame(loop);
    })();
  }

  // ---------------- settings drawer ----------------
  const drawer = $('#drawer');
  $('#gearBtn').onclick = () => { drawer.classList.toggle('hidden'); refreshModels(); };
  $('#closeDrawer').onclick = () => drawer.classList.add('hidden');
  document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.querySelectorAll('.tabpane').forEach(p => p.classList.toggle('hidden', p.dataset.pane !== t.dataset.tab));
  });

  $('#bridgeUrl').value = bridge;
  $('#saveGeneral').onclick = async () => {
    bridge = $('#bridgeUrl').value.trim() || location.origin;
    localStorage.setItem('bridgeUrl', bridge);
    sttMode = $('#sttMode').value;
    await fetch(bridge + '/settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stt: { backend: sttMode } }),
    }).catch(() => {});
    await loadConfig();
  };

  $('#saveSession').onclick = async () => {
    const s = { id: $('#sId').value.trim(), name: $('#sName').value.trim() || $('#sId').value.trim(),
                cmd: $('#sCmd').value.trim(), mode: 'pi-json', cwd: $('#sCwd').value.trim() };
    if (!s.id || !s.cmd) return;
    const agents = (config.agents || []).filter(a => a.id !== s.id).map(a => ({ id: a.id, name: a.name, cmd: a.cmd || 'pi --mode json {text}', mode: 'pi-json', cwd: a.cwd }));
    agents.push(s);
    await fetch(bridge + '/settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agents }),
    });
    await loadConfig(); renderSessions();
  };

  function renderSessions() {
    const box = $('#sessionList'); box.innerHTML = '';
    (config.agents || []).forEach(a => {
      const d = document.createElement('div'); d.className = 'mrow';
      d.innerHTML = `<div><div>${a.name}</div><div class="meta">${a.cwd || '(no cwd)'}</div></div>`;
      box.appendChild(d);
    });
  }

  function populateVoices(voices) {
    const vs = $('#voiceSel'); vs.innerHTML = '';
    (voices.length ? voices : [voice]).forEach(v => {
      const o = document.createElement('option'); o.value = v; o.textContent = v; if (v === voice) o.selected = true; vs.appendChild(o);
    });
  }
  $('#speedSel').oninput = (e) => { speed = parseFloat(e.target.value); $('#speedVal').textContent = speed.toFixed(2) + '×'; };
  $('#volSel').oninput = (e) => { volume = parseFloat(e.target.value); };
  $('#saveVoice').onclick = async () => {
    voice = $('#voiceSel').value;
    await fetch(bridge + '/settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kokoro: { voice, speed } }),
    });
  };

  async function refreshModels() {
    try {
      const models = await window.ModelManager.list();
      ['stt-browser', 'stt-server', 'tts'].forEach(role =>
        window.ModelManager.render(drawer, models, role, refreshModels));
    } catch (_) {}
  }

  micBtn.onclick = startListening;
  loadConfig().then(() => { renderSessions(); });
})();
