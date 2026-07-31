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

  const syncEdit = edit => {
    if (!edit?.id) return;
    const index = data.edits.findIndex(item => item.id === edit.id);
    const old = index >= 0 ? data.edits[index] : {};
    const next = { ...old, ...edit };
    if (index >= 0) data.edits[index] = next;
    else data.edits.push(next);
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

    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'live-free-cancel';
    cancel.textContent = '×';
    cancel.setAttribute('aria-label', 'Abbrechen');

    shell.append(input, save, cancel);
    meta.layer.appendChild(shell);
    if (hint) hint.textContent = edit
      ? 'Eingefügten Text ändern und auf „Speichern“ klicken. Enter geht ebenfalls.'
      : 'Text eingeben und auf „Speichern“ klicken. Enter geht ebenfalls.';

    requestAnimationFrame(() => {
      try { input.focus({ preventScroll: true }); } catch { input.focus(); }
      if (edit) input.select();
    });

    const speichern = async () => {
      const text = input.value.trim();
      if (!text || save.disabled) return;
      input.disabled = true;
      save.disabled = true;
      cancel.disabled = true;
      shell.classList.add('saving');
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
        if (hint) hint.textContent = edit ? 'Text aktualisiert · zum erneuten Bearbeiten einfach wieder anklicken.' : 'Eingefügt · der neue Text bleibt anklickbar und kann jederzeit geändert werden.';
      } catch (error) {
        input.disabled = false;
        save.disabled = false;
        cancel.disabled = false;
        shell.classList.remove('saving');
        shell.title = error.message;
      }
    };

    save.addEventListener('click', speichern);
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
        button.title = `„${String(edit.neuer_text || '').slice(0, 80)}“ bearbeiten`;
        button.setAttribute('aria-label', `Eingefügten Text ${String(edit.neuer_text || '').slice(0, 80)} bearbeiten`);
        button.style.left = `${pos.x * 100}%`;
        button.style.top = `${pos.y * 100}%`;
        button.style.width = `${Math.max(.018, pos.width) * 100}%`;
        button.style.height = `${Math.max(.014, pos.height) * 100}%`;
        button.addEventListener('click', event => {
          event.preventDefault();
          event.stopPropagation();
          openEditor({ page: Number(edit.seite), x: pos.x, y: pos.y, edit });
        });
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
