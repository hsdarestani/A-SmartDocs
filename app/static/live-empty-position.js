(() => {
  const root = document.querySelector('.live-editor');
  if (!root) return;

  const dataEl = document.getElementById('liveWorkspaceData');
  let data = {};
  try { data = JSON.parse(dataEl?.textContent || '{}'); } catch { return; }
  const entwurfId = Number(data.entwurf_id || root.dataset.entwurfId || 0);
  const hint = document.getElementById('liveDocumentHint');

  const closeEditor = () => document.querySelectorAll('.live-free-editor').forEach(el => el.remove());

  document.querySelectorAll('.live-text-layer').forEach(layer => {
    layer.addEventListener('click', event => {
      if (event.target !== layer) return;
      event.preventDefault();
      closeEditor();

      const rect = layer.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
      const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
      const page = Number(layer.dataset.pageLayer || layer.closest('.live-page')?.dataset.page || 1);

      const editor = document.createElement('input');
      editor.type = 'text';
      editor.className = 'live-free-editor';
      editor.placeholder = 'Text eingeben …';
      editor.style.left = `${x * 100}%`;
      editor.style.top = `${y * 100}%`;
      layer.appendChild(editor);
      if (hint) hint.textContent = `Freie Stelle auf Seite ${page} gewählt · Text eingeben und Enter drücken.`;
      try { editor.focus({ preventScroll: true }); } catch { editor.focus(); }

      editor.addEventListener('keydown', async keyEvent => {
        if (keyEvent.key === 'Escape') {
          closeEditor();
          if (hint) hint.textContent = 'Text anklicken oder freie Stelle anklicken.';
          return;
        }
        if (keyEvent.key !== 'Enter') return;
        keyEvent.preventDefault();
        const text = editor.value.trim();
        if (!text || editor.disabled) return;
        editor.disabled = true;
        editor.classList.add('saving');
        try {
          const response = await fetch(`/api/workspace/${entwurfId}/edit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nachricht: text, seite: page, x, y })
          });
          const result = await response.json();
          if (!response.ok) throw new Error(result.detail || `Serverfehler ${response.status}`);
          const image = document.querySelector(`[data-page-image="${page}"]`);
          if (image) image.src = `/workspace/${entwurfId}/seiten/${page}.png?rev=${result.revision || Date.now()}&t=${Date.now()}`;
          closeEditor();
          if (hint) hint.textContent = 'Eingefügt · Text oder freie Stelle anklicken, um weiterzuarbeiten.';
        } catch (error) {
          editor.disabled = false;
          editor.classList.remove('saving');
          editor.title = error.message;
        }
      });
    });
  });
})();
