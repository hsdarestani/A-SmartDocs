(() => {
  const root = document.querySelector('.live-editor');
  if (!root) return;

  const dataEl = document.getElementById('liveWorkspaceData');
  let data = {};
  try { data = JSON.parse(dataEl?.textContent || '{}'); } catch { return; }
  const entwurfId = Number(data.entwurf_id || root.dataset.entwurfId || 0);
  const hint = document.getElementById('liveDocumentHint');
  data.edits = Array.isArray(data.edits) ? data.edits : [];

  const closeEditor = () => document.querySelectorAll('.live-free-editor-shell').forEach(el => el.remove());

  const pageMeta = page => {
    const article = document.querySelector(`.live-page[data-page="${page}"]`);
    const layer = article?.querySelector('.live-text-layer');
    if (!article || !layer) return null;
    return {
      article,
      layer,
      width: Number(article.dataset.pageWidth || 1),
      height: Number(article.dataset.pageHeight || 1)
    };
  };

  const refreshPage = (page, revision) => {
    const image = document.querySelector(`[data-page-image="${page}"]`);
    if (image) image.src = `/workspace/${entwurfId}/seiten/${page}.png?rev=${revision || Date.now()}&t=${Date.now()}`;
  };

  const refreshPages = (pages, revision) => {
    [...new Set((pages || []).map(Number).filter(Boolean))].forEach(page => refreshPage(page, revision));
  };

  const syncEdit = edit => {
    if (!edit?.id) return;
    const index = data.edits.findIndex(item => item.id === edit.id);
    const old = index >= 0 ? data.edits[index] : {};
    const next = { ...old, ...edit };
    if (index >= 0) data.edits[index] = next;
    else data.edits.push(next);
  };

  const removeEdit = editId => {
    data.edits = data.edits.filter(item => item.id !== editId);
  };

  const editPosition = edit => {
    const meta = pageMeta(Number(edit.seite || 1));
    const bbox = Array.isArray(edit.bbox) ? edit.bbox.map(Number) : null;
    if (!meta || !bbox || bbox.length < 4 || !meta.width || !meta.height) return null;
    const fs = Number(edit.schriftgroesse || Math.max(8, bbox[3] - bbox[1]));
    const text = String(edit.neuer_text || '');
    const rawWidth = Math.max(10, bbox[2] - bbox[0]);
    const clickableWidth = Math.min(rawWidth, Math.max(fs * 2.2, text.length * fs * 0.56 + 8));
    return {
      meta,
      x: bbox[0] / meta.width,
      y: bbox[1] / meta.height,
      width: clickableWidth / meta.width,
      height: Math.max(12, bbox[3] - bbox[1]) / meta.height
    };
  };

  const objectAction = async payload => {
    const response = await fetch(`/api/workspace/${entwurfId}/free-object`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `Serverfehler ${response.status}`);
    return result;
  };

  const deleteFreeEdit = async edit => {
    if (!edit?.id) return;
    if (hint) hint.textContent = 'Text wird gelöscht …';
    try {
      const result = await objectAction({ aktion: 'loeschen', edit_id: edit.id });
      removeEdit(edit.id);
      closeEditor();
      refreshPages(result.seiten, result.revision);
      renderFreeValues();
      if (hint) hint.textContent = 'Gelöscht · mit ↶ oben können Sie die letzte Änderung bei Bedarf zurücknehmen.';
    } catch (error) {
      if (hint) hint.textContent = `Löschen nicht möglich: ${error.message}`;
    }
  };

  const moveFreeEdit = async (edit, page, x, y, previewButton = null) => {
    if (!edit?.id) return;
    if (hint) hint.textContent = 'Neue Position wird gespeichert …';
    try {
      const result = await objectAction({ aktion: 'verschieben', edit_id: edit.id, seite: page, x, y });
      if (result.edit) syncEdit(result.edit);
      refreshPages(result.seiten, result.revision);
      renderFreeValues();
      if (hint) hint.textContent = 'Verschoben · ziehen zum erneuten Verschieben, klicken zum Bearbeiten.';
    } catch (error) {
      previewButton?.classList.remove('dragging');
      renderFreeValues();
      if (hint) hint.textContent = `Verschieben nicht möglich: ${error.message}`;
    }
  };

  const openEditor = ({ page, x, y, edit = null }) => {
    closeEditor();
    const meta = pageMeta(page);
    if (!meta) return;

    const shell = document.createElement('div');
    shell.className = 'live-free-editor-shell';
    shell.style.left = `${Math.max(0, Math.min(.94, x)) * 100}%`;
    shell.style.top = `${Math.max(0, Math.min(.97, y)) * 100}%`;

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'live-free-editor';
    input.placeholder = 'Text eingeben …';
    input.value = String(edit?.neuer_text || '');
    input.setAttribute('aria-label', edit ? 'Eingefügten Text bearbeiten' : 'Text an dieser Stelle einfügen');

    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'live-free-save';
    save.textContent = 'Speichern';
    save.setAttribute('aria-label', 'Text speichern');

    let remove = null;
    if (edit?.id) {
      remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'live-free-delete';
      remove.textContent = 'Löschen';
      remove.setAttribute('aria-label', 'Eingefügten Text löschen');
    }

    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'live-free-cancel';
    cancel.textContent = '×';
    cancel.setAttribute('aria-label', 'Abbrechen');

    shell.append(input, save);
    if (remove) shell.append(remove);
    shell.append(cancel);
    meta.layer.appendChild(shell);
    if (hint) hint.textContent = edit
      ? 'Text ändern, ziehen zum Verschieben oder „Löschen“ wählen.'
      : 'Text eingeben und auf „Speichern“ klicken. Enter geht ebenfalls.';

    requestAnimationFrame(() => {
      try { input.focus({ preventScroll: true }); } catch { input.focus(); }
      if (edit) input.select();
    });

    const setBusy = busy => {
      input.disabled = busy;
      save.disabled = busy;
      cancel.disabled = busy;
      if (remove) remove.disabled = busy;
      shell.classList.toggle('saving', busy);
    };

    const speichern = async () => {
      const text = input.value.trim();
      if (!text || save.disabled) return;
      setBusy(true);
      try {
        const payload = edit?.id
          ? { nachricht: text, edit_id: edit.id }
          : { nachricht: text, seite: page, x, y };
        const response = await fetch(`/api/workspace/${entwurfId}/edit`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || `Serverfehler ${response.status}`);
        const changed = result.edits?.[0];
        if (changed) syncEdit(changed);
        refreshPage(page, result.revision);
        closeEditor();
        renderFreeValues(page);
        if (hint) hint.textContent = edit
          ? 'Text aktualisiert · ziehen zum Verschieben oder erneut anklicken zum Bearbeiten.'
          : 'Eingefügt · ziehen zum Verschieben, anklicken zum Bearbeiten.';
      } catch (error) {
        setBusy(false);
        shell.title = error.message;
      }
    };

    save.addEventListener('click', speichern);
    remove?.addEventListener('click', () => deleteFreeEdit(edit));
    cancel.addEventListener('click', () => {
      closeEditor();
      if (hint) hint.textContent = 'Text anklicken zum Ersetzen · freie Stelle anklicken zum Einfügen · Checkbox direkt anklicken.';
    });
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        cancel.click();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        speichern();
      }
    });
  };

  const bindFreeValue = (button, edit, pos) => {
    let start = null;
    let dragged = false;
    let startLeft = 0;
    let startTop = 0;
    let layerRect = null;
    let buttonRect = null;

    button.addEventListener('pointerdown', event => {
      if (event.button !== undefined && event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      closeEditor();
      layerRect = pos.meta.layer.getBoundingClientRect();
      buttonRect = button.getBoundingClientRect();
      start = { x: event.clientX, y: event.clientY, pointerId: event.pointerId };
      startLeft = buttonRect.left - layerRect.left;
      startTop = buttonRect.top - layerRect.top;
      dragged = false;
      button.classList.add('selected');
      try { button.setPointerCapture(event.pointerId); } catch { /* optional */ }
    });

    button.addEventListener('pointermove', event => {
      if (!start || event.pointerId !== start.pointerId || !layerRect || !buttonRect) return;
      const dx = event.clientX - start.x;
      const dy = event.clientY - start.y;
      if (!dragged && Math.hypot(dx, dy) < 4) return;
      dragged = true;
      button.classList.add('dragging');
      const maxLeft = Math.max(0, layerRect.width - buttonRect.width);
      const maxTop = Math.max(0, layerRect.height - buttonRect.height);
      const left = Math.max(0, Math.min(maxLeft, startLeft + dx));
      const top = Math.max(0, Math.min(maxTop, startTop + dy));
      button.style.left = `${(left / layerRect.width) * 100}%`;
      button.style.top = `${(top / layerRect.height) * 100}%`;
      if (hint) hint.textContent = 'Loslassen, um die neue Position zu speichern.';
    });

    const finishPointer = async event => {
      if (!start || event.pointerId !== start.pointerId) return;
      try { button.releasePointerCapture(event.pointerId); } catch { /* optional */ }
      const wasDragged = dragged;
      start = null;
      button.classList.remove('selected');
      if (!wasDragged) {
        button.classList.remove('dragging');
        return;
      }
      button.dataset.suppressClick = '1';
      const current = button.getBoundingClientRect();
      const currentLayer = pos.meta.layer.getBoundingClientRect();
      const x = Math.max(0, Math.min(1, (current.left - currentLayer.left) / currentLayer.width));
      const y = Math.max(0, Math.min(1, (current.top - currentLayer.top) / currentLayer.height));
      await moveFreeEdit(edit, Number(edit.seite), x, y, button);
    };

    button.addEventListener('pointerup', finishPointer);
    button.addEventListener('pointercancel', event => {
      if (start && event.pointerId === start.pointerId) {
        start = null;
        dragged = false;
        renderFreeValues(Number(edit.seite));
      }
    });

    button.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      if (button.dataset.suppressClick === '1') {
        delete button.dataset.suppressClick;
        return;
      }
      openEditor({ page: Number(edit.seite), x: pos.x, y: pos.y, edit });
    });

    button.addEventListener('keydown', event => {
      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        event.stopPropagation();
        deleteFreeEdit(edit);
      }
    });
  };

  const renderFreeValues = pageFilter => {
    const selector = pageFilter ? `.live-page[data-page="${pageFilter}"] .live-free-value` : '.live-free-value';
    document.querySelectorAll(selector).forEach(el => el.remove());
    data.edits
      .filter(edit => edit?.quelle === 'freie-position' && String(edit.neuer_text || '').trim())
      .filter(edit => !pageFilter || Number(edit.seite) === Number(pageFilter))
      .forEach(edit => {
        const pos = editPosition(edit);
        if (!pos) return;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'live-free-value';
        button.dataset.editId = edit.id;
        button.title = `„${String(edit.neuer_text || '').slice(0, 80)}“ · ziehen zum Verschieben · klicken zum Bearbeiten`;
        button.setAttribute('aria-label', `Eingefügten Text ${String(edit.neuer_text || '').slice(0, 80)} verschieben oder bearbeiten`);
        button.style.left = `${pos.x * 100}%`;
        button.style.top = `${pos.y * 100}%`;
        button.style.width = `${Math.max(.018, pos.width) * 100}%`;
        button.style.height = `${Math.max(.014, pos.height) * 100}%`;
        bindFreeValue(button, edit, pos);
        pos.meta.layer.appendChild(button);
      });
  };

  const checkboxAt = async (page, x, y) => {
    try {
      const response = await fetch(`/api/workspace/${entwurfId}/checkbox-at`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seite: page, x, y })
      });
      const result = await response.json();
      if (!response.ok) return false;
      if (!result.treffer) return false;
      refreshPage(page, result.revision);
      if (hint) hint.textContent = result.checked ? 'Checkbox markiert · erneut anklicken zum Entfernen.' : 'Checkbox-Markierung entfernt · erneut anklicken zum Setzen.';
      return true;
    } catch {
      return false;
    }
  };

  document.querySelectorAll('.live-text-layer').forEach(layer => {
    layer.addEventListener('click', async event => {
      if (event.target !== layer) return;
      event.preventDefault();
      closeEditor();

      const rect = layer.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
      const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
      const page = Number(layer.dataset.pageLayer || layer.closest('.live-page')?.dataset.page || 1);

      layer.classList.add('checking-click');
      const wasCheckbox = await checkboxAt(page, x, y);
      layer.classList.remove('checking-click');
      if (wasCheckbox) return;
      openEditor({ page, x, y });
    });
  });

  document.addEventListener('pointerdown', event => {
    if (!event.target.closest('.live-free-editor-shell') && !event.target.closest('.live-free-value')) {
      document.querySelectorAll('.live-free-editor-shell').forEach(editor => {
        if (!editor.contains(event.target) && !event.target.closest('.live-text-layer')) editor.remove();
      });
    }
  });

  renderFreeValues();
})();
