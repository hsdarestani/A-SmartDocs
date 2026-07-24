const $ = (auswahl, wurzel = document) => wurzel.querySelector(auswahl);
const $$ = (auswahl, wurzel = document) => [...wurzel.querySelectorAll(auswahl)];

function meldung(text, art = "erfolg") {
  const element = $("#meldung");
  if (!element) return;
  element.textContent = text;
  element.className = `meldung sichtbar ${art}`;
  window.clearTimeout(window.smartDocsMeldung);
  window.smartDocsMeldung = window.setTimeout(() => element.classList.remove("sichtbar"), 4800);
}
window.setTimeout(() => $("#serverHinweis")?.classList.remove("sichtbar"), 6500);

$("#menueknopf")?.addEventListener("click", () => $("#seitenleiste")?.classList.toggle("offen"));
document.addEventListener("click", ereignis => {
  const leiste = $("#seitenleiste");
  if (window.innerWidth <= 980 && leiste?.classList.contains("offen") && !leiste.contains(ereignis.target) && ereignis.target !== $("#menueknopf")) leiste.classList.remove("offen");
});

$$('.passwort-zeigen').forEach(knopf => knopf.addEventListener("click", () => {
  const eingabe = knopf.previousElementSibling;
  if (!eingabe) return;
  eingabe.type = eingabe.type === "password" ? "text" : "password";
  knopf.textContent = eingabe.type === "password" ? "◉" : "◌";
}));

$$('.tarifoption').forEach(option => option.addEventListener("click", () => {
  $$('.tarifoption').forEach(element => element.classList.remove('ausgewaehlt'));
  option.classList.add('ausgewaehlt');
  option.querySelector('input').checked = true;
}));

$$('.abrechnungsumschalter button').forEach(knopf => knopf.addEventListener('click', () => {
  const gruppe = knopf.closest('.abrechnungsumschalter');
  $$('button', gruppe).forEach(element => element.classList.remove('aktiv'));
  knopf.classList.add('aktiv');
  const zeitraum = knopf.dataset.zeitraum;
  $$('.monatspreis').forEach(preis => {
    const wert = Number(zeitraum === 'jaehrlich' ? preis.dataset.jahr : preis.dataset.monat);
    if (!Number.isNaN(wert)) preis.textContent = wert.toLocaleString('de-DE', { style: 'currency', currency: 'EUR' });
  });
  $$('.zeitraumEingabe').forEach(eingabe => eingabe.value = zeitraum);
}));

function listenSuche(eingabeAuswahl, zeilenAuswahl) {
  const eingabe = $(eingabeAuswahl);
  if (!eingabe) return;
  eingabe.addEventListener('input', () => {
    const wert = eingabe.value.toLowerCase().trim();
    $$(zeilenAuswahl).forEach(element => {
      const name = element.dataset.name || element.textContent.toLowerCase();
      element.hidden = !name.includes(wert);
    });
  });
}
listenSuche('#dokumentSuche', '#dokumentTabelle tbody tr');
listenSuche('#teamSuche', '#teamTabelle tbody tr');
listenSuche('#kontenSuche', '#kontenTabelle tbody tr');
listenSuche('#vorlagenSuche', '.vorlagenkarte');

$$('.filtergruppe button').forEach(knopf => knopf.addEventListener('click', () => {
  $$('.filtergruppe button').forEach(element => element.classList.remove('aktiv'));
  knopf.classList.add('aktiv');
  const filter = knopf.dataset.filter;
  $$('.vorlagenkarte').forEach(karte => {
    const status = karte.dataset.status || '';
    karte.hidden = filter !== 'alle' && (filter === 'bereit' ? !status.includes('bereit') : status.includes('bereit'));
  });
}));

