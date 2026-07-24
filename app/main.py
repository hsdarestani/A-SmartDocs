from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pypdf import PdfReader
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from starlette.middleware.sessions import SessionMiddleware

from .ai import dokument_analysieren, schema_korrigieren
from .auth import mitglied_aus_sitzung, passwort_hashen, passwort_pruefen, token_erzeugen
from .config import einstellungen
from .database import Basis, Sitzung, datenbank_sitzung, engine
from .migrations import schema_aktualisieren
from .models import (
    Abonnement,
    Dokumentausgabe,
    Dokumentvorlage,
    Einladung,
    Kontorolle,
    Mitglied,
    Nutzungsereignis,
    Organisation,
    Rechnung,
    Tarif,
    Vorlagendialog,
)
from .pdf_engine import dokument_erzeugen

cfg = einstellungen()
app = FastAPI(title="A+ SmartDocs", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=cfg.app_secret,
    session_cookie="smartdocs_sitzung",
    max_age=60 * 60 * 24 * 14,
    same_site="lax",
    https_only=cfg.domain not in {"localhost", "127.0.0.1"},
)
app.mount("/statisch", StaticFiles(directory="app/static"), name="statisch")
vorlagen = Jinja2Templates(directory="app/templates")

DEMO_KUNDEN_HASH = "scrypt$uOP7eb6QVc-L-iogqkcLKA==$9Ai2fp6duZKWp2ZwBjVpJ8nRwlc90F_mgWAKR1sHle3k952YFNw1M3GhHN60VD2rsXwDonX3w3aOOIsrck3A6w=="
DEMO_ADMIN_HASH = "scrypt$v45F1kHPpE7YEZJJR4SG5A==$F6bQd-sGT67UC_M5zlbovO5nxAPDHZnKuZ5fMGVjHYk-yafykxM1nq6O8t9McFO_Y6tp65TlyPWptwazC49tIw=="


class KorrekturEingabe(BaseModel):
    vorlage_id: int
    nachricht: str = Field(min_length=2, max_length=3000)


class SchemaEingabe(BaseModel):
    daten: dict[str, Any] = Field(alias="schema")


class KontoGrenzen(BaseModel):
    individueller_preis: Decimal | None = None
    dokumente: int | None = Field(default=None, ge=0)
    vorlagen: int | None = Field(default=None, ge=0)
    unterkonten: int | None = Field(default=None, ge=0)
    speicher_mb: int | None = Field(default=None, ge=0)


class TarifEingabe(BaseModel):
    monatspreis: Decimal = Field(ge=0)
    jahrespreis: Decimal | None = Field(default=None, ge=0)
    dokumente: int = Field(ge=0)
    vorlagen: int = Field(ge=0)
    unterkonten: int = Field(ge=0)
    speicher_mb: int = Field(ge=0)


def geld(wert: Decimal | float | int | None) -> str:
    wert = wert or 0
    return f"{float(wert):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def datum(wert: datetime | None) -> str:
    if not wert:
        return "–"
    return wert.astimezone(timezone.utc).strftime("%d.%m.%Y")


def dateigroesse(wert: int | None) -> str:
    wert = wert or 0
    if wert < 1024 * 1024:
        return f"{max(1, round(wert / 1024))} KB"
    return f"{wert / 1024 / 1024:.1f}".replace(".", ",") + " MB"


vorlagen.env.filters["geld"] = geld
vorlagen.env.filters["datum"] = datum
vorlagen.env.filters["dateigroesse"] = dateigroesse


def hinweis_setzen(request: Request, text: str, art: str = "erfolg") -> None:
    request.session["hinweis"] = {"text": text, "art": art}


def grundkontext(request: Request, db: Session, bereich: str = "") -> dict[str, Any]:
    mitglied = mitglied_aus_sitzung(request, db)
    hinweis = request.session.pop("hinweis", None)
    rueckkehr_admin = request.session.get("urspruengliche_admin_id")
    return {
        "request": request,
        "bereich": bereich,
        "mitglied": mitglied,
        "organisation": mitglied.organisation if mitglied else None,
        "ist_verwaltung": bool(mitglied and mitglied.ist_superadmin),
        "rueckkehr_admin": bool(rueckkehr_admin),
        "hinweis": hinweis,
    }


def weiterleitung_anmeldung(request: Request) -> RedirectResponse:
    ziel = request.url.path
    return RedirectResponse(url=f"/anmelden?weiter={ziel}", status_code=303)


def aktuelles_mitglied(request: Request, db: Session) -> Mitglied | None:
    mitglied = mitglied_aus_sitzung(request, db)
    if not mitglied or mitglied.ist_superadmin:
        return mitglied
    abonnement = db.scalar(select(Abonnement).where(Abonnement.organisation_id == mitglied.organisation_id))
    if not mitglied.organisation.aktiv or not abonnement or abonnement.status not in {"aktiv", "testphase", "intern"}:
        request.session.clear()
        return None
    return mitglied


def muss_angemeldet_sein(request: Request, db: Session) -> Mitglied:
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        raise HTTPException(status_code=401, detail="Bitte melden Sie sich zuerst an.")
    return mitglied


def muss_verwalten_duerfen(request: Request, db: Session) -> Mitglied:
    mitglied = muss_angemeldet_sein(request, db)
    if not mitglied.ist_superadmin:
        raise HTTPException(status_code=403, detail="Dieser Bereich ist ausschließlich für die A+ Verwaltung freigegeben.")
    return mitglied


def vorlage_fuer_mitglied(db: Session, mitglied: Mitglied, vorlage_id: int) -> Dokumentvorlage:
    eintrag = db.get(Dokumentvorlage, vorlage_id)
    if not eintrag or eintrag.organisation_id != mitglied.organisation_id:
        raise HTTPException(status_code=404, detail="Die Dokumentvorlage wurde nicht gefunden.")
    return eintrag


def ausgabe_fuer_mitglied(db: Session, mitglied: Mitglied, ausgabe_id: int) -> Dokumentausgabe:
    eintrag = db.get(Dokumentausgabe, ausgabe_id)
    if not eintrag or eintrag.organisation_id != mitglied.organisation_id:
        raise HTTPException(status_code=404, detail="Das Dokument wurde nicht gefunden.")
    return eintrag


@app.on_event("startup")
def startvorbereitung() -> None:
    Basis.metadata.create_all(bind=engine)
    schema_aktualisieren(engine)
    with Sitzung() as db:
        _tarife_sicherstellen(db)
        _demodaten_sicherstellen(db)


