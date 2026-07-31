(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  async function jsonFetch(url, options = {}) {
    const response = await fetch(url, { credentials: 'same-origin', ...options });
    let data = {};
    try { data = await response.json(); } catch { /* ignore */ }
    if (!response.ok) throw new Error(data.detail || data.hinweis || `Serverfehler ${response.status}`);
    return data;
  }

  function uploadEinrichten() {
    const zone = $('#liveUploadZone');
    const input = $('#liveUploadInput');
    const button = $('#liveUploadButton');
    const progress = $('#liveUploadProgress');
    if (!zone || !input || !button) return;
    let laeuft = false;

    const dateiSenden = async file => {
      if (!file || laeuft) return;
      if (!/\.pdf$/i.test(file.name) && file.type !== 'application/pdf') {
        window.meldung?.('Bitte wählen Sie eine PDF-Datei aus.', 'fehler');
        return;
      }
      laeuft = true;
      progress.hidden = false;
      zone.setAttribute('aria-busy', 'true');
      const body = new FormData();
      body.append('datei', file);
      try {
        const data = await jsonFetch('/api/workspace/upload', { method: 'POST', body });
        window.location.href = data.weiter;
      } catch (error) {
        progress.hidden = true;
        zone.removeAttribute('aria-busy');
        laeuft = false;
        window.meldung?.(error.message, 'fehler');
      }
    };

    zone.addEventListener('click', event => {
      if (event.target.closest('button')) return;
      input.click();
    });
    button.addEventListener('click', event => { event.stopPropagation(); input.click(); });
    zone.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); }
    });
    input.addEventListener('change', () => dateiSenden(input.files?.[0]));
    ['dragenter', 'dragover'].forEach(type => zone.addEventListener(type, event => {
      event.preventDefault(); zone.classList.add('dragover');
    }));
    ['dragleave', 'drop'].forEach(type => zone.addEventListener(type, event => {
      event.preventDefault(); zone.classList.remove('dragover');
    }));
    zone.addEventListener('drop', event => dateiSenden(event.dataTransfer?.files?.[0]));
  }

  function editorEinrichten() {
    const root = $('.live-editor');
    const dataElement = $('#liveWorkspaceData');
    if (!root || !dataElement) return;
    let data = {};
    try { data = JSON.parse(dataElement.textContent || '{}'); } catch { return; }
    const entwurfId = Number(data.entwurf_id || root.dataset.entwurfId || 0);
    if (!entwurfId) return;

    let revision = Number(data.revision || root.dataset.revision || 0);
    let selectedAnchorId = null;
    let selectedAnchorText = '';
    let busy = false;
    let zoom = 1;

    const form = $('#liveChatForm');
    const input = $('#liveChatInput');
    const send = $('#liveChatSend');
    const messages = $('#liveChatMessages');
    const selection = $('#liveSelection');
    const selectionText = $('#liveSelectionText');
    const saveState = $('#liveSaveState');
    const latency = $('#liveLatency');

    const addMessage = (role, text, extra = '') => {
      if (!messages) return null;
      const el = document.createElement('div');
      el.className = `live-message ${role} ${extra}`.trim();
      el.textContent = text;
      messages.appendChild(el);
      messages.scrollTop = messages.scrollHeight;
      return el;
    };

    const clearSelection = () => {
      selectedAnchorId = null;
      selectedAnchorText = '';
      $$('.live-text-anchor.selected').forEach(el => el.classList.remove('selected'));
      if (selection) selection.hidden = true;
      if (input) input.placeholder = 'z. B. employee address is Mainzer Landstraße 12';
    };

    const selectAnchor = anchor => {
      clearSelection();
      selectedAnchorId = anchor.dataset.anchorId;
      selectedAnchorText = anchor.dataset.anchorText || '';
      anchor.classList.add('selected');
      if (selection) selection.hidden = false;
      if (selectionText) selectionText.textContent = selectedAnchorText;
      if (input) {
        input.placeholder = 'Neuen Text eingeben …';
        input.focus();
      }
      $('#liveDocumentHint').textContent = `„${selectedAnchorText.slice(0, 90)}“ ausgewählt · nur neuen Wert schreiben.`;
    };

    $$('.live-text-anchor').forEach(anchor => anchor.addEventListener('click', event => {
      event.preventDefault(); event.stopPropagation(); selectAnchor(anchor);
    }));
    $('#liveSelectionClear')?.addEventListener('click', clearSelection);

    const refreshPages = async pages => {
      const unique = [...new Set((pages || []).map(Number).filter(Boolean))];
      await Promise.all(unique.map(page => new Promise(resolve => {
        const image = $(`[data-page-image="${page}"]`);
        if (!image) return resolve();
        const next = `/workspace/${entwurfId}/seiten/${page}.png?rev=${revision}&t=${Date.now()}`;
        const tester = new Image();
        tester.onload = () => { image.src = next; resolve(); };
        tester.onerror = () => resolve();
        tester.src = next;
      })));
    };

    const setBusy = active => {
      busy = active;
      root.classList.toggle('loading', active);
      if (send) send.disabled = active;
      if (input) input.disabled = active;
      if (saveState) saveState.textContent = active ? 'Änderung wird angewendet …' : 'Automatisch gespeichert';
    };

    form?.addEventListener('submit', async event => {
      event.preventDefault();
      if (busy) return;
      const text = input?.value.trim() || '';
      if (!text) return;
      addMessage('user', text);
      const pending = addMessage('assistant', selectedAnchorId ? 'Wird direkt im Dokument ersetzt …' : 'Änderung wird verstanden …', 'pending');
      const anchorForRequest = selectedAnchorId;
      input.value = '';
      setBusy(true);
      const started = performance.now();
      try {
        const result = await jsonFetch(`/api/workspace/${entwurfId}/edit`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ nachricht: text, anker_id: anchorForRequest }),
        });
        revision = Number(result.revision || revision + 1);
        if (pending) { pending.textContent = result.antwort || 'Erledigt.'; pending.classList.remove('pending'); }
        await refreshPages(result.seiten || []);
        if (result.erfolg) clearSelection();
        if (latency) {
          const browserMs = Math.round(performance.now() - started);
          latency.textContent = result.modus === 'ki'
            ? `KI nur zur Zuordnung · ${browserMs} ms gesamt`
            : `Direkt ohne KI · ${Number(result.dauer_ms || browserMs)} ms Server`;
        }
        if (result.braucht_auswahl) $('#liveDocumentHint').textContent = 'Stelle unklar: gewünschten Text direkt im Dokument anklicken.';
      } catch (error) {
        if (pending) { pending.textContent = error.message; pending.classList.remove('pending'); }
        window.meldung?.(error.message, 'fehler');
      } finally {
        setBusy(false);
        input?.focus();
      }
    });

    $('#liveUndo')?.addEventListener('click', async () => {
      if (busy) return;
      setBusy(true);
      try {
        const result = await jsonFetch(`/api/workspace/${entwurfId}/undo`, { method: 'POST' });
        revision = Number(result.revision || revision + 1);
        await refreshPages(result.seiten || [1]);
        addMessage('assistant', 'Letzte Änderung wurde zurückgenommen.');
        clearSelection();
      } catch (error) {
        window.meldung?.(error.message, 'fehler');
      } finally { setBusy(false); }
    });

    $('#liveExport')?.addEventListener('click', async () => {
      if (busy) return;
      const button = $('#liveExport');
      root.classList.add('exporting');
      button.disabled = true;
      const original = button.innerHTML;
      button.textContent = 'PDF wird erstellt …';
      try {
        const result = await jsonFetch(`/api/workspace/${entwurfId}/export`, { method: 'POST' });
        const link = document.createElement('a');
        link.href = result.download_url;
        link.download = result.dateiname || 'Dokument.pdf';
        document.body.appendChild(link);
        link.click();
        link.remove();
        addMessage('assistant', 'Fertiges PDF wurde erstellt. Sie können weiterarbeiten und jederzeit erneut exportieren.');
      } catch (error) {
        window.meldung?.(error.message, 'fehler');
      } finally {
        root.classList.remove('exporting');
        button.disabled = false;
        button.innerHTML = original;
      }
    });

    const zoomApply = () => {
      zoom = Math.max(.7, Math.min(1.35, zoom));
      $('#livePages').style.width = `${zoom * 100}%`;
      $('#liveZoomValue').textContent = `${Math.round(zoom * 100)}%`;
    };
    $('#liveZoomIn')?.addEventListener('click', () => { zoom += .1; zoomApply(); });
    $('#liveZoomOut')?.addEventListener('click', () => { zoom -= .1; zoomApply(); });

    $('#liveClickHelp')?.addEventListener('click', () => {
      addMessage('assistant', 'Bewegen Sie die Maus über einen Text im PDF. Klick = Text auswählen. Danach schreiben Sie nur den neuen Wert und drücken Enter. Dabei wird keine KI benötigt.');
    });

    input?.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        form?.requestSubmit();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    uploadEinrichten();
    editorEinrichten();
  });
})();
