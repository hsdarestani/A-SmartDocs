(() => {
  'use strict';

  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : String(input?.url || '');
    if (!url.includes('/api/vorlagen/korrigieren')) return originalFetch(input, init);

    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 30000);
    if (init.signal) {
      if (init.signal.aborted) controller.abort();
      else init.signal.addEventListener('abort', () => controller.abort(), { once: true });
    }
    try {
      return await originalFetch(input, { ...init, signal: controller.signal });
    } catch (fehler) {
      if (controller.signal.aborted) {
        throw new Error('Die Änderung dauert zu lange. Bitte senden Sie sie erneut. Ihre bisherigen Änderungen bleiben erhalten.');
      }
      throw fehler;
    } finally {
      window.clearTimeout(timer);
    }
  };

  function editorEinrichten() {
    const form = document.querySelector('#workflowChatForm');
    const dialog = document.querySelector('#workflowDialog');
    if (!form || !dialog) return;

    let laeuft = false;
    const textfeld = document.querySelector('#workflowChatText');
    const senden = form.querySelector('button[type="submit"]');

    const beenden = () => {
      laeuft = false;
      form.classList.remove('verarbeitet');
      if (textfeld) textfeld.disabled = false;
      if (senden) senden.disabled = false;
      [...dialog.querySelectorAll('.dialognachricht.assistent')].forEach((element, index, liste) => {
        if (/Ich passe die Feldvorschläge an/.test(element.textContent || '') && index < liste.length - 1) element.remove();
      });
    };

    const beobachten = () => {
      const observer = new MutationObserver(() => {
        const nachrichten = [...dialog.querySelectorAll('.dialognachricht.assistent')];
        const letzte = nachrichten.at(-1)?.textContent || '';
        if (letzte && !/Ich passe die Feldvorschläge an/.test(letzte)) {
          observer.disconnect();
          beenden();
        }
      });
      observer.observe(dialog, { childList: true });
      window.setTimeout(() => { observer.disconnect(); beenden(); }, 32000);
    };

    form.addEventListener('submit', ereignis => {
      if (laeuft) {
        ereignis.preventDefault();
        ereignis.stopImmediatePropagation();
        return;
      }
      laeuft = true;
      form.classList.add('verarbeitet');
      if (textfeld) textfeld.disabled = true;
      if (senden) senden.disabled = true;
      beobachten();
    }, true);
  }

  function formularEinrichten() {
    const abschnitte = [...document.querySelectorAll('.formular-abschnitt')];
    if (!abschnitte.length) return;
    const zurueck = document.querySelector('#formularZurueck');
    const weiter = document.querySelector('#formularWeiter');
    const abschluss = document.querySelector('.formularabschluss');
    const anzeige = document.querySelector('#formularSchrittAnzeige');
    let index = 0;

    const zeigen = neu => {
      index = Math.max(0, Math.min(abschnitte.length - 1, neu));
      abschnitte.forEach((abschnitt, i) => {
        abschnitt.hidden = i !== index;
        abschnitt.open = i === index;
      });
      if (zurueck) zurueck.disabled = index === 0;
      if (weiter) weiter.hidden = index === abschnitte.length - 1;
      if (abschluss) abschluss.hidden = index !== abschnitte.length - 1;
      if (anzeige) anzeige.textContent = `${index + 1} / ${abschnitte.length}`;
      abschnitte[index]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    zurueck?.addEventListener('click', () => zeigen(index - 1));
    weiter?.addEventListener('click', () => {
      const ungueltig = abschnitte[index].querySelector(':invalid');
      if (ungueltig) return ungueltig.reportValidity();
      zeigen(index + 1);
    });
    if (abschnitte.length === 1) document.querySelector('#formularSchritte')?.setAttribute('hidden', '');
    zeigen(0);
  }

  document.addEventListener('DOMContentLoaded', () => {
    editorEinrichten();
    formularEinrichten();
  });
})();
