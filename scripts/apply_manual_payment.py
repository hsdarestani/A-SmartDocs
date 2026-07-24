from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    if old not in content:
        raise RuntimeError(f"Erwarteter Text fehlt in {path}: {old[:100]!r}")
    write(path, content.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str) -> None:
    content = read(path)
    updated, count = re.subn(pattern, replacement, content, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"Muster wurde in {path} nicht genau einmal gefunden: {pattern[:100]!r} ({count})")
    write(path, updated)


# Datenmodell: manuelle Freischaltung und vorgemerkte Tarifwechsel.
replace_once(
    "app/models.py",
    '''    status: Mapped[str] = mapped_column(String(40), default="aktiv")
    abrechnungszeitraum: Mapped[str] = mapped_column(String(20), default="monatlich")
    individueller_preis: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
''',
    '''    status: Mapped[str] = mapped_column(String(40), default="wartet_auf_zahlung")
    abrechnungszeitraum: Mapped[str] = mapped_column(String(20), default="monatlich")
    angefragter_tarif_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    angefragter_zeitraum: Mapped[str | None] = mapped_column(String(20), nullable=True)
    zahlungshinweis: Mapped[str] = mapped_column(String(255), default="")
    aktiviert_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    individueller_preis: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
''',
)

replace_once(
    "app/migrations.py",
    '''        ("abrechnungszeitraum", "VARCHAR(20) DEFAULT 'monatlich'"),
        ("testphase_bis", "TIMESTAMP WITH TIME ZONE"),
        ("gekuendigt_zum", "TIMESTAMP WITH TIME ZONE"),
''',
    '''        ("abrechnungszeitraum", "VARCHAR(20) DEFAULT 'monatlich'"),
        ("angefragter_tarif_id", "INTEGER"),
        ("angefragter_zeitraum", "VARCHAR(20)"),
        ("zahlungshinweis", "VARCHAR(255) DEFAULT ''"),
        ("aktiviert_am", "TIMESTAMP WITH TIME ZONE"),
        ("testphase_bis", "TIMESTAMP WITH TIME ZONE"),
        ("gekuendigt_zum", "TIMESTAMP WITH TIME ZONE"),
''',
)

# Kontozugriff verlangt ein aktives Firmenkonto und ein freigeschaltetes Abonnement.
replace_once(
    "app/main.py",
    '''def aktuelles_mitglied(request: Request, db: Session) -> Mitglied | None:
    return mitglied_aus_sitzung(request, db)
''',
    '''def aktuelles_mitglied(request: Request, db: Session) -> Mitglied | None:
    mitglied = mitglied_aus_sitzung(request, db)
    if not mitglied or mitglied.ist_superadmin:
        return mitglied
    abonnement = db.scalar(select(Abonnement).where(Abonnement.organisation_id == mitglied.organisation_id))
    if not mitglied.organisation.aktiv or not abonnement or abonnement.status not in {"aktiv", "testphase", "intern"}:
        request.session.clear()
        return None
    return mitglied
''',
)

replace_once(
    "app/main.py",
    '''def _verwaltungs_kennzahlen(db: Session) -> dict[str, Any]:
    abonnements = db.scalars(select(Abonnement).options(joinedload(Abonnement.tarif))).all()
    aktive = [a for a in abonnements if a.status in {"aktiv", "testphase"}]
    monatsumsatz = sum((a.preis / 12 if a.abrechnungszeitraum == "jaehrlich" else a.preis for a in aktive), Decimal("0"))
    dokumente = db.scalar(select(func.coalesce(func.sum(Nutzungsereignis.menge), 0)).where(Nutzungsereignis.art == "dokument_erstellt")) or 0
    ki_kosten = db.scalar(select(func.coalesce(func.sum(Nutzungsereignis.kosten_euro), 0))) or Decimal("0")
    return {"aktive_abonnements": len(aktive), "monatsumsatz": monatsumsatz, "dokumente": int(dokumente), "ki_kosten": ki_kosten}
''',
    '''def _verwaltungs_kennzahlen(db: Session) -> dict[str, Any]:
    abonnements = db.scalars(select(Abonnement).options(joinedload(Abonnement.tarif))).all()
    aktive = [a for a in abonnements if a.status in {"aktiv", "testphase"}]
    wartend = [a for a in abonnements if a.status == "wartet_auf_zahlung"]
    tarifanfragen = [a for a in abonnements if a.angefragter_tarif_id is not None]
    monatsumsatz = sum((a.preis / 12 if a.abrechnungszeitraum == "jaehrlich" else a.preis for a in aktive), Decimal("0"))
    dokumente = db.scalar(select(func.coalesce(func.sum(Nutzungsereignis.menge), 0)).where(Nutzungsereignis.art == "dokument_erstellt")) or 0
    ki_kosten = db.scalar(select(func.coalesce(func.sum(Nutzungsereignis.kosten_euro), 0))) or Decimal("0")
    return {
        "aktive_abonnements": len(aktive),
        "wartende_freischaltungen": len(wartend),
        "offene_tarifanfragen": len(tarifanfragen),
        "monatsumsatz": monatsumsatz,
        "dokumente": int(dokumente),
        "ki_kosten": ki_kosten,
    }
''',
)

