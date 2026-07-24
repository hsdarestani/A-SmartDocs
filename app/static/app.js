const $ = (auswahl, wurzel = document) => wurzel.querySelector(auswahl);
const $$ = (auswahl, wurzel = document) => [...wurzel.querySelectorAll(auswahl)];

function meldung(text, art = "erfolg") {
  const element = $("#meldung");
  if (!element) return;
  element.textContent = text;
  element.className = `meldung sichtbar ${art}`;
  window.clearTimeout(window.smartDocsMeldung);
  window.smartDocsMeldung = window.setTimeout(() => element.classList.remove("sichtbar"), 4200);
}

function formatDateigroesse(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} MB`;
}

const hochladeBereich = $("#hochladeBereich");
const dateiEingabe = $("#dateiEingabe");
const analyseStarten = $("#analyseStarten");
let aktuelleDatei = null;
let aktuelleVorlage = null;

if (hochladeBereich && dateiEingabe) {
  hochladeBereich.addEventListener("click", () => dateiEingabe.click());
  ["dragenter", "dragover"].forEach(art => hochladeBereich.addEventListener(art, ereignis => {
    ereignis.preventDefault();
    hochladeBereich.classList.add("darueber");
  }));
  ["dragleave", "drop"].forEach(art => hochladeBereich.addEventListener(art, ereignis => {
    ereignis.preventDefault();
    hochladeBereich.classList.remove("darueber");
  }));
  hochladeBereich.addEventListener("drop", ereignis => dateiWaehlen(ereignis.dataTransfer.files[0]));
  dateiEingabe.addEventListener("change", () => dateiWaehlen(dateiEingabe.files[0]));
  $("#dateiEntfernen")?.addEventListener("click", () => dateiWaehlen(null));
}

function dateiWaehlen(datei) {
  aktuelleDatei = datei || null;
  const karte = $("#dateiKarte");
  if (!aktuelleDatei) {
    karte?.classList.add("versteckt");
    hochladeBereich?.classList.remove("versteckt");
    if (dateiEingabe) dateiEingabe.value = "";
    if (analyseStarten) analyseStarten.disabled = true;
    return;
  }
  const erlaubt = ["application/pdf", "image/png", "image/jpeg", "image/webp"];
  if (!erlaubt.includes(aktuelleDatei.type)) {
    meldung("Bitte wählen Sie eine PDF-, PNG-, JPG- oder WEBP-Datei aus.", "fehler");
    return dateiWaehlen(null);
  }
  $("#dateiName").textContent = aktuelleDatei.name;
  $("#dateiGroesse").textContent = formatDateigroesse(aktuelleDatei.size);
  karte?.classList.remove("versteckt");
  hochladeBereich?.classList.add("versteckt");
  if (analyseStarten) analyseStarten.disabled = false;
}

analyseStarten?.addEventListener("click", async () => {
  if (!aktuelleDatei) return;
  const ursprung = analyseStarten.innerHTML;
  analyseStarten.disabled = true;
  analyseStarten.innerHTML = '<span class="ladekreis"></span> Dokument wird analysiert …';
  dialogNachricht("assistent", "Ich lese das Dokument und unterscheide feste Inhalte von später veränderlichen Feldern. Das kann einen Moment dauern.");
  const daten = new FormData();
  daten.append("datei", aktuelleDatei);
  daten.append("name", $("#vorlagenName")?.value || "Neue Dokumentvorlage");
  try {
    const antwort = await fetch("/api/vorlagen/analysieren", { method: "POST", body: daten });
    const inhalt = await antwort.json();
    if (!antwort.ok) throw new Error(inhalt.detail || "Die Analyse ist fehlgeschlagen.");
    aktuelleVorlage = inhalt.vorlage_id;
    ergebnisZeigen(inhalt.schema);
    dialogNachricht("assistent", `Ich habe ${inhalt.schema.felder?.length || 0} veränderliche Felder erkannt. Prüfen Sie die Liste. Sie können mir jede gewünschte Korrektur direkt schreiben.`);
    dialogAktivieren(true);
    meldung("Die Dokumentstruktur wurde erfolgreich erkannt.");
  } catch (fehler) {
    dialogNachricht("assistent", `Die Analyse konnte nicht abgeschlossen werden. ${fehler.message}`);
    meldung(fehler.message, "fehler");
  } finally {
    analyseStarten.disabled = false;
    analyseStarten.innerHTML = ursprung;
  }
});

function dialogNachricht(rolle, text) {
  const verlauf = $("#dialogVerlauf");
  if (!verlauf) return;
  const element = document.createElement("div");
  element.className = `dialognachricht ${rolle === "nutzer" ? "nutzer" : "assistent"}`;
  element.textContent = text;
  verlauf.appendChild(element);
  verlauf.scrollTop = verlauf.scrollHeight;
}

function dialogAktivieren(aktiv) {
  const text = $("#dialogText");
  const knopf = $("#dialogFormular button");
  if (text) text.disabled = !aktiv;
  if (knopf) knopf.disabled = !aktiv;
}

function ergebnisZeigen(schema) {
  $("#ergebnisBereich")?.classList.remove("versteckt");
  $("#dokumentArt").textContent = schema.dokumentart || "Erkannte Dokumentvorlage";
  $("#zusammenfassung").textContent = schema.zusammenfassung || "Prüfen Sie die erkannten veränderlichen Inhalte.";
  const liste = $("#felderListe");
  if (!liste) return;
  liste.innerHTML = "";
  (schema.felder || []).forEach((feld, index) => {
    const artikel = document.createElement("article");
    artikel.className = "feldkarte";
    artikel.innerHTML = `
      <span class="feldnummer">${String(index + 1).padStart(2, "0")}</span>
      <div class="feldinhalt"><strong>${sicher(feld.bezeichnung || "Unbenanntes Feld")}</strong><small>${sicher(feld.hinweis || "Automatisch erkannt")}</small></div>
      <span class="feldtyp">${sicher(typBezeichnung(feld.typ))}</span>
      <span class="pflichtmarke ${feld.pflichtfeld ? "pflicht" : ""}">${feld.pflichtfeld ? "Pflichtfeld" : "freiwillig"}</span>
      <button type="button" aria-label="Feld bearbeiten">✎</button>`;
    liste.appendChild(artikel);
  });
  $("#ergebnisBereich").scrollIntoView({ behavior: "smooth", block: "start" });
}

function sicher(text) {
  const element = document.createElement("div");
  element.textContent = String(text ?? "");
  return element.innerHTML;
}

function typBezeichnung(typ) {
  const namen = { text: "Text", mehrzeilig: "Mehrzeiliger Text", datum: "Datum", zahl: "Zahl", betrag: "Betrag", auswahl: "Auswahl", kontrollfeld: "Kontrollfeld", unterschrift: "Unterschrift", bild: "Bild", bilderliste: "Bilderliste", tabelle: "Tabelle" };
  return namen[typ] || "Text";
}

$("#dialogFormular")?.addEventListener("submit", async ereignis => {
  ereignis.preventDefault();
  const feld = $("#dialogText");
  const nachricht = feld?.value.trim();
  if (!nachricht || !aktuelleVorlage) return;
  dialogNachricht("nutzer", nachricht);
  feld.value = "";
  dialogAktivieren(false);
  try {
    const antwort = await fetch("/api/vorlagen/korrigieren", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vorlage_id: aktuelleVorlage, nachricht })
    });
    const inhalt = await antwort.json();
    if (!antwort.ok) throw new Error(inhalt.detail || "Die Änderung konnte nicht verarbeitet werden.");
    ergebnisZeigen(inhalt.schema);
    dialogNachricht("assistent", inhalt.antwort);
  } catch (fehler) {
    dialogNachricht("assistent", fehler.message);
    meldung(fehler.message, "fehler");
  } finally {
    dialogAktivieren(true);
    feld?.focus();
  }
});

$("#vorlageBestaetigen")?.addEventListener("click", async () => {
  if (!aktuelleVorlage) return;
  try {
    const antwort = await fetch(`/api/vorlagen/${aktuelleVorlage}/bestaetigen`, { method: "POST" });
    const inhalt = await antwort.json();
    if (!antwort.ok) throw new Error(inhalt.detail || "Die Vorlage konnte nicht bestätigt werden.");
    meldung("Die Vorlage ist gespeichert und kann jetzt wiederverwendet werden.");
    dialogNachricht("assistent", "Perfekt. Die Vorlage ist bestätigt und ab sofort einsatzbereit.");
  } catch (fehler) {
    meldung(fehler.message, "fehler");
  }
});

$$('[data-vorschlag]').forEach(knopf => knopf.addEventListener("click", () => {
  const frage = knopf.dataset.vorschlag;
  if (frage.includes("Dokumentarten")) dialogNachricht("assistent", "Unterstützt werden beliebige geschäftliche PDF-, Scan- und Bildvorlagen. Entscheidend ist, dass die Inhalte gut lesbar sind.");
  else dialogNachricht("assistent", "Dateien werden verschlüsselt übertragen, getrennt gespeichert und nur für die gewünschte Verarbeitung verwendet.");
}));

const kontenSuche = $("#kontenSuche");
kontenSuche?.addEventListener("input", () => {
  const suchwert = kontenSuche.value.toLowerCase().trim();
  $$("#kontenTabelle tbody tr").forEach(zeile => zeile.hidden = !zeile.dataset.name.includes(suchwert));
});

const kontoDialog = $("#kontoDialog");
let aktuellesKonto = null;
$$('.kontoBearbeiten').forEach(knopf => knopf.addEventListener("click", () => {
  aktuellesKonto = knopf.dataset.konto;
  $("#kontoTitel").textContent = knopf.dataset.name;
  $("#kontoPreis").value = knopf.dataset.preis || "";
  $("#kontoDokumente").value = knopf.dataset.dokumente || "";
  $("#kontoVorlagen").value = knopf.dataset.vorlagen || "";
  $("#kontoUnterkonten").value = knopf.dataset.unterkonten || "";
  $("#kontoSpeicher").value = knopf.dataset.speicher || "";
  kontoDialog?.classList.remove("versteckt");
}));

function kontoDialogSchliessen() { kontoDialog?.classList.add("versteckt"); }
$("#kontoDialogSchliessen")?.addEventListener("click", kontoDialogSchliessen);
$("#kontoAbbrechen")?.addEventListener("click", kontoDialogSchliessen);
kontoDialog?.addEventListener("click", ereignis => { if (ereignis.target === kontoDialog) kontoDialogSchliessen(); });

$("#kontoFormular")?.addEventListener("submit", async ereignis => {
  ereignis.preventDefault();
  if (!aktuellesKonto) return;
  const zahlOderLeer = id => { const wert = $(id).value; return wert === "" ? null : Number(wert); };
  const daten = {
    individueller_preis: zahlOderLeer("#kontoPreis"),
    dokumente: zahlOderLeer("#kontoDokumente"),
    vorlagen: zahlOderLeer("#kontoVorlagen"),
    unterkonten: zahlOderLeer("#kontoUnterkonten"),
    speicher_mb: zahlOderLeer("#kontoSpeicher")
  };
  try {
    const antwort = await fetch(`/api/verwaltung/konten/${aktuellesKonto}/grenzen`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(daten) });
    const inhalt = await antwort.json();
    if (!antwort.ok) throw new Error(inhalt.detail || "Die Konditionen konnten nicht gespeichert werden.");
    kontoDialogSchliessen();
    meldung(inhalt.hinweis);
    window.setTimeout(() => window.location.reload(), 800);
  } catch (fehler) { meldung(fehler.message, "fehler"); }
});