function formatDateigroesse(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace('.', ',')} MB`;
}

const hochladeBereich = $('#hochladeBereich');
const dateiEingabe = $('#dateiEingabe');
const analyseStarten = $('#analyseStarten');
let aktuelleDatei = null;
let aktuelleVorlage = null;

if (hochladeBereich && dateiEingabe) {
  hochladeBereich.addEventListener('click', () => dateiEingabe.click());
  ['dragenter', 'dragover'].forEach(art => hochladeBereich.addEventListener(art, ereignis => { ereignis.preventDefault(); hochladeBereich.classList.add('darueber'); }));
  ['dragleave', 'drop'].forEach(art => hochladeBereich.addEventListener(art, ereignis => { ereignis.preventDefault(); hochladeBereich.classList.remove('darueber'); }));
  hochladeBereich.addEventListener('drop', ereignis => dateiWaehlen(ereignis.dataTransfer.files[0]));
  dateiEingabe.addEventListener('change', () => dateiWaehlen(dateiEingabe.files[0]));
  $('#dateiEntfernen')?.addEventListener('click', () => dateiWaehlen(null));
}

function dateiWaehlen(datei) {
  aktuelleDatei = datei || null;
  const karte = $('#dateiKarte');
  if (!aktuelleDatei) {
    karte?.classList.add('versteckt');
    hochladeBereich?.classList.remove('versteckt');
    if (dateiEingabe) dateiEingabe.value = '';
    if (analyseStarten) analyseStarten.disabled = true;
    return;
  }
  const erlaubt = ['application/pdf', 'image/png', 'image/jpeg', 'image/webp'];
  if (!erlaubt.includes(aktuelleDatei.type)) {
    meldung('Bitte wählen Sie eine PDF-, PNG-, JPG- oder WEBP-Datei aus.', 'fehler');
    return dateiWaehlen(null);
  }
  $('#dateiName').textContent = aktuelleDatei.name;
  $('#dateiGroesse').textContent = formatDateigroesse(aktuelleDatei.size);
  const name = aktuelleDatei.name.replace(/\.[^.]+$/, '').replace(/[-_]/g, ' ');
  if ($('#vorlagenName')?.value === 'Neue Dokumentvorlage') $('#vorlagenName').value = name.charAt(0).toUpperCase() + name.slice(1);
  karte?.classList.remove('versteckt');
  hochladeBereich?.classList.add('versteckt');
  if (analyseStarten) analyseStarten.disabled = false;
}

analyseStarten?.addEventListener('click', async () => {
  if (!aktuelleDatei) return;
  const ursprung = analyseStarten.innerHTML;
  analyseStarten.disabled = true;
  analyseStarten.innerHTML = '<span class="ladekreis"></span> Dokument wird analysiert …';
  dialogNachricht('assistent', 'Ich lese das Dokument, unterscheide feste Inhalte von variablen Feldern und bestimme ihre Positionen.');
  const daten = new FormData();
  daten.append('datei', aktuelleDatei);
  daten.append('name', $('#vorlagenName')?.value || 'Neue Dokumentvorlage');
  try {
    const antwort = await fetch('/api/vorlagen/analysieren', { method: 'POST', body: daten });
    const inhalt = await antwort.json();
    if (!antwort.ok) throw new Error(inhalt.detail || 'Die Analyse ist fehlgeschlagen.');
    aktuelleVorlage = inhalt.vorlage_id;
    ergebnisZeigen(inhalt.schema);
    dialogNachricht('assistent', `Ich habe ${inhalt.schema.felder?.length || 0} veränderliche Felder erkannt. Prüfen Sie die Liste oder beschreiben Sie eine Korrektur.`);
    dialogAktivieren(true);
    meldung('Die Dokumentstruktur wurde erfolgreich erkannt.');
  } catch (fehler) {
    dialogNachricht('assistent', `Die Analyse konnte nicht abgeschlossen werden. ${fehler.message}`);
    meldung(fehler.message, 'fehler');
  } finally {
    analyseStarten.disabled = false;
    analyseStarten.innerHTML = ursprung;
  }
});

function dialogNachricht(rolle, text, ziel = '#dialogVerlauf') {
  const verlauf = $(ziel);
  if (!verlauf) return;
  const element = document.createElement('div');
  element.className = `dialognachricht ${rolle === 'nutzer' ? 'nutzer' : 'assistent'}`;
  element.textContent = text;
  verlauf.appendChild(element);
  verlauf.scrollTop = verlauf.scrollHeight;
}
function dialogAktivieren(aktiv) {
  const text = $('#dialogText'); const knopf = $('#dialogFormular button');
  if (text) text.disabled = !aktiv;
  if (knopf) knopf.disabled = !aktiv;
}
function sicher(text) { const element = document.createElement('div'); element.textContent = String(text ?? ''); return element.innerHTML; }
function typBezeichnung(typ) { return ({ text:'Text',mehrzeilig:'Mehrzeiliger Text',datum:'Datum',zahl:'Zahl',betrag:'Betrag',auswahl:'Auswahl',kontrollfeld:'Kontrollfeld',unterschrift:'Unterschrift',bild:'Bild',bilderliste:'Bilderliste',tabelle:'Tabelle' })[typ] || 'Text'; }
function ergebnisZeigen(schema) {
  $('#ergebnisBereich')?.classList.remove('versteckt');
  $('#dokumentArt').textContent = schema.dokumentart || 'Erkannte Dokumentvorlage';
  $('#zusammenfassung').textContent = schema.zusammenfassung || 'Prüfen Sie die erkannten veränderlichen Inhalte.';
  const liste = $('#felderListe'); if (!liste) return; liste.innerHTML = '';
  (schema.felder || []).forEach((feld, index) => {
    const artikel = document.createElement('article'); artikel.className = 'feldkarte';
    artikel.innerHTML = `<span class="feldnummer">${String(index+1).padStart(2,'0')}</span><div class="feldinhalt"><strong>${sicher(feld.bezeichnung || 'Unbenanntes Feld')}</strong><small>${sicher(feld.hinweis || 'Automatisch erkannt')}</small></div><span class="feldtyp">${sicher(typBezeichnung(feld.typ))}</span><span class="pflichtmarke ${feld.pflichtfeld?'pflicht':''}">${feld.pflichtfeld?'Pflichtfeld':'freiwillig'}</span>`;
    liste.appendChild(artikel);
  });
  $('#ergebnisBereich').scrollIntoView({ behavior:'smooth', block:'start' });
}

$('#dialogFormular')?.addEventListener('submit', async ereignis => {
  ereignis.preventDefault(); const feld = $('#dialogText'); const nachricht = feld?.value.trim();
  if (!nachricht || !aktuelleVorlage) return;
  dialogNachricht('nutzer', nachricht); feld.value=''; dialogAktivieren(false);
  try {
    const antwort = await fetch('/api/vorlagen/korrigieren',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vorlage_id:aktuelleVorlage,nachricht})});
    const inhalt=await antwort.json(); if(!antwort.ok) throw new Error(inhalt.detail||'Die Änderung konnte nicht verarbeitet werden.');
    ergebnisZeigen(inhalt.schema); dialogNachricht('assistent',inhalt.antwort);
  } catch(fehler){dialogNachricht('assistent',fehler.message);meldung(fehler.message,'fehler')} finally{dialogAktivieren(true);feld?.focus()}
});

$('#vorlageBestaetigen')?.addEventListener('click', async () => {
  if (!aktuelleVorlage) return;
  try { const antwort=await fetch(`/api/vorlagen/${aktuelleVorlage}/bestaetigen`,{method:'POST'});const inhalt=await antwort.json();if(!antwort.ok)throw new Error(inhalt.detail||'Die Vorlage konnte nicht bestätigt werden.');meldung('Die Vorlage ist gespeichert und einsatzbereit.');window.setTimeout(()=>location.href=inhalt.weiter||`/vorlagen/${aktuelleVorlage}`,900)} catch(fehler){meldung(fehler.message,'fehler')}
});

$$('[data-vorschlag]').forEach(knopf=>knopf.addEventListener('click',()=>{const frage=knopf.dataset.vorschlag;if(frage.includes('Dokumentarten'))dialogNachricht('assistent','Unterstützt werden geschäftliche PDF-, Scan- und Bildvorlagen. Je besser die Lesbarkeit, desto genauer werden Felder und Positionen erkannt.');else dialogNachricht('assistent','Dateien werden dem angemeldeten Firmenkonto zugeordnet und nur für berechtigte Teammitglieder ausgeliefert.')}));

// Visueller Vorlageneditor
let editorSchema = null;
let editorZoom = 0.85;
const schemaElement = $('#vorlagenSchema');
if (schemaElement) {
  try { editorSchema = JSON.parse(schemaElement.textContent); } catch { editorSchema = { felder: [] }; }
  editorSchema.felder ||= [];
  editorRendern();
}

function editorRendern() {
  if (!editorSchema) return;
  const liste=$('#detailFelderListe'),overlay=$('#feldOverlay'); if(!liste||!overlay)return;
  liste.innerHTML='';overlay.innerHTML='';
  editorSchema.felder.forEach((feld,index)=>{
    const karte=document.createElement('article');karte.className='detail-feld';karte.dataset.index=index;karte.dataset.name=(feld.bezeichnung||'').toLowerCase();
    karte.innerHTML=`<i>${feldSymbol(feld.typ)}</i><div><strong>${sicher(feld.bezeichnung||'Unbenannt')}</strong><small>${sicher(typBezeichnung(feld.typ))} · Seite ${feld.seite||1}</small></div>${feld.pflichtfeld?'<b>Pflicht</b>':''}`;
    karte.addEventListener('click',()=>feldDialogOeffnen(index));liste.appendChild(karte);
    if(Number(feld.seite||1)===1){const pos=feld.position||{};const box=document.createElement('button');box.type='button';box.className='overlay-feld';box.dataset.index=index;box.style.left=`${Number(pos.x??.1)*100}%`;box.style.top=`${Number(pos.y??.2)*100}%`;box.style.width=`${Number(pos.breite??.3)*100}%`;box.style.height=`${Number(pos.hoehe??.035)*100}%`;box.innerHTML=`<span>${sicher(feld.bezeichnung||'Feld')}</span>`;box.addEventListener('click',()=>feldDialogOeffnen(index));overlay.appendChild(box)}
  });
  $$('.panel-register button b').forEach(b=>b.textContent=editorSchema.felder.length);
}
function feldSymbol(typ){return ({text:'T',mehrzeilig:'¶',datum:'D',zahl:'#',betrag:'€',auswahl:'⌄',kontrollfeld:'✓',unterschrift:'✎',bild:'▧',bilderliste:'▦',tabelle:'▤'})[typ]||'T'}

$$('.panel-register button').forEach(knopf=>knopf.addEventListener('click',()=>{const panel=knopf.dataset.panel;$$('.panel-register button').forEach(k=>k.classList.remove('aktiv'));knopf.classList.add('aktiv');$$('.panel-inhalt').forEach(p=>p.classList.toggle('aktiv',p.id===panel))}));
$('#feldSuche')?.addEventListener('input',()=>{const wert=$('#feldSuche').value.toLowerCase();$$('.detail-feld').forEach(k=>k.hidden=!k.dataset.name.includes(wert))});
function zoomAnwenden(){const container=$('#seitenContainer');if(container)container.style.transform=`scale(${editorZoom})`;$('#zoomWert').textContent=`${Math.round(editorZoom*100)} %`}
$('#zoomMinus')?.addEventListener('click',()=>{editorZoom=Math.max(.5,editorZoom-.1);zoomAnwenden()});
$('#zoomPlus')?.addEventListener('click',()=>{editorZoom=Math.min(1.3,editorZoom+.1);zoomAnwenden()});
if ($('#seitenContainer')) zoomAnwenden();

function feldDialogOeffnen(index=null){
  const neu=index===null;const feld=neu?{bezeichnung:'Neues Feld',schluessel:`feld_${editorSchema.felder.length+1}`,typ:'text',pflichtfeld:false,seite:1,hinweis:'Manuell hinzugefügt',position:{x:.1,y:.25,breite:.3,hoehe:.035},schriftgroesse:10}:editorSchema.felder[index];
  $('#feldIndex').value=neu?'':index;$('#feldDialogTitel').textContent=neu?'Neues variables Feld':feld.bezeichnung;$('#feldBezeichnung').value=feld.bezeichnung||'';$('#feldSchluessel').value=feld.schluessel||'';$('#feldTyp').value=feld.typ||'text';$('#feldSeite').value=feld.seite||1;$('#feldPflicht').checked=Boolean(feld.pflichtfeld);const p=feld.position||{};$('#feldX').value=Number(p.x??.1)*100;$('#feldY').value=Number(p.y??.2)*100;$('#feldBreite').value=Number(p.breite??.3)*100;$('#feldHoehe').value=Number(p.hoehe??.035)*100;$('#feldLoeschen').hidden=neu;$('#feldDialog').classList.remove('versteckt');
}
$('#feldHinzufuegen')?.addEventListener('click',()=>feldDialogOeffnen());$('#neuesFeldUnten')?.addEventListener('click',()=>feldDialogOeffnen());
$('#feldFormular')?.addEventListener('submit',ereignis=>{ereignis.preventDefault();const index=$('#feldIndex').value;const feld={bezeichnung:$('#feldBezeichnung').value.trim(),schluessel:$('#feldSchluessel').value.trim().replace(/\s+/g,'_').toLowerCase(),typ:$('#feldTyp').value,pflichtfeld:$('#feldPflicht').checked,seite:Number($('#feldSeite').value)||1,hinweis:index===''?'Manuell hinzugefügt':(editorSchema.felder[Number(index)].hinweis||'Bearbeitbares Feld'),optionen:index===''?[]:(editorSchema.felder[Number(index)].optionen||[]),beispiel:index===''?'':(editorSchema.felder[Number(index)].beispiel||''),position:{x:Number($('#feldX').value)/100,y:Number($('#feldY').value)/100,breite:Number($('#feldBreite').value)/100,hoehe:Number($('#feldHoehe').value)/100},schriftgroesse:10};if(index==='')editorSchema.felder.push(feld);else editorSchema.felder[Number(index)]=feld;$('#feldDialog').classList.add('versteckt');editorRendern()});
$('#feldLoeschen')?.addEventListener('click',()=>{const index=$('#feldIndex').value;if(index!==''&&confirm('Dieses Feld wirklich löschen?')){editorSchema.felder.splice(Number(index),1);$('#feldDialog').classList.add('versteckt');editorRendern()}});

async function schemaSpeichern() { const id=$('#aktuelleVorlageId')?.value;if(!id||!editorSchema)return;const antwort=await fetch(`/api/vorlagen/${id}/schema`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({schema:editorSchema})});const inhalt=await antwort.json();if(!antwort.ok)throw new Error(inhalt.detail||'Die Felder konnten nicht gespeichert werden.');meldung(inhalt.hinweis) }
$('#schemaSpeichern')?.addEventListener('click',()=>schemaSpeichern().catch(f=>meldung(f.message,'fehler')));
$('#detailBestaetigen')?.addEventListener('click',async()=>{try{await schemaSpeichern();const id=$('#detailBestaetigen').dataset.vorlage;const antwort=await fetch(`/api/vorlagen/${id}/bestaetigen`,{method:'POST'});const inhalt=await antwort.json();if(!antwort.ok)throw new Error(inhalt.detail);meldung('Die Vorlage ist bestätigt und kann verwendet werden.');setTimeout(()=>location.href=inhalt.weiter,800)}catch(f){meldung(f.message,'fehler')}});
$('#detailDialogForm')?.addEventListener('submit',async ereignis=>{ereignis.preventDefault();const feld=$('#detailDialogText');const text=feld.value.trim();if(!text)return;const id=Number($('#detailDialogForm').dataset.vorlage);dialogNachricht('nutzer',text,'#detailDialogVerlauf');feld.value='';try{const antwort=await fetch('/api/vorlagen/korrigieren',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vorlage_id:id,nachricht:text})});const inhalt=await antwort.json();if(!antwort.ok)throw new Error(inhalt.detail);editorSchema=inhalt.schema;editorRendern();dialogNachricht('assistent',inhalt.antwort,'#detailDialogVerlauf')}catch(f){dialogNachricht('assistent',f.message,'#detailDialogVerlauf')}});

// Allgemeine Dialoge
function dialogSchliessen(element){element?.classList.add('versteckt')}
$$('.dialogSchliessen').forEach(knopf=>knopf.addEventListener('click',()=>dialogSchliessen(knopf.closest('.dialoghintergrund'))));
$$('.dialoghintergrund').forEach(hintergrund=>hintergrund.addEventListener('click',ereignis=>{if(ereignis.target===hintergrund)dialogSchliessen(hintergrund)}));
$('#einladungOeffnen')?.addEventListener('click',()=>$('#einladungDialog')?.classList.remove('versteckt'));
$('#tarifDialogOeffnen')?.addEventListener('click',()=>$('#tarifDialog')?.classList.remove('versteckt'));
$$('.linkKopieren').forEach(knopf=>knopf.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(knopf.dataset.link);meldung('Der Einladungslink wurde kopiert.')}catch{prompt('Einladungslink kopieren:',knopf.dataset.link)}}));

// A+ Verwaltung
let aktuellesKonto=null;
$$('.kontoBearbeiten').forEach(knopf=>knopf.addEventListener('click',()=>{aktuellesKonto=knopf.dataset.konto;$('#kontoTitel').textContent=knopf.dataset.name;$('#kontoPreis').value=knopf.dataset.preis||'';$('#kontoDokumente').value=knopf.dataset.dokumente||'';$('#kontoVorlagen').value=knopf.dataset.vorlagen||'';$('#kontoUnterkonten').value=knopf.dataset.unterkonten||'';$('#kontoSpeicher').value=knopf.dataset.speicher||'';$('#kontoDialog')?.classList.remove('versteckt')}));
$('#kontoFormular')?.addEventListener('submit',async ereignis=>{ereignis.preventDefault();if(!aktuellesKonto)return;const wert=id=>$(id).value===''?null:Number($(id).value);const daten={individueller_preis:wert('#kontoPreis'),dokumente:wert('#kontoDokumente'),vorlagen:wert('#kontoVorlagen'),unterkonten:wert('#kontoUnterkonten'),speicher_mb:wert('#kontoSpeicher')};try{const antwort=await fetch(`/api/verwaltung/konten/${aktuellesKonto}/grenzen`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(daten)});const inhalt=await antwort.json();if(!antwort.ok)throw new Error(inhalt.detail);dialogSchliessen($('#kontoDialog'));meldung(inhalt.hinweis);setTimeout(()=>location.reload(),800)}catch(f){meldung(f.message,'fehler')}});
$$('.tarifFormular').forEach(formular=>formular.addEventListener('submit',async ereignis=>{ereignis.preventDefault();const form=new FormData(formular);const zahl=name=>form.get(name)===''?null:Number(form.get(name));const daten={monatspreis:zahl('monatspreis'),jahrespreis:zahl('jahrespreis'),dokumente:zahl('dokumente'),vorlagen:zahl('vorlagen'),unterkonten:zahl('unterkonten'),speicher_mb:zahl('speicher_mb')};try{const antwort=await fetch(`/api/verwaltung/tarife/${formular.dataset.tarif}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(daten)});const inhalt=await antwort.json();if(!antwort.ok)throw new Error(inhalt.detail);meldung(inhalt.hinweis)}catch(f){meldung(f.message,'fehler')}}));

// Standardwert für Datumsfelder
$$('input[type="date"]').forEach(eingabe=>{if(!eingabe.value)eingabe.value=new Date().toISOString().slice(0,10)});