# Anmeldung: inaktive Konten erhalten einen klaren Freischaltungshinweis.
replace_once(
    "app/main.py",
    '''    mitglied = db.scalar(select(Mitglied).where(func.lower(Mitglied.email) == email.strip().lower()))
    if not mitglied or not passwort_pruefen(passwort, mitglied.passwort_hash) or not mitglied.aktiv:
        hinweis_setzen(request, "E-Mail-Adresse oder Passwort ist nicht korrekt.", "fehler")
        return RedirectResponse(f"/anmelden?weiter={weiter}", status_code=303)
    request.session.clear()
''',
    '''    mitglied = db.scalar(select(Mitglied).where(func.lower(Mitglied.email) == email.strip().lower()))
    if not mitglied or not passwort_pruefen(passwort, mitglied.passwort_hash):
        hinweis_setzen(request, "E-Mail-Adresse oder Passwort ist nicht korrekt.", "fehler")
        return RedirectResponse(f"/anmelden?weiter={weiter}", status_code=303)
    if not mitglied.aktiv or not mitglied.organisation.aktiv:
        abonnement = db.scalar(select(Abonnement).where(Abonnement.organisation_id == mitglied.organisation_id))
        if abonnement and abonnement.status == "wartet_auf_zahlung":
            hinweis_setzen(request, "Ihr Firmenkonto wartet noch auf die Zahlungsbestätigung und Freischaltung durch A+ Solution.")
            return RedirectResponse("/freischaltung-ausstehend", status_code=303)
        hinweis_setzen(request, "Dieses Firmenkonto ist derzeit nicht freigeschaltet. Bitte kontaktieren Sie A+ Solution.", "fehler")
        return RedirectResponse("/anmelden", status_code=303)
    request.session.clear()
''',
)

# Registrierung: Konto und Rechnung werden angelegt, aber erst nach Offline-Zahlung aktiviert.
replace_once(
    "app/main.py",
    '''    organisation = Organisation(name=unternehmen.strip(), branche="Dienstleistung")
    db.add(organisation)
    db.flush()
    mitglied = Mitglied(organisation_id=organisation.id, name=name.strip(), email=email, passwort_hash=passwort_hash, rolle=Kontorolle.INHABER, email_bestaetigt=True, letzter_zugriff=datetime.now(timezone.utc))
    db.add(mitglied)
    db.add(Abonnement(organisation_id=organisation.id, tarif_id=tarif.id, status="testphase", testphase_bis=datetime.now(timezone.utc) + timedelta(days=14), verlaengert_am=datetime.now(timezone.utc) + timedelta(days=14)))
    db.commit()
    db.refresh(mitglied)
    request.session.clear()
    request.session["mitglied_id"] = mitglied.id
    hinweis_setzen(request, "Willkommen bei A+ SmartDocs. Ihre 14-tägige Testphase ist aktiviert.")
    return RedirectResponse("/arbeitsbereich", status_code=303)
''',
    '''    organisation = Organisation(name=unternehmen.strip(), branche="Dienstleistung", aktiv=False)
    db.add(organisation)
    db.flush()
    mitglied = Mitglied(
        organisation_id=organisation.id,
        name=name.strip(),
        email=email,
        passwort_hash=passwort_hash,
        rolle=Kontorolle.INHABER,
        email_bestaetigt=True,
        aktiv=False,
    )
    db.add(mitglied)
    abonnement = Abonnement(
        organisation_id=organisation.id,
        tarif_id=tarif.id,
        status="wartet_auf_zahlung",
        abrechnungszeitraum="monatlich",
        verlaengert_am=datetime.now(timezone.utc),
    )
    db.add(abonnement)
    nummer = f"ASD-{datetime.now().year}-{1000 + (db.scalar(select(func.count(Rechnung.id))) or 0) + 1}"
    db.add(Rechnung(
        organisation_id=organisation.id,
        nummer=nummer,
        betrag=tarif.monatspreis,
        status="zahlung_ausstehend",
        abrechnungszeitraum=f"{tarif.name} / Monatlich",
        faellig_am=datetime.now(timezone.utc),
    ))
    db.commit()
    request.session.clear()
    hinweis_setzen(request, "Ihre Registrierung wurde gespeichert. Das Konto wird nach Bestätigung der Offline-Zahlung durch A+ Solution freigeschaltet.")
    return RedirectResponse("/freischaltung-ausstehend", status_code=303)
''',
)

replace_once(
    "app/main.py",
    '''@app.get("/passwort-vergessen", response_class=HTMLResponse)
def passwort_vergessen_seite(request: Request, db: Session = Depends(datenbank_sitzung)):
''',
    '''@app.get("/freischaltung-ausstehend", response_class=HTMLResponse)
def freischaltung_ausstehend(request: Request, db: Session = Depends(datenbank_sitzung)):
    request.session.pop("mitglied_id", None)
    kontext = grundkontext(request, db, "freischaltung")
    kontext["mitglied"] = None
    kontext["organisation"] = None
    return vorlagen.TemplateResponse("freischaltung_ausstehend.html", kontext)


@app.get("/passwort-vergessen", response_class=HTMLResponse)
def passwort_vergessen_seite(request: Request, db: Session = Depends(datenbank_sitzung)):
''',
)

# Abrechnung zeigt eine vorgemerkte Anfrage, ohne den Tarif sofort zu ändern.
replace_once(
    "app/main.py",
    '''    kontext = grundkontext(request, db, "abrechnung")
    kontext.update({"abonnement": abo, "rechnungen": rechnungen, "tarife": tarife, "kennzahlen": _organisation_kennzahlen(db, mitglied.organisation_id)})
    return vorlagen.TemplateResponse("abrechnung.html", kontext)
''',
    '''    kontext = grundkontext(request, db, "abrechnung")
    angefragter_tarif = db.get(Tarif, abo.angefragter_tarif_id) if abo and abo.angefragter_tarif_id else None
    kontext.update({
        "abonnement": abo,
        "angefragter_tarif": angefragter_tarif,
        "rechnungen": rechnungen,
        "tarife": tarife,
        "kennzahlen": _organisation_kennzahlen(db, mitglied.organisation_id),
    })
    return vorlagen.TemplateResponse("abrechnung.html", kontext)
''',
)

