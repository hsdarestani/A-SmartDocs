(() => {
  'use strict';

  const seite = document.querySelector('.ausfuellseite');
  if (!seite) return;

  // Das alte globale Datumsverhalten setzte auch Geburtsdaten auf heute.
  // Dynamische Dokumentfelder bleiben leer, solange kein expliziter Standard definiert ist.
  const heute = new Date().toISOString().slice(0, 10);
  seite.querySelectorAll('input[type="date"]:not([data-standard-heute="true"])').forEach(eingabe => {
    if (!eingabe.defaultValue && eingabe.value === heute) eingabe.value = '';
  });

  const abschnitte = [...seite.querySelectorAll('.formular-abschnitt')];
  const umschalter = document.querySelector('#formularAlleUmschalten');
  umschalter?.addEventListener('click', () => {
    const alleOffen = abschnitte.length > 0 && abschnitte.every(abschnitt => abschnitt.open);
    abschnitte.forEach(abschnitt => { abschnitt.open = !alleOffen; });
    umschalter.textContent = alleOffen ? 'Alle öffnen' : 'Alle schließen';
  });

  seite.querySelectorAll('.datei-upload-klein input[type="file"]').forEach(eingabe => {
    eingabe.addEventListener('change', () => {
      const beschriftung = eingabe.closest('.datei-upload-klein')?.querySelector('span');
      if (!beschriftung) return;
      beschriftung.textContent = eingabe.files?.[0]?.name || 'Bilddatei auswählen';
    });
  });

  const formular = seite.querySelector('form.ausfuell-gitter');
  formular?.addEventListener('submit', ereignis => {
    const ungueltig = formular.querySelector(':invalid');
    if (!ungueltig) return;
    const abschnitt = ungueltig.closest('details');
    if (abschnitt) abschnitt.open = true;
    window.setTimeout(() => ungueltig.focus(), 0);
  });
})();