def _tarife_sicherstellen(db: Session) -> None:
    vorgaben = [
        {
            "name": "Start",
            "beschreibung": "Für Einzelpersonen und kleine Teams, die wiederkehrende Dokumente automatisieren möchten.",
            "monatspreis": Decimal("29.00"),
            "jahrespreis": Decimal("290.00"),
            "dokumente": 50,
            "vorlagen": 3,
            "unterkonten": 1,
            "speicher": 2048,
            "merkmale": ["50 Dokumente pro Monat", "3 intelligente Vorlagen", "1 zusätzliches Teammitglied", "Sicherer PDF-Export"],
        },
        {
            "name": "Unternehmen",
            "beschreibung": "Für wachsende Betriebe mit mehreren Mitarbeitern und regelmäßigem Dokumentenaufkommen.",
            "monatspreis": Decimal("69.00"),
            "jahrespreis": Decimal("690.00"),
            "dokumente": 250,
            "vorlagen": 15,
            "unterkonten": 5,
            "speicher": 10240,
            "merkmale": ["250 Dokumente pro Monat", "15 intelligente Vorlagen", "5 Teammitglieder", "Gemeinsame Vorlagen", "Priorisierte Verarbeitung"],
        },
        {
            "name": "Professionell",
            "beschreibung": "Für Organisationen mit hohem Volumen, individuellen Grenzen und erweiterten Verwaltungsfunktionen.",
            "monatspreis": Decimal("149.00"),
            "jahrespreis": Decimal("1490.00"),
            "dokumente": 1000,
            "vorlagen": 60,
            "unterkonten": 20,
            "speicher": 51200,
            "merkmale": ["1.000 Dokumente pro Monat", "60 intelligente Vorlagen", "20 Teammitglieder", "Individuelle Kontogrenzen", "Erweiterte Auswertungen"],
        },
    ]
    for daten in vorgaben:
        tarif = db.scalar(select(Tarif).where(Tarif.name == daten["name"]))
        if not tarif:
            tarif = Tarif(name=daten["name"], monatspreis=daten["monatspreis"], dokumente_monat=daten["dokumente"], vorlagen=daten["vorlagen"], unterkonten=daten["unterkonten"], speicher_mb=daten["speicher"])
            db.add(tarif)
        tarif.beschreibung = daten["beschreibung"]
        tarif.monatspreis = daten["monatspreis"]
        tarif.jahrespreis = daten["jahrespreis"]
        tarif.dokumente_monat = daten["dokumente"]
        tarif.vorlagen = daten["vorlagen"]
        tarif.unterkonten = daten["unterkonten"]
        tarif.speicher_mb = daten["speicher"]
        tarif.merkmale = daten["merkmale"]
        tarif.aktiv = True
    db.commit()