regex_once(
    "app/main.py",
    r'''@app\.post\("/abrechnung/tarif-wechseln"\)\ndef tarif_wechseln\(.*?\n\n@app\.get\("/verwaltung", response_class=HTMLResponse\)''',
    '''@app.post("/abrechnung/tarif-wechseln")
def tarif_wechseln(request: Request, tarif_id: int = Form(...), zeitraum: str = Form("monatlich"), db: Session = Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    if mitglied.rolle != Kontorolle.INHABER:
        hinweis_setzen(request, "Nur der Kontoinhaber kann einen Tarifwechsel anfragen.", "fehler")
        return RedirectResponse("/abrechnung", status_code=303)
    tarif = db.get(Tarif, tarif_id)
    abonnement = db.scalar(select(Abonnement).where(Abonnement.organisation_id == mitglied.organisation_id))
    if not tarif or not abonnement or not tarif.aktiv:
        hinweis_setzen(request, "Die Tarifanfrage konnte nicht gespeichert werden.", "fehler")
        return RedirectResponse("/abrechnung", status_code=303)
    zeitraum = "jaehrlich" if zeitraum == "jaehrlich" else "monatlich"
    abonnement.angefragter_tarif_id = tarif.id
    abonnement.angefragter_zeitraum = zeitraum
    betrag = tarif.jahrespreis if zeitraum == "jaehrlich" and tarif.jahrespreis else tarif.monatspreis
    nummer = f"ASD-{datetime.now().year}-{1000 + (db.scalar(select(func.count(Rechnung.id))) or 0) + 1}"
    db.add(Rechnung(
        organisation_id=mitglied.organisation_id,
        nummer=nummer,
        betrag=betrag,
        status="zahlung_ausstehend",
        abrechnungszeitraum=f"Tarifwechsel: {tarif.name} / {'Jährlich' if zeitraum == 'jaehrlich' else 'Monatlich'}",
        faellig_am=datetime.now(timezone.utc),
    ))
    db.commit()
    hinweis_setzen(request, f"Der Wechsel zu {tarif.name} wurde vorgemerkt. A+ Solution aktiviert ihn nach Bestätigung der Offline-Zahlung.")
    return RedirectResponse("/abrechnung", status_code=303)


@app.get("/verwaltung", response_class=HTMLResponse)''',
)

replace_once(
    "app/main.py",
    '''    kontext = grundkontext(request, db, "verwaltung")
    kontext.update({"kennzahlen": _verwaltungs_kennzahlen(db), "organisationen": organisationen, "tarife": tarife})
    return vorlagen.TemplateResponse("verwaltung.html", kontext)
''',
    '''    kontext = grundkontext(request, db, "verwaltung")
    kontext.update({
        "kennzahlen": _verwaltungs_kennzahlen(db),
        "organisationen": organisationen,
        "tarife": tarife,
        "tarife_nach_id": {tarif.id: tarif for tarif in tarife},
    })
    return vorlagen.TemplateResponse("verwaltung.html", kontext)
''',
)

# A+ Verwaltung bestätigt Offline-Zahlungen oder sperrt Konten.
replace_once(
    "app/main.py",
    '''@app.post("/verwaltung/zurueck")
def verwaltung_zurueck(request: Request, db: Session = Depends(datenbank_sitzung)):
''',
    '''@app.post("/verwaltung/konto/{organisation_id}/aktivieren")
def konto_aktivieren(
    organisation_id: int,
    request: Request,
    zeitraum: str = Form("monatlich"),
    zahlungshinweis: str = Form(""),
    db: Session = Depends(datenbank_sitzung),
):
    admin = muss_verwalten_duerfen(request, db)
    organisation = db.get(Organisation, organisation_id)
    abonnement = db.scalar(select(Abonnement).where(Abonnement.organisation_id == organisation_id))
    if not organisation or not abonnement:
        hinweis_setzen(request, "Das Kundenkonto wurde nicht gefunden.", "fehler")
        return RedirectResponse("/verwaltung", status_code=303)
    if organisation.id == admin.organisation_id:
        hinweis_setzen(request, "Das interne A+ Konto kann hier nicht verändert werden.", "fehler")
        return RedirectResponse("/verwaltung", status_code=303)

    if abonnement.angefragter_tarif_id:
        angefragter_tarif = db.get(Tarif, abonnement.angefragter_tarif_id)
        if angefragter_tarif and angefragter_tarif.aktiv:
            abonnement.tarif_id = angefragter_tarif.id
    zeitraum = abonnement.angefragter_zeitraum or ("jaehrlich" if zeitraum == "jaehrlich" else "monatlich")
    abonnement.abrechnungszeitraum = zeitraum
    abonnement.status = "aktiv"
    abonnement.testphase_bis = None
    abonnement.aktiviert_am = datetime.now(timezone.utc)
    abonnement.verlaengert_am = datetime.now(timezone.utc) + (timedelta(days=365) if zeitraum == "jaehrlich" else timedelta(days=30))
    abonnement.zahlungshinweis = zahlungshinweis.strip()
    abonnement.angefragter_tarif_id = None
    abonnement.angefragter_zeitraum = None
    organisation.aktiv = True
    for konto in organisation.mitglieder:
        konto.aktiv = True

    offene_rechnung = db.scalar(
        select(Rechnung)
        .where(Rechnung.organisation_id == organisation_id, Rechnung.status == "zahlung_ausstehend")
        .order_by(Rechnung.erstellt_am.desc())
    )
    betrag = abonnement.preis
    if offene_rechnung:
        offene_rechnung.status = "bezahlt"
        offene_rechnung.betrag = betrag
        offene_rechnung.faellig_am = datetime.now(timezone.utc)
    else:
        nummer = f"ASD-{datetime.now().year}-{1000 + (db.scalar(select(func.count(Rechnung.id))) or 0) + 1}"
        db.add(Rechnung(
            organisation_id=organisation_id,
            nummer=nummer,
            betrag=betrag,
            status="bezahlt",
            abrechnungszeitraum="Jahresabonnement" if zeitraum == "jaehrlich" else datetime.now().strftime("%m/%Y"),
            faellig_am=datetime.now(timezone.utc),
        ))
    db.commit()
    hinweis_setzen(request, f"Zahlung bestätigt: {organisation.name} ist jetzt freigeschaltet.")
    return RedirectResponse("/verwaltung", status_code=303)


@app.post("/verwaltung/konto/{organisation_id}/sperren")
def konto_sperren(organisation_id: int, request: Request, db: Session = Depends(datenbank_sitzung)):
    admin = muss_verwalten_duerfen(request, db)
    organisation = db.get(Organisation, organisation_id)
    abonnement = db.scalar(select(Abonnement).where(Abonnement.organisation_id == organisation_id))
    if not organisation or not abonnement or organisation.id == admin.organisation_id:
        hinweis_setzen(request, "Das Konto konnte nicht gesperrt werden.", "fehler")
        return RedirectResponse("/verwaltung", status_code=303)
    organisation.aktiv = False
    abonnement.status = "gesperrt"
    for konto in organisation.mitglieder:
        konto.aktiv = False
    db.commit()
    hinweis_setzen(request, f"Das Konto von {organisation.name} wurde gesperrt.")
    return RedirectResponse("/verwaltung", status_code=303)


@app.post("/verwaltung/zurueck")
def verwaltung_zurueck(request: Request, db: Session = Depends(datenbank_sitzung)):
''',
)

