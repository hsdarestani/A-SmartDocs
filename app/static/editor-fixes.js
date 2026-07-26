(() => {
  'use strict';

  const overlay = document.querySelector('#feldOverlay');
  if (!overlay || typeof editorSchema === 'undefined') return;

  let aktion = null;

  const begrenzen = (wert, min, max) => Math.min(max, Math.max(min, wert));

  function alsZahl(wert, standard) {
    const zahl = Number(wert);
    return Number.isFinite(zahl) ? zahl : standard;
  }

  function statusUngespeichert() {
    const knopf = document.querySelector('#schemaSpeichern');
    if (!knopf) return;
    knopf.textContent = 'Änderungen speichern •';
    knopf.classList.add('ungespeichert');
  }

  function griffeErgaenzen() {
    overlay.querySelectorAll('.overlay-feld').forEach(box => {
      if (!box.querySelector('.resize-griff')) {
        const griff = document.createElement('span');
        griff.className = 'resize-griff';
        griff.setAttribute('aria-hidden', 'true');
        box.appendChild(griff);
      }
      box.title = 'Ziehen zum Verschieben · Griff unten rechts zum Skalieren';
      box.setAttribute('aria-label', `${box.textContent.trim()} positionieren`);
    });
  }

  function feldAusBox(box) {
    const index = Number(box.dataset.index);
    if (!Number.isInteger(index) || !editorSchema?.felder?.[index]) return null;
    return { index, feld: editorSchema.felder[index] };
  }

  overlay.addEventListener('pointerdown', ereignis => {
    const box = ereignis.target.closest('.overlay-feld');
    if (!box) return;
    const daten = feldAusBox(box);
    if (!daten) return;
    ereignis.preventDefault();
    ereignis.stopPropagation();

    overlay.querySelectorAll('.overlay-feld').forEach(element => element.classList.toggle('aktiv', element === box));
    box.setPointerCapture?.(ereignis.pointerId);

    const pos = daten.feld.position || {};
    aktion = {
      pointerId: ereignis.pointerId,
      box,
      feld: daten.feld,
      art: ereignis.target.classList.contains('resize-griff') ? 'skalieren' : 'verschieben',
      startX: ereignis.clientX,
      startY: ereignis.clientY,
      x: alsZahl(pos.x, .1),
      y: alsZahl(pos.y, .2),
      breite: alsZahl(pos.breite, .3),
      hoehe: alsZahl(pos.hoehe, .035),
    };
  });

  overlay.addEventListener('pointermove', ereignis => {
    if (!aktion || ereignis.pointerId !== aktion.pointerId) return;
    const rechteck = overlay.getBoundingClientRect();
    if (!rechteck.width || !rechteck.height) return;
    const dx = (ereignis.clientX - aktion.startX) / rechteck.width;
    const dy = (ereignis.clientY - aktion.startY) / rechteck.height;

    if (aktion.art === 'skalieren') {
      const breite = begrenzen(aktion.breite + dx, .02, 1 - aktion.x);
      const hoehe = begrenzen(aktion.hoehe + dy, .015, 1 - aktion.y);
      aktion.feld.position = { ...(aktion.feld.position || {}), breite, hoehe };
      aktion.box.style.width = `${breite * 100}%`;
      aktion.box.style.height = `${hoehe * 100}%`;
    } else {
      const x = begrenzen(aktion.x + dx, 0, 1 - aktion.breite);
      const y = begrenzen(aktion.y + dy, 0, 1 - aktion.hoehe);
      aktion.feld.position = { ...(aktion.feld.position || {}), x, y };
      aktion.box.style.left = `${x * 100}%`;
      aktion.box.style.top = `${y * 100}%`;
    }
    statusUngespeichert();
  });

  function aktionBeenden(ereignis) {
    if (!aktion || ereignis.pointerId !== aktion.pointerId) return;
    aktion.box.releasePointerCapture?.(ereignis.pointerId);
    aktion = null;
  }
  overlay.addEventListener('pointerup', aktionBeenden);
  overlay.addEventListener('pointercancel', aktionBeenden);

  overlay.addEventListener('keydown', ereignis => {
    const box = ereignis.target.closest('.overlay-feld');
    if (!box || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(ereignis.key)) return;
    const daten = feldAusBox(box);
    if (!daten) return;
    ereignis.preventDefault();
    const schritt = ereignis.shiftKey ? .01 : .0025;
    const pos = daten.feld.position || {};
    const breite = alsZahl(pos.breite, .3);
    const hoehe = alsZahl(pos.hoehe, .035);
    let x = alsZahl(pos.x, .1);
    let y = alsZahl(pos.y, .2);
    if (ereignis.key === 'ArrowLeft') x -= schritt;
    if (ereignis.key === 'ArrowRight') x += schritt;
    if (ereignis.key === 'ArrowUp') y -= schritt;
    if (ereignis.key === 'ArrowDown') y += schritt;
    daten.feld.position = {
      ...pos,
      x: begrenzen(x, 0, 1 - breite),
      y: begrenzen(y, 0, 1 - hoehe),
      breite,
      hoehe,
    };
    if (typeof editorRendern === 'function') editorRendern();
    statusUngespeichert();
  });

  document.querySelector('#schemaSpeichern')?.addEventListener('click', () => {
    window.setTimeout(() => {
      const knopf = document.querySelector('#schemaSpeichern');
      if (!knopf) return;
      knopf.textContent = 'Änderungen speichern';
      knopf.classList.remove('ungespeichert');
    }, 500);
  });

  const beobachter = new MutationObserver(griffeErgaenzen);
  beobachter.observe(overlay, { childList: true });
  griffeErgaenzen();
})();