def _beispiel_pdf_erzeugen(ziel: Path) -> None:
    ziel.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(ziel), pagesize=A4)
    breite, hoehe = A4
    c.setFillColor(HexColor("#172033"))
    c.rect(0, hoehe - 110, breite, 110, fill=1, stroke=0)
    c.setFillColor(HexColor("#7658EF"))
    c.roundRect(42, hoehe - 78, 44, 44, 11, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(64, hoehe - 62, "A+")
    c.setFont("Helvetica-Bold", 19)
    c.drawString(102, hoehe - 54, "LEISTUNGSNACHWEIS")
    c.setFont("Helvetica", 8)
    c.setFillColor(HexColor("#AEB8C8"))
    c.drawString(102, hoehe - 72, "MUSTERWERK GEBÄUDESERVICE GMBH")
    c.setFillColor(HexColor("#202B3C"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(45, hoehe - 150, "Kunde")
    c.drawString(320, hoehe - 150, "Leistungsdatum")
    c.setFillColor(HexColor("#F0F2F6"))
    c.roundRect(42, hoehe - 205, 238, 38, 6, fill=1, stroke=0)
    c.roundRect(315, hoehe - 205, 195, 38, 6, fill=1, stroke=0)
    c.setFillColor(HexColor("#68758A"))
    c.setFont("Helvetica", 10)
    c.drawString(55, hoehe - 190, "Beispielkunde GmbH")
    c.drawString(328, hoehe - 190, "24.07.2026")
    c.setFillColor(HexColor("#202B3C"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(45, hoehe - 245, "Ausgeführte Leistungen")
    c.setFillColor(HexColor("#F0F2F6"))
    c.roundRect(42, hoehe - 400, 468, 135, 6, fill=1, stroke=0)
    c.setFillColor(HexColor("#68758A"))
    c.setFont("Helvetica", 10)
    c.drawString(55, hoehe - 290, "Grundreinigung der Büroräume und Fensterflächen")
    c.drawString(55, hoehe - 315, "Kontrolle und Dokumentation der ausgeführten Arbeiten")
    c.setFillColor(HexColor("#202B3C"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(45, 185, "Ansprechpartner")
    c.drawString(315, 185, "Unterschrift Kunde")
    c.setStrokeColor(HexColor("#C7CDD7"))
    c.line(42, 135, 270, 135)
    c.line(315, 135, 510, 135)
    c.setFillColor(HexColor("#68758A"))
    c.setFont("Helvetica", 9)
    c.drawString(45, 148, "Max Mustermann")
    c.setFont("Helvetica", 7)
    c.drawString(42, 42, "Vorlage für die Demonstration von A+ SmartDocs")
    c.save()


def _demo_schema() -> dict[str, Any]:
    return {
        "dokumentart": "Leistungsnachweis",
        "zusammenfassung": "Leistungsdokumentation mit Kundendaten, Datum, Beschreibung, Ansprechpartner und Unterschrift.",
        "felder": [
            {"schluessel": "kundenname", "bezeichnung": "Kundenname", "typ": "text", "pflichtfeld": True, "beispiel": "Beispielkunde GmbH", "seite": 1, "hinweis": "Name des Auftraggebers", "optionen": [], "position": {"x": 0.09, "y": 0.199, "breite": 0.36, "hoehe": 0.035}, "schriftgroesse": 10},
            {"schluessel": "leistungsdatum", "bezeichnung": "Leistungsdatum", "typ": "datum", "pflichtfeld": True, "beispiel": "24.07.2026", "seite": 1, "hinweis": "Datum der ausgeführten Leistung", "optionen": [], "position": {"x": 0.55, "y": 0.199, "breite": 0.25, "hoehe": 0.035}, "schriftgroesse": 10},
            {"schluessel": "leistungen", "bezeichnung": "Ausgeführte Leistungen", "typ": "mehrzeilig", "pflichtfeld": True, "beispiel": "Grundreinigung der Büroräume", "seite": 1, "hinweis": "Beschreibung der Arbeiten", "optionen": [], "position": {"x": 0.09, "y": 0.335, "breite": 0.74, "hoehe": 0.085}, "schriftgroesse": 9},
            {"schluessel": "ansprechpartner", "bezeichnung": "Ansprechpartner", "typ": "text", "pflichtfeld": False, "beispiel": "Max Mustermann", "seite": 1, "hinweis": "Kontaktperson beim Kunden", "optionen": [], "position": {"x": 0.075, "y": 0.812, "breite": 0.35, "hoehe": 0.03}, "schriftgroesse": 9},
            {"schluessel": "unterschrift", "bezeichnung": "Unterschrift Kunde", "typ": "unterschrift", "pflichtfeld": False, "beispiel": "", "seite": 1, "hinweis": "Unterschrift als Bilddatei", "optionen": [], "position": {"x": 0.53, "y": 0.775, "breite": 0.3, "hoehe": 0.07}, "schriftgroesse": 9},
        ],
        "rueckfragen": [],
    }


def _demodaten_sicherstellen(db: Session) -> None:
    unternehmen = db.scalar(select(Tarif).where(Tarif.name == "Unternehmen"))
    professionell = db.scalar(select(Tarif).where(Tarif.name == "Professionell"))
    assert unternehmen and professionell

    admin = db.scalar(select(Mitglied).where(Mitglied.email == "admin@aplus-solution.de"))
    if not admin:
        admin_org = Organisation(name="A+ Solution GmbH", branche="Software und Digitalisierung", ort="Frankfurt am Main")
        db.add(admin_org)
        db.flush()
        admin = Mitglied(organisation_id=admin_org.id, name="A+ Verwaltung", email="admin@aplus-solution.de", passwort_hash=DEMO_ADMIN_HASH, rolle=Kontorolle.INHABER, ist_superadmin=True, letzter_zugriff=datetime.now(timezone.utc))
        db.add(admin)
        db.add(Abonnement(organisation_id=admin_org.id, tarif_id=professionell.id, status="intern", individueller_preis=Decimal("0")))
    else:
        admin.passwort_hash = DEMO_ADMIN_HASH
        admin.ist_superadmin = True

    demo = db.scalar(select(Mitglied).where(Mitglied.email == "demo@smartdocs.de"))
    if not demo:
        demo_org = Organisation(name="Musterwerk Gebäudeservice GmbH", branche="Gebäudeservice", strasse="Mainzer Landstraße 120", plz="60327", ort="Frankfurt am Main", telefon="069 12345678")
        db.add(demo_org)
        db.flush()
        demo = Mitglied(organisation_id=demo_org.id, name="Anna Schneider", email="demo@smartdocs.de", passwort_hash=DEMO_KUNDEN_HASH, rolle=Kontorolle.INHABER, letzter_zugriff=datetime.now(timezone.utc))
        db.add(demo)
        db.add(Abonnement(organisation_id=demo_org.id, tarif_id=unternehmen.id, status="aktiv", testphase_bis=datetime.now(timezone.utc) + timedelta(days=14), verlaengert_am=datetime.now(timezone.utc) + timedelta(days=14)))
        db.flush()
        db.add_all([
            Mitglied(organisation_id=demo_org.id, name="Jonas Weber", email="jonas@smartdocs.demo", passwort_hash=DEMO_KUNDEN_HASH, rolle=Kontorolle.BEARBEITUNG, letzter_zugriff=datetime.now(timezone.utc) - timedelta(hours=2)),
            Mitglied(organisation_id=demo_org.id, name="Miriam Koch", email="miriam@smartdocs.demo", passwort_hash=DEMO_KUNDEN_HASH, rolle=Kontorolle.LESEN, letzter_zugriff=datetime.now(timezone.utc) - timedelta(days=1)),
        ])
        db.add_all([
            Nutzungsereignis(organisation_id=demo_org.id, art="dokument_erstellt", menge=34, kosten_euro=Decimal("0.72")),
            Nutzungsereignis(organisation_id=demo_org.id, art="vorlage_analysiert", menge=3, kosten_euro=Decimal("0.18")),
        ])
        for monate_zurueck, betrag in [(0, Decimal("69")), (1, Decimal("69")), (2, Decimal("69"))]:
            zeitpunkt = datetime.now(timezone.utc) - timedelta(days=30 * monate_zurueck)
            db.add(Rechnung(organisation_id=demo_org.id, nummer=f"ASD-2026-{1008 - monate_zurueck}", betrag=betrag, status="bezahlt", abrechnungszeitraum=zeitpunkt.strftime("%m/%Y"), faellig_am=zeitpunkt, erstellt_am=zeitpunkt))
        db.flush()
    else:
        demo.passwort_hash = DEMO_KUNDEN_HASH
        demo_org = demo.organisation

    demo_pdf = cfg.upload_pfad / "demo-leistungsnachweis.pdf"
    if not demo_pdf.exists():
        _beispiel_pdf_erzeugen(demo_pdf)
    vorhandene_vorlage = db.scalar(select(Dokumentvorlage).where(Dokumentvorlage.organisation_id == demo_org.id, Dokumentvorlage.name == "Leistungsnachweis – Demo"))
    if not vorhandene_vorlage:
        db.add(Dokumentvorlage(organisation_id=demo_org.id, erstellt_von_id=demo.id, name="Leistungsnachweis – Demo", dateiname="leistungsnachweis-demo.pdf", speicherort=str(demo_pdf), inhaltstyp="application/pdf", originalgroesse=demo_pdf.stat().st_size, status="bereit", seiten=1, erkannte_felder=5, schema=_demo_schema(), zusammenfassung=_demo_schema()["zusammenfassung"], aktualisiert_am=datetime.now(timezone.utc)))

    # Bestehende unzugeordnete Beispieldaten aus frühen Ständen dem Demokonto zuordnen.
    for eintrag in db.scalars(select(Dokumentvorlage).where(Dokumentvorlage.organisation_id.is_(None))).all():
        if Path(eintrag.speicherort).exists():
            eintrag.organisation_id = demo_org.id
            eintrag.erstellt_von_id = demo.id
    db.commit()


def _organisation_kennzahlen(db: Session, organisation_id: int) -> dict[str, Any]:
    abo = db.scalar(select(Abonnement).options(joinedload(Abonnement.tarif)).where(Abonnement.organisation_id == organisation_id))
    dokumente = db.scalar(select(func.coalesce(func.sum(Nutzungsereignis.menge), 0)).where(Nutzungsereignis.organisation_id == organisation_id, Nutzungsereignis.art == "dokument_erstellt")) or 0
    vorlagen_anzahl = db.scalar(select(func.count(Dokumentvorlage.id)).where(Dokumentvorlage.organisation_id == organisation_id)) or 0
    mitglieder = db.scalar(select(func.count(Mitglied.id)).where(Mitglied.organisation_id == organisation_id, Mitglied.aktiv.is_(True))) or 0
    ausgaben = db.scalar(select(func.count(Dokumentausgabe.id)).where(Dokumentausgabe.organisation_id == organisation_id)) or 0
    limit = abo.dokument_limit if abo else 0
    return {
        "abonnement": abo,
        "dokumente": int(dokumente),
        "vorlagen": int(vorlagen_anzahl),
        "mitglieder": int(mitglieder),
        "ausgaben": int(ausgaben),
        "dokument_limit": limit,
        "verbrauch_prozent": min(100, round(int(dokumente) / limit * 100)) if limit else 0,
    }


def _verwaltungs_kennzahlen(db: Session) -> dict[str, Any]:
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


@app.get("/", response_class=HTMLResponse)
def startseite(request: Request, db: Session = Depends(datenbank_sitzung)):
    if aktuelles_mitglied(request, db):
        return RedirectResponse("/arbeitsbereich", status_code=303)
    kontext = grundkontext(request, db, "start")
    kontext["tarife"] = db.scalars(select(Tarif).where(Tarif.aktiv.is_(True)).order_by(Tarif.monatspreis)).all()
    return vorlagen.TemplateResponse("start.html", kontext)


@app.get("/preise", response_class=HTMLResponse)
def preise(request: Request, db: Session = Depends(datenbank_sitzung)):
    kontext = grundkontext(request, db, "preise")
    kontext["mitglied"] = None
    kontext["organisation"] = None
    kontext["tarife"] = db.scalars(select(Tarif).where(Tarif.aktiv.is_(True)).order_by(Tarif.monatspreis)).all()
    return vorlagen.TemplateResponse("preise.html", kontext)


@app.get("/anmelden", response_class=HTMLResponse)
def anmelden_seite(request: Request, weiter: str = "/arbeitsbereich", db: Session = Depends(datenbank_sitzung)):
    if aktuelles_mitglied(request, db):
        return RedirectResponse("/arbeitsbereich", status_code=303)
    kontext = grundkontext(request, db, "anmelden")
    kontext["weiter"] = weiter if weiter.startswith("/") else "/arbeitsbereich"
    return vorlagen.TemplateResponse("anmelden.html", kontext)


@app.post("/anmelden")
def anmelden(request: Request, email: str = Form(...), passwort: str = Form(...), weiter: str = Form("/arbeitsbereich"), db: Session = Depends(datenbank_sitzung)):
    mitglied = db.scalar(select(Mitglied).where(func.lower(Mitglied.email) == email.strip().lower()))
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
    request.session["mitglied_id"] = mitglied.id
    mitglied.letzter_zugriff = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse(weiter if weiter.startswith("/") else "/arbeitsbereich", status_code=303)


@app.get("/registrieren", response_class=HTMLResponse)
def registrieren_seite(request: Request, tarif: int | None = None, db: Session = Depends(datenbank_sitzung)):
    if aktuelles_mitglied(request, db):
        return RedirectResponse("/arbeitsbereich", status_code=303)
    kontext = grundkontext(request, db, "registrieren")
    kontext["tarife"] = db.scalars(select(Tarif).where(Tarif.aktiv.is_(True)).order_by(Tarif.monatspreis)).all()
    kontext["gewaehlter_tarif"] = tarif
    return vorlagen.TemplateResponse("registrieren.html", kontext)


@app.post("/registrieren")
def registrieren(
    request: Request,
    unternehmen: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    passwort: str = Form(...),
    tarif_id: int = Form(...),
    datenschutz: str | None = Form(None),
    db: Session = Depends(datenbank_sitzung),
):
    email = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        hinweis_setzen(request, "Bitte geben Sie eine gültige E-Mail-Adresse ein.", "fehler")
        return RedirectResponse(f"/registrieren?tarif={tarif_id}", status_code=303)
    if db.scalar(select(Mitglied).where(func.lower(Mitglied.email) == email)):
        hinweis_setzen(request, "Für diese E-Mail-Adresse besteht bereits ein Konto.", "fehler")
        return RedirectResponse("/anmelden", status_code=303)
    if not datenschutz:
        hinweis_setzen(request, "Bitte bestätigen Sie die Datenschutz- und Nutzungsbedingungen.", "fehler")
        return RedirectResponse(f"/registrieren?tarif={tarif_id}", status_code=303)
    tarif = db.get(Tarif, tarif_id)
    if not tarif or not tarif.aktiv:
        hinweis_setzen(request, "Der ausgewählte Tarif ist nicht verfügbar.", "fehler")
        return RedirectResponse("/preise", status_code=303)
    try:
        passwort_hash = passwort_hashen(passwort)
    except ValueError as exc:
        hinweis_setzen(request, str(exc), "fehler")
        return RedirectResponse(f"/registrieren?tarif={tarif_id}", status_code=303)
    organisation = Organisation(name=unternehmen.strip(), branche="Dienstleistung", aktiv=False)
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


@app.get("/freischaltung-ausstehend", response_class=HTMLResponse)
def freischaltung_ausstehend(request: Request, db: Session = Depends(datenbank_sitzung)):
    request.session.pop("mitglied_id", None)
    kontext = grundkontext(request, db, "freischaltung")
    kontext["mitglied"] = None
    kontext["organisation"] = None
    return vorlagen.TemplateResponse("freischaltung_ausstehend.html", kontext)


@app.get("/passwort-vergessen", response_class=HTMLResponse)
def passwort_vergessen_seite(request: Request, db: Session = Depends(datenbank_sitzung)):
    return vorlagen.TemplateResponse("passwort_vergessen.html", grundkontext(request, db, "anmelden"))


@app.post("/passwort-vergessen")
def passwort_vergessen(request: Request, email: str = Form(...), db: Session = Depends(datenbank_sitzung)):
    # Für die Präsentationsfassung wird der Versand simuliert. Die Oberfläche verrät nicht, ob ein Konto existiert.
    hinweis_setzen(request, "Sofern ein Konto existiert, wurde ein Link zum Zurücksetzen des Passworts versendet.")
    return RedirectResponse("/anmelden", status_code=303)


@app.post("/abmelden")
def abmelden(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/arbeitsbereich", response_class=HTMLResponse)
def arbeitsbereich(request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    dokumentvorlagen = db.scalars(select(Dokumentvorlage).where(Dokumentvorlage.organisation_id == mitglied.organisation_id).order_by(Dokumentvorlage.aktualisiert_am.desc()).limit(6)).all()
    dokumente = db.scalars(select(Dokumentausgabe).where(Dokumentausgabe.organisation_id == mitglied.organisation_id).order_by(Dokumentausgabe.erstellt_am.desc()).limit(5)).all()
    kontext = grundkontext(request, db, "arbeitsbereich")
    kontext.update({"kennzahlen": _organisation_kennzahlen(db, mitglied.organisation_id), "vorlagen_liste": dokumentvorlagen, "dokumente_liste": dokumente})
    return vorlagen.TemplateResponse("arbeitsbereich.html", kontext)


@app.get("/vorlagen", response_class=HTMLResponse)
def vorlagen_uebersicht(request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    liste = db.scalars(select(Dokumentvorlage).where(Dokumentvorlage.organisation_id == mitglied.organisation_id).order_by(Dokumentvorlage.aktualisiert_am.desc())).all()
    kontext = grundkontext(request, db, "vorlagen")
    kontext.update({"vorlagen_liste": liste, "kennzahlen": _organisation_kennzahlen(db, mitglied.organisation_id)})
    return vorlagen.TemplateResponse("vorlagen.html", kontext)


@app.get("/vorlagen/neu", response_class=HTMLResponse)
def neue_vorlage(request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    kontext = grundkontext(request, db, "vorlagen")
    kontext["kennzahlen"] = _organisation_kennzahlen(db, mitglied.organisation_id)
    return vorlagen.TemplateResponse("vorlage_neu.html", kontext)


@app.get("/vorlagen/{vorlage_id}", response_class=HTMLResponse)
def vorlage_details(vorlage_id: int, request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    dialoge = db.scalars(select(Vorlagendialog).where(Vorlagendialog.vorlage_id == eintrag.id).order_by(Vorlagendialog.erstellt_am)).all()
    kontext = grundkontext(request, db, "vorlagen")
    kontext.update({"eintrag": eintrag, "dialoge": dialoge})
    return vorlagen.TemplateResponse("vorlage_detail.html", kontext)


@app.get("/vorlagen/{vorlage_id}/datei")
def vorlage_datei(vorlage_id: int, request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    pfad = Path(eintrag.speicherort)
    if not pfad.exists():
        raise HTTPException(status_code=404, detail="Die Originaldatei ist nicht mehr verfügbar.")
    return FileResponse(pfad, media_type=eintrag.inhaltstyp, filename=eintrag.dateiname)


@app.get("/vorlagen/{vorlage_id}/verwenden", response_class=HTMLResponse)
def vorlage_verwenden(vorlage_id: int, request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    if eintrag.status != "bereit":
        hinweis_setzen(request, "Bitte bestätigen Sie die erkannten Felder, bevor Sie die Vorlage verwenden.", "fehler")
        return RedirectResponse(f"/vorlagen/{vorlage_id}", status_code=303)
    kontext = grundkontext(request, db, "vorlagen")
    kontext["eintrag"] = eintrag
    return vorlagen.TemplateResponse("vorlage_verwenden.html", kontext)


@app.post("/vorlagen/{vorlage_id}/verwenden")
async def dokument_aus_vorlage(vorlage_id: int, request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    kennzahlen = _organisation_kennzahlen(db, mitglied.organisation_id)
    if kennzahlen["dokumente"] >= kennzahlen["dokument_limit"]:
        hinweis_setzen(request, "Das monatliche Dokumentenlimit ist erreicht. Bitte wechseln Sie den Tarif oder kontaktieren Sie die A+ Verwaltung.", "fehler")
        return RedirectResponse("/abrechnung", status_code=303)
    formular = await request.form()
    titel = str(formular.get("dokumenttitel") or f"{eintrag.name} {datetime.now().strftime('%d.%m.%Y')}").strip()
    eingaben: dict[str, Any] = {}
    temp_dateien: list[Path] = []
    for feld in eintrag.schema.get("felder", []):
        schluessel = str(feld.get("schluessel", ""))
        if not schluessel:
            continue
        wert = formular.get(schluessel)
        if isinstance(wert, UploadFile):
            if wert.filename:
                endung = Path(wert.filename).suffix.lower()[:10]
                ziel = cfg.upload_pfad / f"eingabe-{uuid.uuid4().hex}{endung}"
                inhalt = await wert.read()
                ziel.write_bytes(inhalt)
                eingaben[schluessel] = str(ziel)
                temp_dateien.append(ziel)
            else:
                eingaben[schluessel] = ""
        else:
            eingaben[schluessel] = str(wert or "")
    dateiname = f"{uuid.uuid4().hex}.pdf"
    ziel = cfg.ausgabe_pfad / dateiname
    try:
        seiten = dokument_erzeugen(Path(eintrag.speicherort), eintrag.inhaltstyp, eintrag.schema, eingaben, ziel, titel, eintrag.name)
    except Exception as exc:
        hinweis_setzen(request, f"Das PDF konnte nicht erstellt werden: {exc}", "fehler")
        return RedirectResponse(f"/vorlagen/{vorlage_id}/verwenden", status_code=303)
    ausgabe = Dokumentausgabe(organisation_id=mitglied.organisation_id, vorlage_id=eintrag.id, erstellt_von_id=mitglied.id, titel=titel, dateiname=f"{re.sub(r'[^A-Za-z0-9ÄÖÜäöüß_-]+', '-', titel).strip('-') or 'Dokument'}.pdf", speicherort=str(ziel), eingaben={k: ("[Datei]" if isinstance(v, str) and v in {str(p) for p in temp_dateien} else v) for k, v in eingaben.items()}, status="fertig", seiten=seiten, dateigroesse=ziel.stat().st_size)
    db.add(ausgabe)
    db.add(Nutzungsereignis(organisation_id=mitglied.organisation_id, art="dokument_erstellt", menge=1, kosten_euro=Decimal("0.002"), einzelheiten={"vorlage_id": eintrag.id}))
    db.commit()
    hinweis_setzen(request, "Das Dokument wurde erfolgreich erstellt und im Archiv gespeichert.")
    return RedirectResponse("/dokumente", status_code=303)


@app.get("/dokumente", response_class=HTMLResponse)
def dokumente_uebersicht(request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    liste = db.scalars(select(Dokumentausgabe).options(joinedload(Dokumentausgabe.vorlage), joinedload(Dokumentausgabe.erstellt_von)).where(Dokumentausgabe.organisation_id == mitglied.organisation_id).order_by(Dokumentausgabe.erstellt_am.desc())).all()
    kontext = grundkontext(request, db, "dokumente")
    kontext["dokumente_liste"] = liste
    return vorlagen.TemplateResponse("dokumente.html", kontext)


@app.get("/dokumente/{ausgabe_id}/herunterladen")
def dokument_herunterladen(ausgabe_id: int, request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = ausgabe_fuer_mitglied(db, mitglied, ausgabe_id)
    pfad = Path(eintrag.speicherort)
    if not pfad.exists():
        raise HTTPException(status_code=404, detail="Die PDF-Datei ist nicht mehr verfügbar.")
    return FileResponse(pfad, media_type="application/pdf", filename=eintrag.dateiname)


@app.post("/dokumente/{ausgabe_id}/loeschen")
def dokument_loeschen(ausgabe_id: int, request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = ausgabe_fuer_mitglied(db, mitglied, ausgabe_id)
    Path(eintrag.speicherort).unlink(missing_ok=True)
    db.delete(eintrag)
    db.commit()
    hinweis_setzen(request, "Das Dokument wurde gelöscht.")
    return RedirectResponse("/dokumente", status_code=303)


@app.get("/team", response_class=HTMLResponse)
def team(request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    mitglieder = db.scalars(select(Mitglied).where(Mitglied.organisation_id == mitglied.organisation_id).order_by(Mitglied.erstellt_am)).all()
    einladungen = db.scalars(select(Einladung).where(Einladung.organisation_id == mitglied.organisation_id, Einladung.angenommen.is_(False)).order_by(Einladung.erstellt_am.desc())).all()
    kontext = grundkontext(request, db, "team")
    kontext.update({"mitglieder_liste": mitglieder, "einladungen": einladungen, "kennzahlen": _organisation_kennzahlen(db, mitglied.organisation_id), "rollen": list(Kontorolle)})
    return vorlagen.TemplateResponse("team.html", kontext)


@app.post("/team/einladen")
def team_einladen(request: Request, email: str = Form(...), rolle: Kontorolle = Form(Kontorolle.NUTZUNG), db: Session = Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    if mitglied.rolle not in {Kontorolle.INHABER, Kontorolle.VERWALTUNG}:
        hinweis_setzen(request, "Nur Inhaber und Administratoren können Teammitglieder einladen.", "fehler")
        return RedirectResponse("/team", status_code=303)
    kennzahlen = _organisation_kennzahlen(db, mitglied.organisation_id)
    if kennzahlen["mitglieder"] >= kennzahlen["abonnement"].unterkonten_limit + 1:
        hinweis_setzen(request, "Das Teamlimit des aktuellen Tarifs ist erreicht.", "fehler")
        return RedirectResponse("/team", status_code=303)
    email = email.strip().lower()
    if db.scalar(select(Mitglied).where(func.lower(Mitglied.email) == email)):
        hinweis_setzen(request, "Diese E-Mail-Adresse ist bereits registriert.", "fehler")
        return RedirectResponse("/team", status_code=303)
    token = token_erzeugen(24)
    db.add(Einladung(organisation_id=mitglied.organisation_id, email=email, rolle=rolle, token=token, laeuft_ab_am=datetime.now(timezone.utc) + timedelta(days=7)))
    db.commit()
    hinweis_setzen(request, f"Einladung erstellt. Präsentationslink: {request.base_url}einladung/{token}")
    return RedirectResponse("/team", status_code=303)


@app.get("/einladung/{token}", response_class=HTMLResponse)
def einladung_annehmen_seite(token: str, request: Request, db: Session = Depends(datenbank_sitzung)):
    einladung = db.scalar(select(Einladung).options(joinedload(Einladung.organisation)).where(Einladung.token == token, Einladung.angenommen.is_(False)))
    kontext = grundkontext(request, db, "registrieren")
    kontext["mitglied"] = None
    kontext["organisation"] = None
    kontext["einladung"] = einladung
    return vorlagen.TemplateResponse("einladung.html", kontext)


@app.post("/einladung/{token}")
def einladung_annehmen(token: str, request: Request, name: str = Form(...), passwort: str = Form(...), db: Session = Depends(datenbank_sitzung)):
    einladung = db.scalar(select(Einladung).where(Einladung.token == token, Einladung.angenommen.is_(False)))
    if not einladung or einladung.laeuft_ab_am < datetime.now(timezone.utc):
        hinweis_setzen(request, "Diese Einladung ist ungültig oder abgelaufen.", "fehler")
        return RedirectResponse("/anmelden", status_code=303)
    try:
        hashwert = passwort_hashen(passwort)
    except ValueError as exc:
        hinweis_setzen(request, str(exc), "fehler")
        return RedirectResponse(f"/einladung/{token}", status_code=303)
    mitglied = Mitglied(organisation_id=einladung.organisation_id, name=name.strip(), email=einladung.email, passwort_hash=hashwert, rolle=einladung.rolle, letzter_zugriff=datetime.now(timezone.utc))
    db.add(mitglied)
    einladung.angenommen = True
    db.commit()
    db.refresh(mitglied)
    request.session.clear()
    request.session["mitglied_id"] = mitglied.id
    hinweis_setzen(request, "Ihr Teamkonto ist eingerichtet.")
    return RedirectResponse("/arbeitsbereich", status_code=303)


@app.post("/team/{mitglied_id}/status")
def team_status(mitglied_id: int, request: Request, db: Session = Depends(datenbank_sitzung)):
    aktuell = muss_angemeldet_sein(request, db)
    ziel = db.get(Mitglied, mitglied_id)
    if not ziel or ziel.organisation_id != aktuell.organisation_id or ziel.id == aktuell.id:
        raise HTTPException(status_code=404, detail="Das Teammitglied wurde nicht gefunden.")
    if aktuell.rolle not in {Kontorolle.INHABER, Kontorolle.VERWALTUNG}:
        raise HTTPException(status_code=403, detail="Diese Änderung ist nicht erlaubt.")
    ziel.aktiv = not ziel.aktiv
    db.commit()
    hinweis_setzen(request, "Der Kontostatus wurde aktualisiert.")
    return RedirectResponse("/team", status_code=303)


@app.get("/einstellungen", response_class=HTMLResponse)
def einstellungen_seite(request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    kontext = grundkontext(request, db, "einstellungen")
    return vorlagen.TemplateResponse("einstellungen.html", kontext)


@app.post("/einstellungen")
def einstellungen_speichern(request: Request, unternehmen: str = Form(...), branche: str = Form(""), strasse: str = Form(""), plz: str = Form(""), ort: str = Form(""), telefon: str = Form(""), name: str = Form(...), db: Session = Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    organisation = mitglied.organisation
    organisation.name = unternehmen.strip()
    organisation.branche = branche.strip()
    organisation.strasse = strasse.strip()
    organisation.plz = plz.strip()
    organisation.ort = ort.strip()
    organisation.telefon = telefon.strip()
    mitglied.name = name.strip()
    db.commit()
    hinweis_setzen(request, "Die Konto- und Unternehmensdaten wurden gespeichert.")
    return RedirectResponse("/einstellungen", status_code=303)


@app.get("/abrechnung", response_class=HTMLResponse)
def abrechnung(request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    abo = db.scalar(select(Abonnement).options(joinedload(Abonnement.tarif)).where(Abonnement.organisation_id == mitglied.organisation_id))
    rechnungen = db.scalars(select(Rechnung).where(Rechnung.organisation_id == mitglied.organisation_id).order_by(Rechnung.erstellt_am.desc())).all()
    tarife = db.scalars(select(Tarif).where(Tarif.aktiv.is_(True)).order_by(Tarif.monatspreis)).all()
    kontext = grundkontext(request, db, "abrechnung")
    angefragter_tarif = db.get(Tarif, abo.angefragter_tarif_id) if abo and abo.angefragter_tarif_id else None
    kontext.update({
        "abonnement": abo,
        "angefragter_tarif": angefragter_tarif,
        "rechnungen": rechnungen,
        "tarife": tarife,
        "kennzahlen": _organisation_kennzahlen(db, mitglied.organisation_id),
    })
    return vorlagen.TemplateResponse("abrechnung.html", kontext)


@app.post("/abrechnung/tarif-wechseln")
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


@app.get("/verwaltung", response_class=HTMLResponse)
def verwaltung(request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    if not mitglied.ist_superadmin:
        return RedirectResponse("/arbeitsbereich", status_code=303)
    organisationen = db.scalars(select(Organisation).options(joinedload(Organisation.abonnement).joinedload(Abonnement.tarif), joinedload(Organisation.mitglieder)).order_by(Organisation.erstellt_am.desc())).unique().all()
    tarife = db.scalars(select(Tarif).order_by(Tarif.monatspreis)).all()
    kontext = grundkontext(request, db, "verwaltung")
    kontext.update({
        "kennzahlen": _verwaltungs_kennzahlen(db),
        "organisationen": organisationen,
        "tarife": tarife,
        "tarife_nach_id": {tarif.id: tarif for tarif in tarife},
    })
    return vorlagen.TemplateResponse("verwaltung.html", kontext)


@app.post("/verwaltung/konto/{organisation_id}/ansehen")
def konto_ansehen(organisation_id: int, request: Request, db: Session = Depends(datenbank_sitzung)):
    admin = muss_verwalten_duerfen(request, db)
    inhaber = db.scalar(select(Mitglied).where(Mitglied.organisation_id == organisation_id, Mitglied.rolle == Kontorolle.INHABER).order_by(Mitglied.id))
    if not inhaber:
        hinweis_setzen(request, "Für dieses Unternehmen wurde kein Inhaberkonto gefunden.", "fehler")
        return RedirectResponse("/verwaltung", status_code=303)
    request.session["urspruengliche_admin_id"] = admin.id
    request.session["mitglied_id"] = inhaber.id
    hinweis_setzen(request, f"Sie sehen A+ SmartDocs jetzt aus Sicht von {inhaber.organisation.name}.")
    return RedirectResponse("/arbeitsbereich", status_code=303)


@app.post("/verwaltung/konto/{organisation_id}/aktivieren")
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
    admin_id = request.session.pop("urspruengliche_admin_id", None)
    if admin_id and db.get(Mitglied, int(admin_id)):
        request.session["mitglied_id"] = int(admin_id)
        hinweis_setzen(request, "Zurück in der A+ Verwaltung.")
        return RedirectResponse("/verwaltung", status_code=303)
    return RedirectResponse("/arbeitsbereich", status_code=303)


def _ersatz_schema(dateiname: str) -> dict[str, Any]:
    return {
        "dokumentart": "Geschäftsdokument",
        "zusammenfassung": f"Automatisch erkannte Struktur aus {dateiname}. Die vorgeschlagenen Felder können im Dialog angepasst werden.",
        "felder": [
            {"schluessel": "kundenname", "bezeichnung": "Kundenname", "typ": "text", "pflichtfeld": True, "beispiel": "", "seite": 1, "hinweis": "Name des Kunden oder Auftraggebers", "optionen": [], "position": {"x": 0.1, "y": 0.2, "breite": 0.36, "hoehe": 0.035}, "schriftgroesse": 10},
            {"schluessel": "datum", "bezeichnung": "Datum", "typ": "datum", "pflichtfeld": True, "beispiel": "", "seite": 1, "hinweis": "Dokument- oder Leistungsdatum", "optionen": [], "position": {"x": 0.58, "y": 0.2, "breite": 0.22, "hoehe": 0.035}, "schriftgroesse": 10},
            {"schluessel": "beschreibung", "bezeichnung": "Beschreibung", "typ": "mehrzeilig", "pflichtfeld": False, "beispiel": "", "seite": 1, "hinweis": "Freie Beschreibung oder Leistungsangaben", "optionen": [], "position": {"x": 0.1, "y": 0.36, "breite": 0.72, "hoehe": 0.08}, "schriftgroesse": 9},
            {"schluessel": "unterschrift", "bezeichnung": "Unterschrift", "typ": "unterschrift", "pflichtfeld": False, "beispiel": "", "seite": 1, "hinweis": "Unterschrift als Bilddatei", "optionen": [], "position": {"x": 0.55, "y": 0.78, "breite": 0.28, "hoehe": 0.07}, "schriftgroesse": 9},
        ],
        "rueckfragen": ["Sind weitere Bereiche des Dokuments veränderlich?"],
    }


@app.post("/api/vorlagen/analysieren")
def vorlage_analysieren(request: Request, datei: UploadFile = File(...), name: str = Form(default="Neue Dokumentvorlage"), db: Session = Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    kennzahlen = _organisation_kennzahlen(db, mitglied.organisation_id)
    if kennzahlen["vorlagen"] >= kennzahlen["abonnement"].vorlagen_limit:
        raise HTTPException(status_code=409, detail="Das Vorlagenlimit des aktuellen Tarifs ist erreicht.")
    erlaubte_typen = {"application/pdf", "image/png", "image/jpeg", "image/webp"}
    if datei.content_type not in erlaubte_typen:
        raise HTTPException(status_code=415, detail="Bitte laden Sie eine PDF-, PNG-, JPG- oder WEBP-Datei hoch.")
    endung = Path(datei.filename or "dokument.pdf").suffix.lower() or ".pdf"
    ziel = cfg.upload_pfad / f"{mitglied.organisation_id}-{uuid.uuid4().hex}{endung}"
    groesse = 0
    with ziel.open("wb") as ausgabe:
        while block := datei.file.read(1024 * 1024):
            groesse += len(block)
            if groesse > cfg.max_upload_mb * 1024 * 1024:
                ausgabe.close()
                ziel.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Die Datei darf höchstens {cfg.max_upload_mb} MB groß sein.")
            ausgabe.write(block)
    seiten = 1
    if datei.content_type == "application/pdf":
        try:
            seiten = max(1, len(PdfReader(str(ziel)).pages))
        except Exception:
            seiten = 1
    eintrag = Dokumentvorlage(organisation_id=mitglied.organisation_id, erstellt_von_id=mitglied.id, name=name.strip() or "Neue Dokumentvorlage", dateiname=datei.filename or ziel.name, speicherort=str(ziel), inhaltstyp=datei.content_type or "application/pdf", originalgroesse=groesse, status="wird analysiert", seiten=seiten, aktualisiert_am=datetime.now(timezone.utc))
    db.add(eintrag)
    db.commit()
    db.refresh(eintrag)
    analyse_hinweis = ""
    try:
        schema, nutzung = dokument_analysieren(ziel, eintrag.dateiname)
    except Exception:
        schema = _ersatz_schema(eintrag.dateiname)
        nutzung = {"eingabe": 0, "ausgabe": 0}
        analyse_hinweis = " Die Präsentationsanalyse wurde verwendet; alle Felder bleiben vollständig bearbeitbar."
    felder = schema.get("felder", []) if isinstance(schema, dict) else []
    eintrag.schema = schema
    eintrag.erkannte_felder = len(felder)
    eintrag.zusammenfassung = str(schema.get("zusammenfassung", ""))
    eintrag.status = "Bestätigung erforderlich"
    db.add(Vorlagendialog(vorlage_id=eintrag.id, rolle="assistent", nachricht=f"Ich habe {len(felder)} veränderliche Felder erkannt. Bitte prüfen Sie die Vorschläge und nennen Sie mir notwendige Korrekturen.{analyse_hinweis}"))
    db.add(Nutzungsereignis(organisation_id=mitglied.organisation_id, art="vorlage_analysiert", menge=1, kosten_euro=Decimal(str(round((nutzung["eingabe"] * 0.0000004) + (nutzung["ausgabe"] * 0.0000016), 4))), einzelheiten=nutzung))
    db.commit()
    return {"erfolg": True, "vorlage_id": eintrag.id, "schema": schema, "status": eintrag.status, "weiter": f"/vorlagen/{eintrag.id}"}


@app.post("/api/vorlagen/korrigieren")
def vorlage_korrigieren(eingabe: KorrekturEingabe, request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = vorlage_fuer_mitglied(db, mitglied, eingabe.vorlage_id)
    if not eintrag.schema:
        raise HTTPException(status_code=409, detail="Für diese Vorlage liegt noch kein Analyseschema vor.")
    db.add(Vorlagendialog(vorlage_id=eintrag.id, rolle="nutzer", nachricht=eingabe.nachricht))
    try:
        neues_schema, nutzung = schema_korrigieren(eintrag.schema, eingabe.nachricht)
        antwort = "Die Vorlage wurde entsprechend angepasst. Prüfen Sie bitte die aktualisierten Felder."
    except Exception:
        neues_schema = dict(eintrag.schema)
        antwort = "Die Anweisung wurde gespeichert. Bitte verwenden Sie bei Bedarf zusätzlich den visuellen Feldeditor."
        nutzung = {"eingabe": 0, "ausgabe": 0}
    eintrag.schema = neues_schema
    eintrag.erkannte_felder = len(neues_schema.get("felder", []))
    eintrag.zusammenfassung = str(neues_schema.get("zusammenfassung", eintrag.zusammenfassung))
    eintrag.aktualisiert_am = datetime.now(timezone.utc)
    db.add(Vorlagendialog(vorlage_id=eintrag.id, rolle="assistent", nachricht=antwort))
    db.add(Nutzungsereignis(organisation_id=mitglied.organisation_id, art="vorlage_korrigiert", menge=1, einzelheiten=nutzung))
    db.commit()
    return {"erfolg": True, "schema": neues_schema, "antwort": antwort}


@app.put("/api/vorlagen/{vorlage_id}/schema")
def schema_speichern(vorlage_id: int, eingabe: SchemaEingabe, request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    eintrag.schema = eingabe.daten
    eintrag.erkannte_felder = len(eingabe.daten.get("felder", []))
    eintrag.zusammenfassung = str(eingabe.daten.get("zusammenfassung", eintrag.zusammenfassung))
    eintrag.aktualisiert_am = datetime.now(timezone.utc)
    db.commit()
    return {"erfolg": True, "hinweis": "Die Feldkonfiguration wurde gespeichert.", "schema": eintrag.schema}


@app.post("/api/vorlagen/{vorlage_id}/bestaetigen")
def vorlage_bestaetigen(vorlage_id: int, request: Request, db: Session = Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    eintrag.status = "bereit"
    eintrag.aktualisiert_am = datetime.now(timezone.utc)
    db.add(Vorlagendialog(vorlage_id=eintrag.id, rolle="assistent", nachricht="Die Vorlage ist bestätigt und kann ab sofort wiederverwendet werden."))
    db.commit()
    return {"erfolg": True, "status": "bereit", "weiter": f"/vorlagen/{eintrag.id}/verwenden"}


@app.patch("/api/verwaltung/konten/{organisation_id}/grenzen")
def konto_grenzen_aendern(organisation_id: int, grenzen: KontoGrenzen, request: Request, db: Session = Depends(datenbank_sitzung)):
    muss_verwalten_duerfen(request, db)
    abonnement = db.scalar(select(Abonnement).where(Abonnement.organisation_id == organisation_id))
    if not abonnement:
        raise HTTPException(status_code=404, detail="Für dieses Konto wurde kein Abonnement gefunden.")
    abonnement.individueller_preis = grenzen.individueller_preis
    abonnement.dokumente_override = grenzen.dokumente
    abonnement.vorlagen_override = grenzen.vorlagen
    abonnement.unterkonten_override = grenzen.unterkonten
    abonnement.speicher_override_mb = grenzen.speicher_mb
    db.commit()
    return {"erfolg": True, "hinweis": "Die individuellen Konditionen wurden gespeichert."}


@app.patch("/api/verwaltung/tarife/{tarif_id}")
def tarif_aendern(tarif_id: int, eingabe: TarifEingabe, request: Request, db: Session = Depends(datenbank_sitzung)):
    muss_verwalten_duerfen(request, db)
    tarif = db.get(Tarif, tarif_id)
    if not tarif:
        raise HTTPException(status_code=404, detail="Der Tarif wurde nicht gefunden.")
    tarif.monatspreis = eingabe.monatspreis
    tarif.jahrespreis = eingabe.jahrespreis
    tarif.dokumente_monat = eingabe.dokumente
    tarif.vorlagen = eingabe.vorlagen
    tarif.unterkonten = eingabe.unterkonten
    tarif.speicher_mb = eingabe.speicher_mb
    db.commit()
    return {"erfolg": True, "hinweis": f"Der Tarif {tarif.name} wurde aktualisiert."}


@app.get("/api/status")
def status():
    return {"zustand": "bereit", "zeit": datetime.now(timezone.utc).isoformat(), "dienst": "A+ SmartDocs", "ausbaustufe": "Praesentationsfassung"}


@app.exception_handler(401)
def nicht_angemeldet(request: Request, exc: HTTPException):
    return weiterleitung_anmeldung(request)


@app.exception_handler(403)
def nicht_erlaubt(request: Request, exc: HTTPException):
    return vorlagen.TemplateResponse("fehler.html", {"request": request, "bereich": "", "mitglied": None, "organisation": None, "ist_verwaltung": False, "rueckkehr_admin": False, "hinweis": None, "titel": "Zugriff nicht möglich", "text": exc.detail}, status_code=403)