# Registrierungstext für manuelle Zahlung.
write(
    "app/templates/registrieren.html",
    '''{% extends "base.html" %}
{% block titel %}Firmenkonto beantragen – A+ SmartDocs{% endblock %}
{% block oeffentlicher_inhalt %}
<section class="auth-seite registrierung">
  <div class="auth-bild">
    <a class="marke" href="/"><span class="marken-symbol">A+</span><span class="marken-text"><strong>SmartDocs</strong><small>von A+ Solution</small></span></a>
    <div><span class="hinweismarke"><span></span>Manuelle Freischaltung</span><h1>Ihr Firmenkonto startet nach <em>Zahlungsbestätigung.</em></h1><p>Sie wählen den passenden Tarif und legen Ihre Zugangsdaten an. Die Zahlung erfolgt außerhalb der Anwendung. Sobald A+ Solution den Zahlungseingang bestätigt, wird Ihr Arbeitsbereich freigeschaltet.</p></div>
    <div class="registrierungs-vorteile"><span>01 / Getrenntes Firmenkonto</span><span>02 / Manuell bestätigte Freischaltung</span><span>03 / Teamkonten und Rollen</span><span>04 / Wiederverwendbare PDF-Abläufe</span></div>
  </div>
  <div class="auth-formular"><div class="auth-box breit-box"><span class="uebertitel">Neues Firmenkonto</span><h2>Konto beantragen</h2><p>Nach der Registrierung erhalten Sie die Zahlungsinformationen direkt von A+ Solution. Es findet keine Online-Abbuchung statt.</p><form action="/registrieren" method="post" class="formular-stapel"><div class="formular-zweispaltig"><label><span>Unternehmen</span><input type="text" name="unternehmen" placeholder="Muster GmbH" required></label><label><span>Ihr vollständiger Name</span><input type="text" name="name" placeholder="Anna Schneider" required></label></div><label><span>Geschäftliche E-Mail-Adresse</span><input type="email" name="email" placeholder="anna@unternehmen.de" required></label><label><span>Passwort</span><div class="passwortfeld"><input type="password" name="passwort" minlength="8" placeholder="Mindestens 8 Zeichen" required><button type="button" class="passwort-zeigen" aria-label="Passwort anzeigen">◉</button></div></label><fieldset class="tarifauswahl"><legend>Gewünschter Tarif</legend>{% for tarif in tarife %}<label class="tarifoption {% if gewaehlter_tarif == tarif.id or (not gewaehlter_tarif and tarif.name == 'Unternehmen') %}ausgewaehlt{% endif %}"><input type="radio" name="tarif_id" value="{{ tarif.id }}" {% if gewaehlter_tarif == tarif.id or (not gewaehlter_tarif and tarif.name == 'Unternehmen') %}checked{% endif %}><span><strong>{{ tarif.name }}</strong><small>{{ tarif.dokumente_monat }} Dokumente · {{ tarif.unterkonten }} Unterkonten</small></span><b>{{ tarif.monatspreis|geld }}</b></label>{% endfor %}</fieldset><label class="kontrollzeile"><input type="checkbox" name="datenschutz" value="ja" required><span>Ich akzeptiere die Datenschutz- und Nutzungsbedingungen.</span></label><button class="schaltflaeche primaer breit" type="submit">Registrierung absenden <span>→</span></button></form><p class="auth-wechsel">Bereits freigeschaltet? <a href="/anmelden">Zum Arbeitsbereich anmelden</a></p></div></div>
</section>
{% endblock %}
''',
)

write(
    "app/templates/freischaltung_ausstehend.html",
    '''{% extends "base.html" %}
{% block titel %}Freischaltung ausstehend – A+ SmartDocs{% endblock %}
{% block oeffentlicher_inhalt %}
<section class="freischaltung-seite">
  <div class="freischaltung-karte">
    <a class="marke" href="/"><span class="marken-symbol">A+</span><span class="marken-text"><strong>SmartDocs</strong><small>von A+ Solution</small></span></a>
    <span class="freischaltung-code">STATUS / PAYMENT REVIEW</span>
    <div class="freischaltung-symbol">✓</div>
    <span class="uebertitel">Registrierung eingegangen</span>
    <h1>Ihr Konto wartet auf die Freischaltung.</h1>
    <p>Die Zahlung wird offline außerhalb von A+ SmartDocs abgewickelt. Sobald der zuständige Ansprechpartner den Zahlungseingang an A+ Solution bestätigt hat, aktiviert die A+ Verwaltung Ihr Firmenkonto.</p>
    <div class="freischaltung-schritte">
      <article><i>01</i><div><strong>Registrierung gespeichert</strong><small>Unternehmen, Inhaber und Tarif wurden angelegt.</small></div></article>
      <article class="aktiv"><i>02</i><div><strong>Offline-Zahlung bestätigen</strong><small>Die Zahlungsabwicklung erfolgt direkt mit A+ Solution.</small></div></article>
      <article><i>03</i><div><strong>Konto wird freigeschaltet</strong><small>Danach können Sie sich mit Ihren Zugangsdaten anmelden.</small></div></article>
    </div>
    <div class="freischaltung-aktionen"><a class="schaltflaeche primaer" href="/anmelden">Freischaltung prüfen</a><a class="schaltflaeche sekundaer" href="/">Zur Startseite</a></div>
  </div>
</section>
{% endblock %}
''',
)

