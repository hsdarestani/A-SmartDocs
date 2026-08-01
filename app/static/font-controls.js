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

  function start() {
    const root = $('.live-editor');
    const dataElement = $('#liveWorkspaceData');
    const selection = $('#liveSelection');
    const fontSelect = $('#liveSelectionFont');
    const sizeInput = $('#liveSelectionFontSize');
    const detected = $('#liveDetectedFont');
    const documentSelect = $('#liveDocumentFont');
    const preserveStyles = $('#liveDocumentPreserveStyles');
    const saveState = $('#liveSaveState');
    if (!root || !dataElement || !selection || !fontSelect || !documentSelect) return;

    let data = {};
    try { data = JSON.parse(dataElement.textContent || '{}'); } catch { return; }
    const entwurfId = Number(data.entwurf_id || root.dataset.entwurfId || 0);
    if (!entwurfId) return;
    let revision = Number(data.revision || root.dataset.revision || 0);
    const edits = Array.isArray(data.edits) ? data.edits : [];
    let fonts = [];
    let busy = false;

    const selectedAnchors = () => $$('.live-text-anchor.selected')
      .sort((a, b) => {
        const pageDiff = Number(a.dataset.page || 0) - Number(b.dataset.page || 0);
        return pageDiff || Number(a.dataset.wordOrder || 0) - Number(b.dataset.wordOrder || 0);
      });

    const currentAnchorId = () => selectedAnchors().map(anchor => anchor.dataset.anchorId).filter(Boolean).join('|');

    const optionenFuellen = select => {
      select.innerHTML = '';
      const gruppen = new Map();
      fonts.forEach(font => {
        const gruppe = font.gruppe || 'Schriften';
        if (!gruppen.has(gruppe)) {
          const optgroup = document.createElement('optgroup');
          optgroup.label = gruppe;
          gruppen.set(gruppe, optgroup);
          select.appendChild(optgroup);
        }
        const option = document.createElement('option');
        option.value = font.key;
        option.textContent = font.name;
        gruppen.get(gruppe).appendChild(option);
      });
    };

    const refreshPages = async (pages, nextRevision) => {
      revision = Number(nextRevision || revision + 1);
      root.dataset.revision = String(revision);
      const unique = [...new Set((pages || []).map(Number).filter(Boolean))];
      await Promise.all(unique.map(page => new Promise(resolve => {
        const image = $(`[data-page-image="${page}"]`);
        if (!image) return resolve();
        const next = `/workspace/${entwurfId}/seiten/${page}.png?rev=${revision}&t=${Date.now()}`;
        const test = new Image();
        test.onload = () => { image.src = next; resolve(); };
        test.onerror = () => resolve();
        test.src = next;
      })));
    };

    const setBusy = active => {
      busy = active;
      root.classList.toggle('live-font-loading', active);
      if (fontSelect) fontSelect.disabled = active;
      if (sizeInput) sizeInput.disabled = active;
      if (documentSelect) documentSelect.disabled = active;
      if (preserveStyles) preserveStyles.disabled = active;
      if (saveState) {
        saveState.textContent = active ? 'Schrift wird angewendet …' : 'Automatisch gespeichert';
        saveState.classList.toggle('live-font-state', active);
      }
    };

    const editFuerAnker = ankerId => edits.find(edit => String(edit.anker_id || '') === ankerId) || null;

    const auswahlAktualisieren = () => {
      const anchors = selectedAnchors();
      if (!anchors.length || selection.hidden) return;
      const ankerId = currentAnchorId();
      const erster = anchors[0];
      const edit = editFuerAnker(ankerId);
      const originalFont = erster.dataset.fontName || 'nicht eindeutig erkannt';
      if (detected) detected.textContent = `Erkannt: ${originalFont}`;
      fontSelect.value = String(edit?.font_key || 'auto');
      if (![...fontSelect.options].some(option => option.value === fontSelect.value)) fontSelect.value = 'auto';
      if (sizeInput) {
        const wert = edit?.font_size_user ? edit.schriftgroesse : Number(erster.dataset.fontSize || 0);
        sizeInput.value = wert ? String(Math.round(Number(wert) * 10) / 10) : '';
        sizeInput.placeholder = erster.dataset.fontSize ? `${erster.dataset.fontSize} pt` : 'Original';
      }
    };

    const auswahlSpeichern = async () => {
      if (busy) return;
      const ankerId = currentAnchorId();
      if (!ankerId) return;
      const size = sizeInput?.value.trim() ? Number(sizeInput.value) : null;
      setBusy(true);
      try {
        const result = await jsonFetch(`/api/workspace/${entwurfId}/selection-font`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ anker_id: ankerId, font_key: fontSelect.value || 'auto', font_size: size }),
        });
        if (result.seiten?.length) await refreshPages(result.seiten, result.revision);
        else revision = Number(result.revision || revision);
        window.meldung?.('Schrift für die Auswahl gespeichert.', 'erfolg');
      } catch (error) {
        window.meldung?.(error.message, 'fehler');
      } finally {
        setBusy(false);
      }
    };

    const dokumentSpeichern = async () => {
      if (busy) return;
      setBusy(true);
      try {
        const result = await jsonFetch(`/api/workspace/${entwurfId}/document-font`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ font_key: documentSelect.value || 'auto', stile_erhalten: preserveStyles?.checked !== false }),
        });
        await refreshPages(result.seiten || [], result.revision);
        window.meldung?.(
          documentSelect.value === 'auto' ? 'Originalschriften wiederhergestellt.' : 'Dokumentschrift wurde in der Vorschau angewendet.',
          'erfolg',
        );
      } catch (error) {
        window.meldung?.(error.message, 'fehler');
      } finally {
        setBusy(false);
      }
    };

    const beobachteAuswahl = () => setTimeout(auswahlAktualisieren, 0);
    $$('.live-text-anchor').forEach(anchor => {
      anchor.addEventListener('click', beobachteAuswahl);
      anchor.addEventListener('pointerup', beobachteAuswahl);
    });
    $('#liveSelectionClear')?.addEventListener('click', () => {
      if (detected) detected.textContent = '';
    });

    fontSelect.addEventListener('change', auswahlSpeichern);
    sizeInput?.addEventListener('change', auswahlSpeichern);
    documentSelect.addEventListener('change', dokumentSpeichern);
    preserveStyles?.addEventListener('change', dokumentSpeichern);

    root.classList.add('live-font-loading');
    jsonFetch(`/api/workspace/${entwurfId}/fonts`)
      .then(result => {
        fonts = Array.isArray(result.fonts) ? result.fonts : [];
        optionenFuellen(fontSelect);
        optionenFuellen(documentSelect);
        const dokumentFont = result.dokument_font || {};
        documentSelect.value = dokumentFont.font_key || 'auto';
        if (preserveStyles) preserveStyles.checked = dokumentFont.stile_erhalten !== false;
        auswahlAktualisieren();
      })
      .catch(error => window.meldung?.(error.message, 'fehler'))
      .finally(() => root.classList.remove('live-font-loading'));
  }

  document.addEventListener('DOMContentLoaded', start);
})();
