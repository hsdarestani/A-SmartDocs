(() => {
  const root = document.querySelector('.live-editor');
  if (!root) return;
  document.querySelectorAll('.live-text-layer').forEach(layer => {
    layer.addEventListener('dblclick', async event => {
      if (event.target !== layer) return;
      const rect = layer.getBoundingClientRect();
      const text = window.prompt('Text für diese Stelle');
      if (!text) return;
      const data = JSON.parse(document.getElementById('liveWorkspaceData').textContent || '{}');
      const page = Number(layer.dataset.pageLayer || 1);
      const response = await fetch(`/api/workspace/${data.entwurf_id}/edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          nachricht: text,
          seite: page,
          x: (event.clientX - rect.left) / rect.width,
          y: (event.clientY - rect.top) / rect.height
        })
      });
      if (response.ok) window.location.reload();
    });
  });
})();