write(
    "app/templates/abrechnung.html",
    '''{% extends "base.html" %}
{% block titel %}Tarif und Abrechnung – A+ SmartDocs{% endblock %}
{% block inhalt %}
<section class="seitenrahmen">
  <div class="seitenkopf">
    <div><span class="uebertitel">Tarif und Verbrauch</span><h1>Abrechnung</h1><p>Aktueller Tarif, Nutzungsgrenzen und manuell bestätigte Zahlungen Ihres Unternehmens.</p></div>
    <span class="zustandsmarke {% if abonnement.status in ['aktiv','testphase','intern'] %}bereit{% endif %}">{{ abonnement.status }}</span>
  </div>

  {% if angefragter_tarif %}
  <section class="zahlungs-anfrage-banner">
    <div><span class="uebertitel">Offene Tarifanfrage</span><h2>{{ angefragter_tarif.name }}</h2><p>{{ 'Jährliche' if abonnement.angefragter_zeitraum == 'jaehrlich' else 'Monatliche' }} Abrechnung · Aktivierung nach Bestätigung der Offline-Zahlung durch A+ Solution.</p></div>
    <span>Prüfung ausstehend</span>
  </section>
  {% endif %}

  <div class="abrechnungs-gitter">
    <section class="aktuelle-tarifkarte">
      <div><span class="uebertitel">Aktueller Tarif</span><h2>{{ abonnement.tarif.name }}</h2><p>{{ abonnement.tarif.beschreibung }}</p><div class="tarif-preis"><strong>{{ abonnement.preis|geld }}</strong><small>/ {{ 'Jahr' if abonnement.abrechnungszeitraum == 'jaehrlich' else 'Monat' }}</small></div></div>
      <div class="tarif-verbrauch">
        <article><span><strong>Dokumente</strong><small>{{ kennzahlen.dokumente }} von {{ abonnement.dokument_limit }}</small></span><div><i style="--fortschritt:{{ kennzahlen.verbrauch_prozent }}%"></i></div></article>
        <article><span><strong>Vorlagen</strong><small>{{ kennzahlen.vorlagen }} von {{ abonnement.vorlagen_limit }}</small></span><div><i style="--fortschritt:{{ (kennzahlen.vorlagen / abonnement.vorlagen_limit * 100) if abonnement.vorlagen_limit else 0 }}%"></i></div></article>
        <article><span><strong>Teamkonten</strong><small>{{ kennzahlen.mitglieder }} von {{ abonnement.unterkonten_limit + 1 }}</small></span><div><i style="--fortschritt:{{ (kennzahlen.mitglieder / (abonnement.unterkonten_limit + 1) * 100) }}%"></i></div></article>
      </div>
    </section>

    <section class="inhaltskarte zahlungsart">
      <div class="kartenkopf"><div><h2>Manuelle Zahlung</h2><p>Offline-Abwicklung durch A+ Solution</p></div></div>
      <div class="kartenabbildung zahlungsmodus"><span>A+ BILLING</span><strong>OFFLINE PAYMENT</strong><small>Freischaltung durch die Verwaltung</small></div>
      <p class="zahlungs-hinweis">Es werden keine Karten- oder Bankdaten in A+ SmartDocs gespeichert. Nach einer Zahlung bestätigt die A+ Verwaltung den Vorgang und aktiviert den Tarif manuell.</p>
      <span class="zahlungs-bestaetigung">Letzte Zahlungsfreigabe: {{ abonnement.aktiviert_am|datum if abonnement.aktiviert_am else 'nicht hinterlegt' }}</span>
    </section>
  </div>

  <section class="tarifwechsel">
    <div class="kartenkopf"><div><h2>Tarifwechsel anfragen</h2><p>Die Auswahl wird nur vorgemerkt. Ihr aktueller Tarif bleibt aktiv, bis A+ Solution die Offline-Zahlung bestätigt.</p></div><div class="abrechnungsumschalter klein"><button class="aktiv" data-zeitraum="monatlich">Monatlich</button><button data-zeitraum="jaehrlich">Jährlich</button></div></div>
    <div class="tarifwechsel-raster">{% for tarif in tarife %}<form action="/abrechnung/tarif-wechseln" method="post" class="wechselkarte {% if tarif.id == abonnement.tarif_id %}aktuell{% endif %}"><input type="hidden" name="tarif_id" value="{{ tarif.id }}"><input class="zeitraumEingabe" type="hidden" name="zeitraum" value="monatlich"><div><span>{{ tarif.name }}</span>{% if tarif.id == abonnement.tarif_id %}<b>Aktuell</b>{% endif %}</div><strong class="monatspreis" data-monat="{{ tarif.monatspreis }}" data-jahr="{{ tarif.jahrespreis }}">{{ tarif.monatspreis|geld }}</strong><small>{{ tarif.dokumente_monat }} Dokumente · {{ tarif.vorlagen }} Vorlagen · {{ tarif.unterkonten }} Unterkonten</small><button class="schaltflaeche {% if tarif.id == abonnement.tarif_id %}sekundaer{% else %}primaer{% endif %} breit" type="submit" {% if tarif.id == abonnement.tarif_id %}disabled{% endif %}>{{ 'Aktiver Tarif' if tarif.id == abonnement.tarif_id else 'Tarif anfragen' }}</button></form>{% endfor %}</div>
  </section>

  <section class="inhaltskarte rechnungsliste">
    <div class="kartenkopf"><div><h2>Zahlungs- und Rechnungsverlauf</h2><p>Manuell bestätigte und noch offene Abrechnungsvorgänge</p></div></div>
    <div class="tabellenrahmen"><table><thead><tr><th>Vorgangsnummer</th><th>Tarif / Zeitraum</th><th>Datum</th><th>Betrag</th><th>Status</th></tr></thead><tbody>{% for rechnung in rechnungen %}<tr><td><strong>{{ rechnung.nummer }}</strong></td><td>{{ rechnung.abrechnungszeitraum }}</td><td>{{ rechnung.erstellt_am|datum }}</td><td>{{ rechnung.betrag|geld }}</td><td><span class="zustandsmarke {% if rechnung.status == 'bezahlt' %}bereit{% endif %}">{{ rechnung.status }}</span></td></tr>{% else %}<tr><td colspan="5">Noch keine Abrechnungsvorgänge vorhanden.</td></tr>{% endfor %}</tbody></table></div>
  </section>
</section>
{% endblock %}
''',
)

