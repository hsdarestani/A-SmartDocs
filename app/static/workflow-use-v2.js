(() => {
  'use strict';
  const felder = [...document.querySelectorAll('.dynamisches-feld[data-feld-schluessel]')];
  if (!felder.length || !document.querySelector('#liveFormPages')) return;

  const wertAusFeld = container => {
    const textfeld = container.querySelector('input[type="text"],input[type="number"],input[type="date"],textarea');
    if (textfeld) return textfeld.value || '';
    const radio = container.querySelector('input[type="radio"]:checked');
    if (radio) return radio.value || '';
    const checkbox = container.querySelector('input[type="checkbox"]');
    if (checkbox) return checkbox.checked ? '✓' : '';
    const datei = container.querySelector('input[type="file"]');
    return datei?.files?.[0]?.name || '';
  };

  function aktivieren(container) {
    felder.forEach(feld => feld.classList.toggle('aktiv', feld === container));
    const seite = Number(container.dataset.seite || 1);
    const page = document.querySelector(`.live-form-page[data-seite="${seite}"]`);
    if (!page) return;
    document.querySelectorAll('.live-form-marker').forEach(marker => marker.classList.remove('aktiv'));
    const marker = page.querySelector('.live-form-marker');
    if (!marker) return;
    marker.style.left = `${Number(container.dataset.x || 0) * 100}%`;
    marker.style.top = `${Number(container.dataset.y || 0) * 100}%`;
    marker.style.width = `${Number(container.dataset.breite || .25) * 100}%`;
    marker.style.height = `${Number(container.dataset.hoehe || .04) * 100}%`;
    marker.querySelector('span').textContent = container.dataset.feldLabel || 'Aktuelles Feld';
    marker.querySelector('output').textContent = wertAusFeld(container);
    marker.classList.add('aktiv');
    page.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const hinweis = document.querySelector('#livePreviewHinweis');
    if (hinweis) hinweis.textContent = `„${container.dataset.feldLabel || 'Feld'}“ · Seite ${seite}`;
  }

  felder.forEach(container => {
    container.querySelectorAll('input,textarea,select,label').forEach(element => {
      element.addEventListener('focus', () => aktivieren(container), true);
      element.addEventListener('click', () => aktivieren(container));
      element.addEventListener('input', () => aktivieren(container));
      element.addEventListener('change', () => aktivieren(container));
    });
  });

  const first = felder[0];
  if (first) window.setTimeout(() => aktivieren(first), 150);
})();
