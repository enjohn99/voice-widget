// model-manager.js - GUI model manager. Lists installed vs available per role, select + download (progress).
window.ModelManager = (function () {
  let bridge = '';
  function setBridge(url) { bridge = url.replace(/\/$/, ''); }

  async function list() {
    const r = await fetch(bridge + '/models');
    return (await r.json()).models || [];
  }
  async function select(role, id) {
    await fetch(bridge + '/models/select', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role, id }),
    });
  }
  // SSE download with progress callback. mock=true for offline testing.
  function download(id, onProgress, mock) {
    return new Promise((resolve, reject) => {
      fetch(bridge + '/models/download', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, mock: !!mock }),
      }).then(async (resp) => {
        const reader = resp.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let idx;
          while ((idx = buf.indexOf('\n\n')) >= 0) {
            const line = buf.slice(0, idx).replace(/^data: /, '');
            buf = buf.slice(idx + 2);
            if (!line.trim()) continue;
            try {
              const ev = JSON.parse(line);
              onProgress(ev);
              if (ev.done) resolve(ev);
              if (ev.error) reject(new Error(ev.error));
            } catch (_) {}
          }
        }
        resolve({ done: true });
      }).catch(reject);
    });
  }

  function render(container, models, role, onChange) {
    const list = container.querySelector(`.role-group[data-role="${role}"] .mlist`);
    if (!list) return;
    list.innerHTML = '';
    models.filter(m => m.role === role).forEach(m => {
      const row = document.createElement('div');
      row.className = 'mrow';
      row.innerHTML = `<div><div>${m.name}</div>
        <div class="meta">${m.approx_mb} MB · ${m.license}</div>
        <div class="prog"></div></div>
        <div class="btns"></div>`;
      const btns = row.querySelector('.btns');
      if (!m.installed) {
        const dl = document.createElement('button');
        dl.className = 'b-dl'; dl.textContent = 'Download';
        dl.onclick = async () => {
          dl.textContent = '…';
          const prog = row.querySelector('.prog');
          await download(m.id, (ev) => { if (ev.pct != null) prog.style.width = ev.pct + '%'; }, m.role === 'stt-browser' ? false : false);
          onChange();
        };
        btns.appendChild(dl);
      }
      const sel = document.createElement('button');
      sel.className = m.active ? 'b-active' : 'b-sel';
      sel.textContent = m.active ? 'Active' : 'Select';
      sel.onclick = async () => { await select(role, m.id); onChange(); };
      btns.appendChild(sel);
      list.appendChild(row);
    });
  }

  return { setBridge, list, select, download, render };
})();