write(
    "app/templates/verwaltung.html",
    '''{% extends "base.html" %}
{% block titel %}Verwaltungszentrale – A+ SmartDocs{% endblock %}
{% block inhalt %}
<section class="seitenrahmen verwaltungsseite">
  <div class="seitenkopf"><div><span class="uebertitel">A+ SmartDocs Verwaltung</span><h1>Kunden, Zahlungen und Kontosteuerung</h1><p>Offline-Zahlungen bestätigen, Firmenkonten freischalten und Tarife zentral verwalten.</p></div><div class="seitenaktionen"><button id="tarifDialogOeffnen" class="schaltflaeche sekundaer">Tarife bearbeiten</button></div></div>

  <div class="kennzahlenraster verwaltung">
    <article class="kennzahlkarte hervorgehoben"><div class="kartenzeichen">€</div><div><small>Aktivierter Monatsumsatz</small><strong>{{ kennzahlen.monatsumsatz|geld }}</strong><span>nur freigeschaltete Konten</span></div></article>
    <article class="kennzahlkarte warnung"><div class="kartenzeichen">!</div><div><small>Warten auf Freischaltung</small><strong>{{ kennzahlen.wartende_freischaltungen }}</strong><span>Zahlung manuell prüfen</span></div></article>
    <article class="kennzahlkarte"><div class="kartenzeichen">◉</div><div><small>Aktive Abonnements</small><strong>{{ kennzahlen.aktive_abonnements }}</strong><span>einschließlich Testkonten</span></div></article>
    <article class="kennzahlkarte"><div class="kartenzeichen">↗</div><div><small>Offene Tarifwechsel</small><strong>{{ kennzahlen.offene_tarifanfragen }}</strong><span>nach Zahlung aktivieren</span></div></article>
  </div>

  <section class="inhaltskarte kontenkarte">
    <div class="kartenkopf"><div><h2>Kundenkonten</h2><p>Status, Tarif, Zahlungsprüfung und individuelle Grenzen</p></div><div class="tabellenaktionen"><label><span>⌕</span><input id="kontenSuche" type="search" placeholder="Konto suchen …"></label></div></div>
    <div class="tabellenrahmen"><table id="kontenTabelle"><thead><tr><th>Unternehmen</th><th>Aktueller Tarif</th><th>Anfrage</th><th>Monatspreis</th><th>Status</th><th>Verwaltung</th></tr></thead><tbody>
    {% for org in organisationen %}{% set abo = org.abonnement %}{% if abo %}{% set wunsch = tarife_nach_id.get(abo.angefragter_tarif_id) if abo.angefragter_tarif_id else none %}
      <tr data-name="{{ org.name|lower }}">
        <td><div class="unternehmenszelle"><span>{{ org.name[:2]|upper }}</span><div><strong>{{ org.name }}</strong><small>{{ org.branche }} · {{ org.mitglieder|length }} Konto/Konten</small></div></div></td>
        <td><span class="tarifmarke">{{ abo.tarif.name }}</span><small>{{ abo.dokument_limit }} Dokumente / Monat</small></td>
        <td>{% if wunsch %}<strong>{{ wunsch.name }}</strong><small>{{ 'jährlich' if abo.angefragter_zeitraum == 'jaehrlich' else 'monatlich' }}</small>{% else %}<span>–</span>{% endif %}</td>
        <td><strong>{{ abo.preis|geld }}</strong></td>
        <td><span class="zustandsmarke {% if abo.status in ['aktiv','testphase','intern'] %}bereit{% endif %}">{{ abo.status }}</span></td>
        <td><div class="admin-zeilenaktionen">
          {% if not mitglied or org.id != mitglied.organisation_id %}
            {% if abo.status == 'wartet_auf_zahlung' or abo.status == 'gesperrt' or wunsch %}
              <form action="/verwaltung/konto/{{ org.id }}/aktivieren" method="post" onsubmit="return confirm('Offline-Zahlung bestätigen und dieses Konto freischalten?')"><input type="hidden" name="zeitraum" value="{{ abo.angefragter_zeitraum or abo.abrechnungszeitraum or 'monatlich' }}"><button class="admin-aktivieren" type="submit" title="Zahlung bestätigen und aktivieren">✓ Aktivieren</button></form>
            {% else %}
              <form action="/verwaltung/konto/{{ org.id }}/sperren" method="post" onsubmit="return confirm('Dieses Kundenkonto wirklich sperren?')"><button type="submit" title="Konto sperren">⊘</button></form>
            {% endif %}
            {% if org.aktiv %}<form action="/verwaltung/konto/{{ org.id }}/ansehen" method="post"><button type="submit" title="Kundensicht öffnen">◉</button></form>{% endif %}
          {% endif %}
          <button class="kontoBearbeiten mehrknopf" data-konto="{{ org.id }}" data-name="{{ org.name }}" data-preis="{{ abo.individueller_preis or '' }}" data-dokumente="{{ abo.dokumente_override or '' }}" data-vorlagen="{{ abo.vorlagen_override or '' }}" data-unterkonten="{{ abo.unterkonten_override or '' }}" data-speicher="{{ abo.speicher_override_mb or '' }}">•••</button>
        </div></td>
      </tr>
    {% endif %}{% endfor %}
    </tbody></table></div>
  </section>
</section>

<div id="kontoDialog" class="dialoghintergrund versteckt"><form id="kontoFormular" class="einstellungsdialog"><div class="dialogtitel"><div><span class="uebertitel">Individuelle Konditionen</span><h2 id="kontoTitel">Konto bearbeiten</h2></div><button type="button" class="dialogSchliessen">×</button></div><p>Leere Felder übernehmen automatisch die allgemeinen Tarifwerte.</p><div class="formularraster"><label><span>Monatspreis in Euro</span><input id="kontoPreis" type="number" step="0.01" min="0"></label><label><span>Dokumente pro Monat</span><input id="kontoDokumente" type="number" min="0"></label><label><span>Vorlagen</span><input id="kontoVorlagen" type="number" min="0"></label><label><span>Unterkonten</span><input id="kontoUnterkonten" type="number" min="0"></label><label class="volle-breite"><span>Speicher in MB</span><input id="kontoSpeicher" type="number" min="0"></label></div><div class="dialogaktionen"><button type="button" class="schaltflaeche sekundaer dialogSchliessen">Abbrechen</button><button type="submit" class="schaltflaeche primaer">Änderungen speichern</button></div></form></div>
<div id="tarifDialog" class="dialoghintergrund versteckt"><div class="einstellungsdialog tarif-dialog"><div class="dialogtitel"><div><span class="uebertitel">Allgemeine Tarifwerte</span><h2>Tarife bearbeiten</h2></div><button type="button" class="dialogSchliessen">×</button></div><div class="tarif-editor-liste">{% for tarif in tarife %}<form class="tarifFormular" data-tarif="{{ tarif.id }}"><div class="tarif-editor-kopf"><strong>{{ tarif.name }}</strong><span>{{ tarif.beschreibung }}</span></div><div class="formularraster"><label><span>Monatspreis</span><input name="monatspreis" type="number" step="0.01" value="{{ tarif.monatspreis }}"></label><label><span>Jahrespreis</span><input name="jahrespreis" type="number" step="0.01" value="{{ tarif.jahrespreis or '' }}"></label><label><span>Dokumente</span><input name="dokumente" type="number" value="{{ tarif.dokumente_monat }}"></label><label><span>Vorlagen</span><input name="vorlagen" type="number" value="{{ tarif.vorlagen }}"></label><label><span>Unterkonten</span><input name="unterkonten" type="number" value="{{ tarif.unterkonten }}"></label><label><span>Speicher in MB</span><input name="speicher_mb" type="number" value="{{ tarif.speicher_mb }}"></label></div><button class="schaltflaeche sekundaer breit" type="submit">{{ tarif.name }} speichern</button></form>{% endfor %}</div></div></div>
{% endblock %}
''',
)

