(() => {
  'use strict';
  const bereich = document.querySelector('#hochladeBereich');
  const eingabe = document.querySelector('#dateiEingabe');
  const starten = document.querySelector('#analyseStarten');
  if (!bereich || !eingabe) return;

  function dateiUebernehmen(datei) {
    if (!datei) return;
    window.smartDocsAusgewaehlteDatei = datei;
    try {
      const transfer = new DataTransfer();
      transfer.items.add(datei);
      eingabe.files = transfer.files;
    } catch {
      // Safari erlaubt das Setzen von input.files nicht immer. analysis-flow.js
      // verwendet deshalb zusätzlich window.smartDocsAusgewaehlteDatei.
    }
    eingabe.dispatchEvent(new Event('change', { bubbles: true }));
    if (starten) starten.disabled = false;
  }

  ['dragenter', 'dragover'].forEach(art => bereich.addEventListener(art, ereignis => {
    ereignis.preventDefault();
    ereignis.stopPropagation();
    bereich.classList.add('darueber');
  }, true));
  ['dragleave', 'drop'].forEach(art => bereich.addEventListener(art, ereignis => {
    ereignis.preventDefault();
    ereignis.stopPropagation();
    bereich.classList.remove('darueber');
  }, true));
  bereich.addEventListener('drop', ereignis => dateiUebernehmen(ereignis.dataTransfer?.files?.[0]), true);
  eingabe.addEventListener('change', () => {
    if (eingabe.files?.[0]) window.smartDocsAusgewaehlteDatei = eingabe.files[0];
  });
  document.querySelector('#dateiEntfernen')?.addEventListener('click', () => {
    window.smartDocsAusgewaehlteDatei = null;
  });
})();
