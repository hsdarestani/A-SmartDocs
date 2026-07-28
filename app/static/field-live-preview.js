(() => {
  'use strict';

  function schemaLesen() {
    try {
      return JSON.parse(document.querySelector('#workflowSchema')?.textContent || '{}');
    } catch {
      return {};
    }
  }

  function anwenden() {
    const schema = schemaLesen();
    const felder = Array.isArray(schema.felder) ? schema.felder : [];
    document.querySelectorAll('.workflow-feldbox[data-index]').forEach(box => {
      const feld = felder[Number(box.dataset.index)];
      if (!feld) return;
      box.querySelector('.workflow-feldwert')?.remove();
      const wert = String(feld.standardwert || feld.vorschauwert || '').trim();
      box.classList.toggle('hat-standardwert', Boolean(wert));
      if (!wert) return;
      const ausgabe = document.createElement('strong');
      ausgabe.className = 'workflow-feldwert';
      ausgabe.textContent = wert;
      box.appendChild(ausgabe);
      box.title = `${feld.bezeichnung || 'Feld'}: ${wert}`;
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    anwenden();
    const wurzel = document.querySelector('.workflow-editor');
    if (!wurzel) return;
    const observer = new MutationObserver(() => window.requestAnimationFrame(anwenden));
    observer.observe(wurzel, { childList: true, subtree: true });
  });

  document.addEventListener('smartdocs:schema-updated', ereignis => {
    const element = document.querySelector('#workflowSchema');
    if (element && ereignis.detail?.schema) element.textContent = JSON.stringify(ereignis.detail.schema);
    window.requestAnimationFrame(anwenden);
  });
})();