# Ergänzende A+ Styles.
css_path = "app/static/app-aplus.css"
css = read(css_path)
marker = "/* MANUAL-PAYMENT-FLOW */"
if marker not in css:
    css += '''

/* MANUAL-PAYMENT-FLOW */
.freischaltung-seite{min-height:calc(100vh - 90px);display:grid;place-items:center;padding:70px 24px;background:linear-gradient(135deg,var(--aplus-ice),#fff)}
.freischaltung-karte{width:min(760px,100%);background:#fff;border:1px solid var(--aplus-line);box-shadow:0 28px 80px rgba(7,28,46,.12);padding:44px;position:relative}
.freischaltung-karte>.marke{margin-bottom:42px}.freischaltung-code{position:absolute;right:28px;top:30px;font-family:"IBM Plex Mono",monospace;font-size:11px;letter-spacing:.12em;color:var(--aplus-muted)}
.freischaltung-symbol{width:64px;height:64px;border-radius:50%;display:grid;place-items:center;background:var(--aplus-navy);color:#fff;font-size:28px;margin-bottom:22px}
.freischaltung-karte h1{font-size:clamp(34px,5vw,58px);line-height:1.02;max-width:650px;margin:8px 0 18px;color:var(--aplus-navy)}
.freischaltung-karte>p{font-size:18px;line-height:1.7;color:var(--aplus-muted);max-width:680px}
.freischaltung-schritte{display:grid;gap:0;margin:34px 0;border:1px solid var(--aplus-line)}
.freischaltung-schritte article{display:flex;gap:18px;align-items:center;padding:18px 20px;border-bottom:1px solid var(--aplus-line)}.freischaltung-schritte article:last-child{border-bottom:0}
.freischaltung-schritte article.aktiv{background:var(--aplus-ice)}.freischaltung-schritte i{font-family:"IBM Plex Mono",monospace;color:var(--aplus-blue);font-style:normal;font-weight:600}.freischaltung-schritte div{display:grid;gap:3px}.freischaltung-schritte small{color:var(--aplus-muted)}
.freischaltung-aktionen{display:flex;gap:12px;flex-wrap:wrap}
.zahlungs-anfrage-banner{display:flex;justify-content:space-between;gap:24px;align-items:center;background:var(--aplus-navy);color:#fff;padding:24px 28px;margin-bottom:24px}.zahlungs-anfrage-banner h2{font-size:28px;margin:4px 0}.zahlungs-anfrage-banner p{color:#c9dbe4;margin:0}.zahlungs-anfrage-banner>span{border:1px solid rgba(255,255,255,.35);padding:8px 12px;font-family:"IBM Plex Mono",monospace;font-size:12px;white-space:nowrap}
.zahlungs-bestaetigung{display:block;margin-top:14px;padding-top:14px;border-top:1px solid var(--aplus-line);font-size:13px;color:var(--aplus-muted)}
.kennzahlkarte.warnung{border-color:#dfb75f}.kennzahlkarte.warnung .kartenzeichen{background:#fff3d8;color:#825b08}
.admin-zeilenaktionen .admin-aktivieren{width:auto;padding:8px 11px;border-radius:3px;background:var(--aplus-blue);color:#fff;font-size:12px;font-weight:600;white-space:nowrap}
@media(max-width:700px){.freischaltung-karte{padding:30px 22px}.freischaltung-code{position:static;display:block;margin:-24px 0 28px}.zahlungs-anfrage-banner{align-items:flex-start;flex-direction:column}}
'''
    write(css_path, css)

