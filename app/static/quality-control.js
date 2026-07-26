(() => {
  'use strict';
  if (typeof editorSchema === 'undefined' || !document.querySelector('#aktuelleVorlageId')) return;

  const $q = (auswahl, wurzel = document) => wurzel.querySelector(auswahl);
  const $$q = (auswahl, wurzel = document) => [...wurzel.querySelectorAll(auswahl)];
  const vorlageId = Number($q('#aktuelleVorlageId')?.value || 0);

  function stufe(feld) {
    if (feld.konfidenzstufe) return feld.konfidenzstufe;
    const wert = Number(feld.konfidenz ?? 0.62);
    return wert >= .88 ? 'sicher' : wert >= .68 ? 'pruefen' : 'unsicher';
  }

  function qualitaetBerechnen() {
    const felder = editorSchema.felder || [];
    const ergebnis = { gesamt: felder.length, sicher: 0, pruefen: 0, unsicher: 0, offene_felder: 0, durchschnitt: 0 };
    let summe = 0;
    felder.forEach(feld => {
      const niveau = stufe(feld);
      const wert = Number(feld.konfidenz ?? (niveau === 'sicher' ? .9 : niveau === 'pruefen' ? .75 : .55));
      summe += wert;
      ergebnis[niveau] += 1;
      if (niveau !== 'sicher' && !feld.geprueft) ergebnis.offene_felder += 1;
    });
    ergebnis.durchschnitt = felder.length ? Math.round(summe / felder.length * 100) : 0;
    editorSchema.qualitaet = { ...(editorSchema.qualitaet || {}), ...ergebnis, testausfuellung_geprueft: Boolean(editorSchema.testausfuellung_geprueft) };
    return editorSchema.qualitaet;
  }

  function textSetzen(id, wert) {
    const element = $q(id);
    if (element) element.textContent = String(wert);
  }

  function qualitaetAnzeigen() {
    const q = qualitaetBerechnen();
    textSetzen('#qGesamt', q.gesamt);
    textSetzen('#qSicher', q.sicher);
    textSetzen('#qPruefen', q.pruefen);
    textSetzen('#qUnsicher', q.unsicher);
    textSetzen('#qOffen', q.offene_felder);
    textSetzen('#qDurchschnitt', `${q.durchschnitt} %`);
    const status = $q('#qualitaetsKurzstatus');
    if (status) {
      status.textContent = q.offene_felder
        ? `${q.offene_felder} Felder kurz prüfen`
        : editorSchema.testausfuellung_geprueft
          ? 'Qualitätsprüfung abgeschlossen'
          : 'Felder geprüft · Testausfüllung fehlt';
    }
    const knopf = $q('#detailBestaetigen');
    if (knopf) {
      const bereit = q.offene_felder === 0 && Boolean(editorSchema.testausfuellung_geprueft);
      knopf.classList.toggle('qualitaet-offen', !bereit);
      knopf.title = bereit ? 'Vorlage freigeben' : 'Zuerst Testausfüllung prüfen';
    }
  }

  function dekorieren() {
    $$q('#detailFelderListe .detail-feld').forEach(karte => {
      const index = Number(karte.dataset.index);
      const feld = editorSchema.felder?.[index];
      if (!feld) return;
      const niveau = stufe(feld);
      karte.classList.remove('konfidenz-sicher', 'konfidenz-pruefen', 'konfidenz-unsicher');
      karte.classList.add(`konfidenz-${niveau}`);
      let marke = karte.querySelector('.konfidenzmarke');
      if (!marke) {
        marke = document.createElement('span');
        marke.className = 'konfidenzmarke';
        karte.appendChild(marke);
      }
      const prozent = Math.round(Number(feld.konfidenz ?? 0) * 100);
      marke.textContent = feld.geprueft ? 'geprüft ✓' : niveau === 'sicher' ? `${prozent}% sicher` : niveau === 'pruefen' ? `${prozent}% prüfen` : `${prozent}% unsicher`;
      karte.title = feld.pruefhinweis || '';
    });
    $$q('#feldOverlay .overlay-feld').forEach(box => {
      const feld = editorSchema.felder?.[Number(box.dataset.index)];
      if (!feld) return;
      const niveau = stufe(feld);
      box.classList.remove('konfidenz-sicher', 'konfidenz-pruefen', 'konfidenz-unsicher', 'geprueft');
      box.classList.add(`konfidenz-${niveau}`);
      if (feld.geprueft) box.classList.add('geprueft');
    });
    qualitaetAnzeigen();
  }

  if (typeof editorRendern === 'function') {
    const originalRendern = editorRendern;
    editorRendern = function (...argumente) {
      const ergebnis = originalRendern.apply(this, argumente);
      window.setTimeout(dekorieren, 0);
      return ergebnis;
    };
  }

  function alsManuellGeprueft(index) {
    const feld = editorSchema.felder?.[Number(index)];
    if (!feld) return;
    feld.geprueft = true;
    feld.erkennungsquelle = 'manuell-korrigiert';
    feld.konfidenz = 1;
    feld.konfidenzstufe = 'sicher';
    feld.pruefung_erforderlich = false;
    feld.pruefhinweis = 'Vom Benutzer manuell geprüft oder positioniert.';
    editorSchema.testausfuellung_geprueft = false;
    editorSchema.testausfuellung_hash = null;
    qualitaetAnzeigen();
  }
  window.smartDocsFeldGeprueft = alsManuellGeprueft;
  window.smartDocsQualitaetAktualisieren = dekorieren;

  $q('#feldFormular')?.addEventListener('submit', () => {
    const index = $q('#feldIndex')?.value;
    window.setTimeout(() => {
      const zielIndex = index === '' ? (editorSchema.felder.length - 1) : Number(index);
      alsManuellGeprueft(zielIndex);
      if (typeof editorRendern === 'function') editorRendern();
    }, 0);
  });

  $q('#feldOverlay')?.addEventListener('pointerup', ereignis => {
    const box = ereignis.target.closest('.overlay-feld');
    if (!box) return;
    alsManuellGeprueft(box.dataset.index);
    dekorieren();
  });
  $q('#feldOverlay')?.addEventListener('keydown', ereignis => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(ereignis.key)) return;
    const box = ereignis.target.closest('.overlay-feld');
    if (box) alsManuellGeprueft(box.dataset.index);
  });

  function dialogOeffnen() {
    $q('#testausfuellungDialog')?.classList.remove('versteckt');
  }
  function dialogSchliessen() {
    $q('#testausfuellungDialog')?.classList.add('versteckt');
  }
  $q('#testausfuellungSchliessen')?.addEventListener('click', dialogSchliessen);
  $q('#testausfuellungDialog')?.addEventListener('click', ereignis => {
    if (ereignis.target === $q('#testausfuellungDialog')) dialogSchliessen();
  });

  async function testausfuellungStarten() {
    const knopf = $q('#testausfuellungStarten');
    const original = knopf?.textContent;
    try {
      if (knopf) { knopf.disabled = true; knopf.textContent = 'Testausfüllung wird erzeugt …'; }
      if (typeof schemaSpeichern === 'function') await schemaSpeichern();
      const antwort = await fetch(`/api/vorlagen/${vorlageId}/testausfuellung`, { method: 'POST' });
      const inhalt = await antwort.json();
      if (!antwort.ok) throw new Error(inhalt.detail || 'Die Testausfüllung konnte nicht erzeugt werden.');
      $q('#vergleichOriginal').src = `${inhalt.original_url}#toolbar=0&navpanes=0&view=FitH`;
      $q('#vergleichTest').src = `${inhalt.test_url}#toolbar=0&navpanes=0&view=FitH`;
      $q('#testausfuellungBestaetigt').checked = false;
      editorSchema.testausfuellung_geprueft = false;
      editorSchema.testausfuellung_hash = null;
      dialogOeffnen();
      if (typeof meldung === 'function') meldung(inhalt.hinweis);
    } catch (fehler) {
      if (typeof meldung === 'function') meldung(fehler.message, 'fehler');
    } finally {
      if (knopf) { knopf.disabled = false; knopf.textContent = original; }
    }
  }
  $q('#testausfuellungStarten')?.addEventListener('click', testausfuellungStarten);

  $q('#qualitaetsPruefungAbschliessen')?.addEventListener('click', async () => {
    const checkbox = $q('#testausfuellungBestaetigt');
    if (!checkbox?.checked) {
      if (typeof meldung === 'function') meldung('Bitte vergleichen Sie beide Dokumente und bestätigen Sie die Prüfung.', 'fehler');
      return;
    }
    try {
      const antwort = await fetch(`/api/vorlagen/${vorlageId}/pruefung-bestaetigen`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alle_pruefpflichtigen: true, testausfuellung_geprueft: true, schluessel: [] }),
      });
      const inhalt = await antwort.json();
      if (!antwort.ok) throw new Error(inhalt.detail || 'Die Prüfung konnte nicht abgeschlossen werden.');
      editorSchema = inhalt.schema;
      if (typeof editorRendern === 'function') editorRendern();
      dialogSchliessen();
      if (typeof meldung === 'function') meldung(inhalt.hinweis);
    } catch (fehler) {
      if (typeof meldung === 'function') meldung(fehler.message, 'fehler');
    }
  });

  $q('#detailBestaetigen')?.addEventListener('click', ereignis => {
    const q = qualitaetBerechnen();
    if (q.offene_felder === 0 && editorSchema.testausfuellung_geprueft) return;
    ereignis.preventDefault();
    ereignis.stopImmediatePropagation();
    if (typeof meldung === 'function') meldung('Vor der Freigabe wird eine Testausfüllung benötigt.', 'fehler');
    testausfuellungStarten();
  }, true);

  dekorieren();
})();
