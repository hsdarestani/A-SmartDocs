(() => {
  'use strict';

  const schemaElement = document.querySelector('#workflowSchema');
  const vorlageElement = document.querySelector('#workflowVorlageId');
  if (!schemaElement || !vorlageElement) return;

  const $ = (auswahl, wurzel = document) => wurzel.querySelector(auswahl);
  const $$ = (auswahl, wurzel = document) => [...wurzel.querySelectorAll(auswahl)];
  const vorlageId = Number(vorlageElement.value);
  let schema;
  try { schema = JSON.parse(schemaElement.textContent || '{}'); } catch { schema = {}; }
  schema.felder = Array.isArray(schema.felder) ? schema.felder : [];
  let modus = 'chat';
  let aktivIndex = null;
  let zoom = 1;
  let drag = null;
  let ungespeichert = false;

  const sicher = text => {
    const div = document.createElement('div');
    div.textContent = String(text ?? '');
    return div.innerHTML;
  };
  const begrenzen = (wert, min, max) => Math.min(max, Math.max(min, wert));
  const typName = typ => ({ text:'Text', mehrzeilig:'Mehrzeiliger Text', datum:'Datum', zahl:'Zahl', betrag:'Betrag', auswahl:'Auswahl', kontrollfeld:'Kontrollkästchen', unterschrift:'Unterschrift', bild:'Bild', tabelle:'Tabelle' })[typ] || 'Text';
  const feldSymbol = typ => ({ text:'T', mehrzeilig:'¶', datum:'D', zahl:'#', betrag:'€', auswahl:'⌄', kontrollfeld:'✓', unterschrift:'✎', bild:'▧', tabelle:'▤' })[typ] || 'T';

  function meldung(text, art = 'erfolg') {
    if (typeof window.meldung === 'function') return window.meldung(text, art);
    const element = $('#meldung');
    if (!element) return;
    element.textContent = text;
    element.className = `meldung sichtbar ${art}`;
    window.setTimeout(() => element.classList.remove('sichtbar'), 4500);
  }

  function schemaGeaendert() {
    ungespeichert = true;
    schema.testausfuellung_geprueft = false;
    schema.testausfuellung_hash = null;
    const knopf = $('#workflowSpeichern');
    if (knopf) {
      knopf.textContent = 'Speichern •';
      knopf.classList.add('ungespeichert');
    }
  }

  function feldVervollstaendigen(feld, index) {
    const ergebnis = { ...feld };
    ergebnis.schluessel ||= `feld_${index + 1}`;
    ergebnis.bezeichnung ||= `Feld ${index + 1}`;
    ergebnis.typ ||= 'text';
    ergebnis.seite = Math.max(1, Number(ergebnis.seite || 1));
    ergebnis.pflichtfeld = Boolean(ergebnis.pflichtfeld);
    ergebnis.position = {
      x: begrenzen(Number(ergebnis.position?.x ?? .1), 0, .98),
      y: begrenzen(Number(ergebnis.position?.y ?? .1), 0, .98),
      breite: begrenzen(Number(ergebnis.position?.breite ?? .28), .025, .95),
      hoehe: begrenzen(Number(ergebnis.position?.hoehe ?? .04), .018, .7),
    };
    ergebnis.alten_inhalt_entfernen = ergebnis.alten_inhalt_entfernen ?? Boolean(String(ergebnis.beispiel || '').trim());
    ergebnis.vorschlag_status ||= ergebnis.geprueft ? 'bestaetigt' : 'vorgeschlagen';
    return ergebnis;
  }

  function normieren() {
    schema.felder = schema.felder.map(feldVervollstaendigen);
  }

  function feldMarkieren(index, drawer = false) {
    aktivIndex = Number(index);
    $$('.workflow-feldkarte').forEach(karte => karte.classList.toggle('aktiv', Number(karte.dataset.index) === aktivIndex));
    $$('.workflow-feldbox').forEach(box => box.classList.toggle('aktiv', Number(box.dataset.index) === aktivIndex));
    const feld = schema.felder[aktivIndex];
    if (!feld) return;
    const seite = $(`.workflow-seite[data-seite="${feld.seite}"]`);
    seite?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const box = $(`.workflow-feldbox[data-index="${aktivIndex}"]`);
    box?.classList.remove('pulse');
    window.requestAnimationFrame(() => box?.classList.add('pulse'));
    const hinweis = $('#workflowDokumentHinweis');
    if (hinweis) hinweis.textContent = `„${feld.bezeichnung}“ · Seite ${feld.seite} · blau hervorgehoben`;
    if (drawer) drawerOeffnen(aktivIndex);
  }

  function vorschlagBestaetigen(index) {
    const feld = schema.felder[index];
    if (!feld) return;
    feld.vorschlag_status = 'bestaetigt';
    feld.geprueft = true;
    feld.konfidenz = 1;
    feld.konfidenzstufe = 'sicher';
    schemaGeaendert();
    rendern();
    feldMarkieren(Math.min(index, schema.felder.length - 1));
  }

  function feldEntfernen(index) {
    const feld = schema.felder[index];
    if (!feld) return;
    schema.felder.splice(index, 1);
    aktivIndex = null;
    schemaGeaendert();
    rendern();
    meldung(`„${feld.bezeichnung}“ bleibt fest und wurde aus den Variablen entfernt.`);
  }

  function feldlisteRendern() {
    const liste = $('#workflowFeldListe');
    if (!liste) return;
    const suche = ($('#workflowFeldSuche')?.value || '').trim().toLowerCase();
    liste.innerHTML = '';
    schema.felder.forEach((feld, index) => {
      if (suche && !`${feld.bezeichnung} ${feld.typ}`.toLowerCase().includes(suche)) return;
      const karte = document.createElement('article');
      karte.className = `workflow-feldkarte ${feld.vorschlag_status === 'bestaetigt' ? 'bestaetigt' : 'vorgeschlagen'}`;
      karte.dataset.index = index;
      karte.innerHTML = `<button type="button" class="workflow-feldhaupt"><i>${feldSymbol(feld.typ)}</i><span><b>${sicher(feld.bezeichnung)}</b><small>${sicher(typName(feld.typ))} · Seite ${feld.seite}</small></span><em>⌖</em></button><div class="workflow-feldaktionen"><button type="button" data-aktion="bestaetigen">${feld.vorschlag_status === 'bestaetigt' ? 'Bestätigt ✓' : 'Übernehmen'}</button><button type="button" data-aktion="bearbeiten">Bearbeiten</button><button type="button" data-aktion="entfernen">Nicht variabel</button></div>`;
      $('.workflow-feldhaupt', karte).addEventListener('click', () => feldMarkieren(index));
      $('[data-aktion="bestaetigen"]', karte).addEventListener('click', () => vorschlagBestaetigen(index));
      $('[data-aktion="bearbeiten"]', karte).addEventListener('click', () => feldMarkieren(index, true));
      $('[data-aktion="entfernen"]', karte).addEventListener('click', () => feldEntfernen(index));
      liste.appendChild(karte);
    });
    const anzahl = $('#workflowFeldAnzahl');
    if (anzahl) anzahl.textContent = schema.felder.length;
  }

  function overlayRendern() {
    $$('.workflow-overlay').forEach(overlay => overlay.innerHTML = '');
    schema.felder.forEach((feld, index) => {
      const overlay = $(`.workflow-overlay[data-seite="${feld.seite}"]`);
      if (!overlay) return;
      const position = feld.position || {};
      const box = document.createElement('button');
      box.type = 'button';
      box.className = `workflow-feldbox ${feld.vorschlag_status === 'bestaetigt' ? 'bestaetigt' : 'vorgeschlagen'}`;
      box.dataset.index = index;
      box.style.left = `${Number(position.x || 0) * 100}%`;
      box.style.top = `${Number(position.y || 0) * 100}%`;
      box.style.width = `${Number(position.breite || .25) * 100}%`;
      box.style.height = `${Number(position.hoehe || .04) * 100}%`;
      box.innerHTML = `<span>${sicher(feld.bezeichnung)}</span><i class="workflow-resize" aria-hidden="true"></i>`;
      box.addEventListener('click', ereignis => {
        ereignis.stopPropagation();
        if (!drag) feldMarkieren(index, modus === 'manuell');
      });
      overlay.appendChild(box);
    });
    if (aktivIndex !== null) feldMarkieren(aktivIndex);
  }

  function rendern() {
    normieren();
    feldlisteRendern();
    overlayRendern();
  }

  function modusSetzen(neu) {
    modus = neu;
    $$('[data-workflow-modus]').forEach(knopf => knopf.classList.toggle('aktiv', knopf.dataset.workflowModus === modus));
    $('#workflowChatPanel')?.classList.toggle('aktiv', modus === 'chat');
    $('#workflowManuellPanel')?.classList.toggle('aktiv', modus === 'manuell');
    $('.workflow-editor')?.classList.toggle('manuell-aktiv', modus === 'manuell');
    const hinweis = $('#workflowDokumentHinweis');
    if (hinweis) hinweis.textContent = modus === 'manuell'
      ? 'Klicken Sie auf das Dokument, um an dieser Stelle ein neues Feld anzulegen.'
      : 'Wählen Sie einen Vorschlag oder beschreiben Sie die Änderung im Chat.';
  }

  $$('[data-workflow-modus]').forEach(knopf => knopf.addEventListener('click', () => modusSetzen(knopf.dataset.workflowModus)));
  $('#workflowFeldSuche')?.addEventListener('input', feldlisteRendern);

  function drawerOeffnen(index) {
    const feld = schema.felder[index];
    if (!feld) return;
    $('#workflowFeldIndex').value = index;
    $('#workflowFeldTitel').textContent = feld.bezeichnung;
    $('#workflowFeldBezeichnung').value = feld.bezeichnung || '';
    $('#workflowFeldTyp').value = feld.typ || 'text';
    $('#workflowFeldBeispiel').value = feld.beispiel || '';
    $('#workflowAltenInhaltEntfernen').checked = Boolean(feld.alten_inhalt_entfernen);
    $('#workflowFeldPflicht').checked = Boolean(feld.pflichtfeld);
    const drawer = $('#workflowFeldDrawer');
    drawer?.classList.add('offen');
    drawer?.setAttribute('aria-hidden', 'false');
  }
  function drawerSchliessen() {
    const drawer = $('#workflowFeldDrawer');
    drawer?.classList.remove('offen');
    drawer?.setAttribute('aria-hidden', 'true');
  }
  $('#workflowDrawerSchliessen')?.addEventListener('click', drawerSchliessen);
  $('#workflowFeldUebernehmen')?.addEventListener('click', () => {
    const index = Number($('#workflowFeldIndex').value);
    const feld = schema.felder[index];
    if (!feld) return;
    feld.bezeichnung = $('#workflowFeldBezeichnung').value.trim() || feld.bezeichnung;
    feld.typ = $('#workflowFeldTyp').value;
    feld.beispiel = $('#workflowFeldBeispiel').value.trim();
    feld.alten_inhalt_entfernen = $('#workflowAltenInhaltEntfernen').checked;
    feld.pflichtfeld = $('#workflowFeldPflicht').checked;
    feld.vorschlag_status = 'bestaetigt';
    feld.geprueft = true;
    feld.konfidenz = 1;
    feld.konfidenzstufe = 'sicher';
    schemaGeaendert();
    drawerSchliessen();
    rendern();
    feldMarkieren(index);
  });
  $('#workflowFeldEntfernen')?.addEventListener('click', () => {
    const index = Number($('#workflowFeldIndex').value);
    drawerSchliessen();
    feldEntfernen(index);
  });

  $$('.workflow-overlay').forEach(overlay => {
    overlay.addEventListener('click', ereignis => {
      if (modus !== 'manuell' || ereignis.target.closest('.workflow-feldbox')) return;
      const rect = overlay.getBoundingClientRect();
      const x = begrenzen((ereignis.clientX - rect.left) / rect.width, 0, .78);
      const y = begrenzen((ereignis.clientY - rect.top) / rect.height, 0, .92);
      const seite = Number(overlay.dataset.seite || 1);
      const index = schema.felder.length;
      schema.felder.push({
        schluessel: `feld_${Date.now()}`,
        bezeichnung: 'Neues Feld',
        typ: 'text',
        pflichtfeld: false,
        beispiel: '',
        seite,
        hinweis: 'Manuell auf dem Dokument angelegt',
        optionen: [],
        position: { x, y, breite: .22, hoehe: .04 },
        schriftgroesse: 10,
        alten_inhalt_entfernen: false,
        vorschlag_status: 'bestaetigt',
        geprueft: true,
        erkennungsquelle: 'manuell',
      });
      schemaGeaendert();
      rendern();
      feldMarkieren(index, true);
    });

    overlay.addEventListener('pointerdown', ereignis => {
      const box = ereignis.target.closest('.workflow-feldbox');
      if (!box || modus !== 'manuell') return;
      const index = Number(box.dataset.index);
      const feld = schema.felder[index];
      if (!feld) return;
      ereignis.preventDefault();
      ereignis.stopPropagation();
      box.setPointerCapture?.(ereignis.pointerId);
      const p = feld.position;
      drag = { pointerId: ereignis.pointerId, box, feld, startX: ereignis.clientX, startY: ereignis.clientY, x:p.x, y:p.y, breite:p.breite, hoehe:p.hoehe, art: ereignis.target.classList.contains('workflow-resize') ? 'resize' : 'move' };
      feldMarkieren(index);
    });
    overlay.addEventListener('pointermove', ereignis => {
      if (!drag || drag.pointerId !== ereignis.pointerId) return;
      const rect = overlay.getBoundingClientRect();
      const dx = (ereignis.clientX - drag.startX) / rect.width;
      const dy = (ereignis.clientY - drag.startY) / rect.height;
      if (drag.art === 'resize') {
        drag.feld.position.breite = begrenzen(drag.breite + dx, .025, 1 - drag.x);
        drag.feld.position.hoehe = begrenzen(drag.hoehe + dy, .018, 1 - drag.y);
        drag.box.style.width = `${drag.feld.position.breite * 100}%`;
        drag.box.style.height = `${drag.feld.position.hoehe * 100}%`;
      } else {
        drag.feld.position.x = begrenzen(drag.x + dx, 0, 1 - drag.breite);
        drag.feld.position.y = begrenzen(drag.y + dy, 0, 1 - drag.hoehe);
        drag.box.style.left = `${drag.feld.position.x * 100}%`;
        drag.box.style.top = `${drag.feld.position.y * 100}%`;
      }
      drag.feld.vorschlag_status = 'bestaetigt';
      drag.feld.geprueft = true;
      schemaGeaendert();
    });
    const beenden = ereignis => {
      if (!drag || drag.pointerId !== ereignis.pointerId) return;
      drag.box.releasePointerCapture?.(ereignis.pointerId);
      drag = null;
      rendern();
    };
    overlay.addEventListener('pointerup', beenden);
    overlay.addEventListener('pointercancel', beenden);
  });

  function zoomSetzen(neu) {
    zoom = begrenzen(neu, .65, 1.35);
    document.documentElement.style.setProperty('--workflow-zoom', zoom);
    const wert = $('#workflowZoomWert');
    if (wert) wert.textContent = `${Math.round(zoom * 100)} %`;
  }
  $('#workflowZoomMinus')?.addEventListener('click', () => zoomSetzen(zoom - .1));
  $('#workflowZoomPlus')?.addEventListener('click', () => zoomSetzen(zoom + .1));

  function dialogNachricht(rolle, text) {
    const dialog = $('#workflowDialog');
    if (!dialog) return;
    const element = document.createElement('div');
    element.className = `dialognachricht ${rolle}`;
    element.textContent = text;
    dialog.appendChild(element);
    dialog.scrollTop = dialog.scrollHeight;
  }

  async function chatSenden(text) {
    if (!text) return;
    dialogNachricht('nutzer', text);
    if (/entferne alle vorschläge|ohne vorschläge starten/i.test(text)) {
      schema.felder = [];
      schemaGeaendert();
      rendern();
      dialogNachricht('assistent', 'Alle Vorschläge wurden entfernt. Wechseln Sie in den manuellen Modus oder beschreiben Sie die gewünschten Felder im Chat.');
      return;
    }
    dialogNachricht('assistent', 'Ich passe die Feldvorschläge an …');
    const antwort = await fetch('/api/vorlagen/korrigieren', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vorlage_id: vorlageId, nachricht: text }),
    });
    const inhalt = await antwort.json();
    if (!antwort.ok) throw new Error(inhalt.detail || 'Die Änderung konnte nicht verarbeitet werden.');
    schema = inhalt.schema || schema;
    schema.felder = Array.isArray(schema.felder) ? schema.felder : [];
    schemaGeaendert();
    rendern();
    dialogNachricht('assistent', inhalt.antwort || 'Die Änderung wurde live im Dokument übernommen.');
  }

  $('#workflowChatForm')?.addEventListener('submit', async ereignis => {
    ereignis.preventDefault();
    const feld = $('#workflowChatText');
    const text = feld?.value.trim();
    if (!text) return;
    feld.value = '';
    try { await chatSenden(text); } catch (fehler) { dialogNachricht('assistent', fehler.message); meldung(fehler.message, 'fehler'); }
  });
  $$('[data-chat-vorschlag]').forEach(knopf => knopf.addEventListener('click', async () => {
    try { await chatSenden(knopf.dataset.chatVorschlag); } catch (fehler) { meldung(fehler.message, 'fehler'); }
  }));

  async function speichern() {
    const antwort = await fetch(`/api/vorlagen/${vorlageId}/schema`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schema }),
    });
    const inhalt = await antwort.json();
    if (!antwort.ok) throw new Error(inhalt.detail || 'Die Vorlage konnte nicht gespeichert werden.');
    schema = inhalt.schema || schema;
    ungespeichert = false;
    const knopf = $('#workflowSpeichern');
    if (knopf) { knopf.textContent = 'Gespeichert ✓'; knopf.classList.remove('ungespeichert'); window.setTimeout(() => knopf.textContent = 'Speichern', 1200); }
    return inhalt;
  }
  $('#workflowSpeichern')?.addEventListener('click', () => speichern().then(() => meldung('Die Änderungen wurden gespeichert.')).catch(fehler => meldung(fehler.message, 'fehler')));

  async function testStarten() {
    if (ungespeichert) await speichern();
    const antwort = await fetch(`/api/vorlagen/${vorlageId}/testausfuellung`, { method: 'POST' });
    const inhalt = await antwort.json();
    if (!antwort.ok) throw new Error(inhalt.detail || 'Die Testausfüllung konnte nicht erstellt werden.');
    $('#workflowTestOriginal').src = `${inhalt.original_url}#toolbar=0&navpanes=0&view=FitH`;
    $('#workflowTestAusgabe').src = `${inhalt.test_url}#toolbar=0&navpanes=0&view=FitH`;
    $('#workflowTestBestaetigt').checked = false;
    $('#workflowTestDialog').classList.remove('versteckt');
  }
  $('#workflowTesten')?.addEventListener('click', () => testStarten().catch(fehler => meldung(fehler.message, 'fehler')));
  $('#workflowTestSchliessen')?.addEventListener('click', () => $('#workflowTestDialog').classList.add('versteckt'));
  $('#workflowTestAbschliessen')?.addEventListener('click', async () => {
    if (!$('#workflowTestBestaetigt')?.checked) return meldung('Bitte bestätigen Sie zuerst den visuellen Vergleich.', 'fehler');
    try {
      const antwort = await fetch(`/api/vorlagen/${vorlageId}/pruefung-bestaetigen`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ alle_pruefpflichtigen:true, testausfuellung_geprueft:true, schluessel:[] }) });
      const inhalt = await antwort.json();
      if (!antwort.ok) throw new Error(inhalt.detail || 'Die Prüfung konnte nicht abgeschlossen werden.');
      schema = inhalt.schema || schema;
      $('#workflowTestDialog').classList.add('versteckt');
      meldung(inhalt.hinweis || 'Die Testausfüllung wurde bestätigt.');
    } catch (fehler) { meldung(fehler.message, 'fehler'); }
  });

  $('#workflowFreigeben')?.addEventListener('click', async () => {
    try {
      if (ungespeichert) await speichern();
      const antwort = await fetch(`/api/vorlagen/${vorlageId}/bestaetigen`, { method:'POST' });
      const inhalt = await antwort.json();
      if (!antwort.ok) throw new Error(inhalt.detail || 'Die Vorlage kann noch nicht freigegeben werden.');
      window.location.href = inhalt.weiter || `/vorlagen/${vorlageId}/verwenden`;
    } catch (fehler) {
      meldung(fehler.message, 'fehler');
      if (/Testausfüllung|Prüfung/i.test(fehler.message)) testStarten().catch(() => {});
    }
  });

  window.addEventListener('beforeunload', ereignis => {
    if (!ungespeichert) return;
    ereignis.preventDefault();
    ereignis.returnValue = '';
  });

  zoomSetzen(1);
  modusSetzen('chat');
  rendern();
})();