# Automatische Prüfung erweitert den echten manuellen Freischaltungsablauf.
write(
    "scripts/pruefung.py",
    '''from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DOMAIN"] = "localhost"
os.environ["DATABASE_URL"] = "sqlite:////tmp/a-smartdocs-pruefung.sqlite3"
os.environ["DATENPFAD"] = "/tmp/a-smartdocs-pruefung-daten"
os.environ["APP_SECRET"] = "nur-fuer-automatische-pruefung"

Path("/tmp/a-smartdocs-pruefung.sqlite3").unlink(missing_ok=True)
shutil.rmtree("/tmp/a-smartdocs-pruefung-daten", ignore_errors=True)

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import Sitzung
from app.main import app
from app.models import Organisation


def anmelden(client: TestClient, email: str, passwort: str, weiter: str) -> None:
    antwort = client.post("/anmelden", data={"email": email, "passwort": passwort, "weiter": weiter}, follow_redirects=False)
    assert antwort.status_code == 303
    assert antwort.headers["location"] == weiter


def pruefen() -> None:
    with TestClient(app) as client:
        for pfad in ["/", "/preise", "/anmelden", "/registrieren", "/freischaltung-ausstehend"]:
            antwort = client.get(pfad)
            assert antwort.status_code == 200, (pfad, antwort.status_code)
            assert "A+ SmartDocs" in antwort.text or "SmartDocs" in antwort.text

        anmelden(client, "demo@smartdocs.de", "Aplus-Kunde-7Qm!26", "/arbeitsbereich")
        for pfad in ["/arbeitsbereich", "/vorlagen", "/vorlagen/1", "/vorlagen/1/verwenden", "/dokumente", "/team", "/einstellungen", "/abrechnung"]:
            antwort = client.get(pfad)
            assert antwort.status_code == 200, (pfad, antwort.status_code)

        antwort = client.post(
            "/vorlagen/1/verwenden",
            data={"dokumenttitel": "Automatischer Prüfbericht", "kundenname": "Prüfkunde GmbH", "leistungsdatum": "2026-07-24", "leistungen": "Automatisch geprüfte Dokumentausgabe", "ansprechpartner": "Anna Prüfung"},
            follow_redirects=False,
        )
        assert antwort.status_code == 303 and antwort.headers["location"] == "/dokumente"
        assert "Automatischer Prüfbericht" in client.get("/dokumente").text
        client.post("/abmelden")

        # Neues Kundenkonto bleibt bis zur Offline-Zahlungsbestätigung gesperrt.
        registrierung = client.post(
            "/registrieren",
            data={"unternehmen": "Freischaltung Test GmbH", "name": "Tina Test", "email": "tina@example.de", "passwort": "Sicheres-Passwort-42!", "tarif_id": 1, "datenschutz": "ja"},
            follow_redirects=False,
        )
        assert registrierung.status_code == 303
        assert registrierung.headers["location"] == "/freischaltung-ausstehend"
        gesperrt = client.post("/anmelden", data={"email": "tina@example.de", "passwort": "Sicheres-Passwort-42!", "weiter": "/arbeitsbereich"}, follow_redirects=False)
        assert gesperrt.status_code == 303
        assert gesperrt.headers["location"] == "/freischaltung-ausstehend"

        anmelden(client, "admin@aplus-solution.de", "Aplus-Admin-9Vr!26", "/verwaltung")
        verwaltung = client.get("/verwaltung")
        assert verwaltung.status_code == 200
        assert "Freischaltung Test GmbH" in verwaltung.text
        assert "Aktivieren" in verwaltung.text
        with Sitzung() as db:
            organisation = db.scalar(select(Organisation).where(Organisation.name == "Freischaltung Test GmbH"))
            assert organisation is not None
            organisation_id = organisation.id
        freigabe = client.post(f"/verwaltung/konto/{organisation_id}/aktivieren", data={"zeitraum": "monatlich", "zahlungshinweis": "Prüfzahlung"}, follow_redirects=False)
        assert freigabe.status_code == 303 and freigabe.headers["location"] == "/verwaltung"
        client.post("/abmelden")

        anmelden(client, "tina@example.de", "Sicheres-Passwort-42!", "/arbeitsbereich")
        assert client.get("/arbeitsbereich").status_code == 200

    print("A+ SmartDocs: automatische Produktprüfung einschließlich manueller Zahlungsfreigabe erfolgreich")


if __name__ == "__main__":
    pruefen()
''',
)

print("Manueller Zahlungs- und Freischaltungsablauf wurde eingebaut.")
