(() => {
  const knop = document.getElementById('analyseStarten');
  const dateiEingabe = document.getElementById('dateiEingabe');
  const nameEingabe = document.getElementById('vorlagenName');
  const verlauf = document.getElementById('dialogVerlauf');
  if (!knop || !dateiEingabe || !verlauf) return;

  let laeuft = false;
  let vorlageId = null;

  const warten = millisekunden => new Promise(resolve => window.setTimeout(resolve, millisekunden));

  function nachricht(text, art = 'assistent') {
    const element = document.createElement('div');
    element.className = `dialognachricht ${art}`;
    element.textContent = text;
    verlauf.appendChild(element);
    verlauf.scrollTop = verlauf.scrollHeight;
  }

  function schritt(index, zustand = 'aktiv') {
    const zeilen = [...document.querySelectorAll('.assistenten-checkliste span')];
    zeilen.forEach((zeile, position) => {
      zeile.classList.toggle('aktiv', position === index && zustand === 'aktiv');
      if (position < index || (position === index && zustand === 'fertig')) zeile.classList.add('fertig');
    });
  }

  async function jsonAntwort(antwort) {
    const text = await antwort.text();
    let daten = {};
    try {
      daten = text ? JSON.parse(text) : {};
    } catch {
      throw new Error(`Der Server hat keine gültige Antwort geliefert (${antwort.status}).`);
    }
    if (!antwort.ok) throw new Error(daten.detail || daten.hinweis || `Serverfehler ${antwort.status}`);
    return daten;
  }

  async function abrufen(url, optionen = {}, versuche = 1) {
    let letzterFehler;
    for (let versuch = 0; versuch <= versuche; versuch += 1) {
      try {
        const antwort = await fetch(url, { credentials: 'same-origin', ...optionen });
        return await jsonAntwort(antwort);
      } catch (fehler) {
        letzterFehler = fehler;
        if (versuch < versuche) await warten(1000 * (versuch + 1));
      }
    }
    throw letzterFehler;
  }

  function wiederholenAnbieten(statusUrl) {
    const zeile = document.createElement('div');
    zeile.className = 'analyse-wiederholen';
    const hinweis = document.createElement('span');
    hinweis.textContent = 'Die Datei ist sicher gespeichert.';
    const erneut = document.createElement('button');
    erneut.type = 'button';
    erneut.textContent = 'Prüflauf erneut starten';
    erneut.addEventListener('click', async () => {
      erneut.disabled = true;
      try {
        const daten = await abrufen(`/api/vorlagen/${vorlageId}/analyse-neu-starten`, { method: 'POST' }, 2);
        zeile.remove();
        nachricht('Der Prüflauf wurde erneut gestartet.');
        await statusBeobachten(daten.status_url || statusUrl);
      } catch (fehler) {
        erneut.disabled = false;
        nachricht(`Der erneute Start ist noch nicht möglich: ${fehler.message}`);
      }
    });
    zeile.append(hinweis, erneut);
    verlauf.appendChild(zeile);
    verlauf.scrollTop = verlauf.scrollHeight;
  }

  async function statusBeobachten(statusUrl) {
    let netzfehler = 0;
    for (let runde = 0; runde < 160; runde += 1) {
      await warten(runde < 4 ? 900 : 1500);
      try {
        const status = await abrufen(statusUrl, {}, 2);
        netzfehler = 0;
        if (status.fertig) {
          schritt(3, 'fertig');
          nachricht('Die Analyse ist abgeschlossen. Sie werden jetzt zur Feldprüfung weitergeleitet.');
          window.setTimeout(() => { window.location.href = status.weiter; }, 650);
          return;
        }
        if (status.fehler) {
          nachricht(status.hinweis || 'Der Prüflauf wurde unterbrochen.');
          wiederholenAnbieten(statusUrl);
          return;
        }
        schritt(Math.min(2, 1 + Math.floor(runde / 6)));
      } catch (fehler) {
        netzfehler += 1;
        if (netzfehler >= 4) {
          nachricht('Die Verbindung zur Statusabfrage ist momentan instabil. Die Analyse läuft auf dem Server weiter; ein erneuter Versuch erfolgt automatisch.');
          netzfehler = 0;
        }
      }
    }
    nachricht('Der Prüflauf benötigt länger als erwartet. Die Datei ist gespeichert und kann über die Vorlagenbibliothek geöffnet werden.');
    const link = document.createElement('a');
    link.href = vorlageId ? `/vorlagen/${vorlageId}` : '/vorlagen';
    link.className = 'analyse-weiter-link';
    link.textContent = 'Gespeicherte Vorlage öffnen →';
    verlauf.appendChild(link);
  }

  async function prueflaufStarten(ereignis) {
    ereignis.preventDefault();
    ereignis.stopImmediatePropagation();
    if (laeuft) return;

    const datei = dateiEingabe.files?.[0];
    if (!datei) {
      nachricht('Bitte wählen Sie zuerst ein Quelldokument aus.');
      return;
    }

    laeuft = true;
    const ursprung = knop.innerHTML;
    knop.disabled = true;
    knop.innerHTML = '<span class="ladekreis"></span> Datei wird sicher gespeichert …';
    schritt(0);
    nachricht('Die Datei wird zuerst gespeichert. Danach läuft die Dokumentanalyse unabhängig von dieser Browser-Verbindung weiter.');

    const daten = new FormData();
    daten.append('datei', datei);
    daten.append('name', nameEingabe?.value || 'Neue Dokumentvorlage');

    try {
      const ergebnis = await abrufen('/api/vorlagen/analysieren', { method: 'POST', body: daten }, 1);
      vorlageId = ergebnis.vorlage_id;
      knop.innerHTML = '<span class="ladekreis"></span> Prüflauf läuft im Hintergrund …';
      schritt(1);
      nachricht(ergebnis.hinweis || 'Die Datei ist gespeichert. Der Prüflauf wurde gestartet.');
      await statusBeobachten(ergebnis.status_url);
    } catch (fehler) {
      nachricht(`Der Upload konnte nicht bestätigt werden: ${fehler.message}`);
      const hilfe = document.createElement('a');
      hilfe.href = '/vorlagen';
      hilfe.className = 'analyse-weiter-link';
      hilfe.textContent = 'Vorlagenbibliothek prüfen →';
      verlauf.appendChild(hilfe);
    } finally {
      laeuft = false;
      knop.disabled = false;
      knop.innerHTML = ursprung;
    }
  }

  knop.addEventListener('click', prueflaufStarten, { capture: true });
})();
