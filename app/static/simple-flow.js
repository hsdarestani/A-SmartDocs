(() => {
  'use strict';

  const warten = dauer => new Promise(resolve => window.setTimeout(resolve, dauer));

  async function fetchMitZeitlimit(url, optionen = {}, dauer = 10000) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), dauer);
    try {
      return await fetch(url, { ...optionen, signal: controller.signal });
    } finally {
      window.clearTimeout(timer);
    }
  }

  function editorEinrichten() {
    const form = document.querySelector('#workflowChatForm');
    const dialog = document.querySelector('#workflowDialog');
    const vorlageId = Number(document.querySelector('#workflowVorlageId')?.value || 0);
    if (!form || !dialog || !vorlageId) return;

    const textfeld = document.querySelector('#workflowChatText');
    const senden = form.querySelector('button[type="submit"]');
    let laeuft = false;

    const nachricht = (rolle, text, klasse = '') => {
      const element = document.createElement('div');
      element.className = `dialognachricht ${rolle} ${klasse}`.trim();
      element.textContent = text;
      dialog.appendChild(element);
      dialog.scrollTop = dialog.scrollHeight;
      return element;
    };

    const sperren = aktiv => {
      laeuft = aktiv;
      form.classList.toggle('verarbeitet', aktiv);
      if (textfeld) textfeld.disabled = aktiv;
      if (senden) senden.disabled = aktiv;
    };

    async function statusAbwarten(statusUrl, statusElement) {
      let netzfehler = 0;
      while (true) {
        await warten(1200);
        let antwort;
        try {
          antwort = await fetchMitZeitlimit(statusUrl, { headers: { Accept: 'application/json' } }, 8000);
          netzfehler = 0;
        } catch {
          netzfehler += 1;
          statusElement.textContent = netzfehler > 2
            ? 'Die Bearbeitung läuft weiter. Die Verbindung wird wiederhergestellt …'
            : 'A+ bearbeitet die Änderung …';
          continue;
        }

        let inhalt = {};
        try { inhalt = await antwort.json(); } catch { /* nächster Poll */ }
        if (!antwort.ok) {
          statusElement.textContent = inhalt.detail || 'Der Bearbeitungsstatus konnte nicht geladen werden.';
          sperren(false);
          return;
        }
        if (inhalt.fertig) {
          statusElement.textContent = inhalt.antwort || 'Die Änderung wurde übernommen.';
          statusElement.classList.remove('auftrag-laeuft');
          statusElement.classList.add('auftrag-fertig');
          window.setTimeout(() => window.location.reload(), 650);
          return;
        }
        if (inhalt.fehler) {
          statusElement.textContent = inhalt.antwort || 'Die automatische Bearbeitung konnte nicht abgeschlossen werden.';
          statusElement.classList.remove('auftrag-laeuft');
          statusElement.classList.add('auftrag-fehler');
          sperren(false);
          textfeld?.focus();
          return;
        }
        statusElement.textContent = 'A+ bearbeitet die Änderung im Hintergrund …';
      }
    }

    async function sendenUndVerfolgen(text, nutzernachrichtZeigen = true) {
      if (!text || laeuft) return;
      sperren(true);
      if (nutzernachrichtZeigen) nachricht('nutzer', text);
      if (textfeld) textfeld.value = '';
      const statusElement = nachricht('assistent', 'A+ bearbeitet die Änderung im Hintergrund …', 'auftrag-laeuft');

      try {
        const antwort = await fetchMitZeitlimit('/api/vorlagen/korrigieren-async', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ vorlage_id: vorlageId, nachricht: text }),
        }, 10000);
        const inhalt = await antwort.json();
        if (!antwort.ok) throw new Error(inhalt.detail || 'Die Änderung konnte nicht gestartet werden.');
        await statusAbwarten(inhalt.status_url, statusElement);
      } catch (fehler) {
        statusElement.textContent = fehler.name === 'AbortError'
          ? 'Die Verbindung zum Server war kurz unterbrochen. Bitte laden Sie die Seite neu; ein bereits gestarteter Auftrag läuft weiter.'
          : (fehler.message || 'Die Änderung konnte nicht gestartet werden.');
        statusElement.classList.remove('auftrag-laeuft');
        statusElement.classList.add('auftrag-fehler');
        sperren(false);
        textfeld?.focus();
      }
    }

    form.addEventListener('submit', ereignis => {
      ereignis.preventDefault();
      ereignis.stopImmediatePropagation();
      const text = textfeld?.value.trim() || '';
      sendenUndVerfolgen(text);
    }, true);

    document.addEventListener('click', ereignis => {
      const knopf = ereignis.target.closest('[data-chat-vorschlag]');
      if (!knopf || !form.contains(knopf) && !document.querySelector('#workflowChatPanel')?.contains(knopf)) return;
      ereignis.preventDefault();
      ereignis.stopImmediatePropagation();
      sendenUndVerfolgen(knopf.dataset.chatVorschlag || '');
    }, true);

    try {
      const schema = JSON.parse(document.querySelector('#workflowSchema')?.textContent || '{}');
      const auftrag = schema?._chat_auftrag;
      if (auftrag?.status === 'laeuft' && auftrag.id) {
        sperren(true);
        const statusElement = nachricht('assistent', 'Die zuletzt gesendete Änderung wird weiter verarbeitet …', 'auftrag-laeuft');
        statusAbwarten(`/api/vorlagen/${vorlageId}/korrektur-status/${auftrag.id}`, statusElement);
      }
    } catch { /* kein fortzusetzender Auftrag */ }
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
