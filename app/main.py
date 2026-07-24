from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from .ai import dokument_analysieren, schema_korrigieren
from .config import einstellungen
from .database import Basis, Sitzung, datenbank_sitzung, engine
from .models import (
    Abonnement,
    Dokumentvorlage,
    Kontorolle,
    Mitglied,
    Nutzungsereignis,
    Organisation,
    Tarif,
    Vorlagendialog,
)

app = FastAPI(title="A+ SmartDocs", docs_url=None, redoc_url=None)
app.mount("/statisch", StaticFiles(directory="app/static"), name="statisch")
vorlagen = Jinja2Templates(directory="app/templates")


class KorrekturEingabe(BaseModel):
    vorlage_id: int
    nachricht: str = Field(min_length=2, max_length=3000)


class KontoGrenzen(BaseModel):
    individueller_preis: Decimal | None = None
    dokumente: int | None = Field(default=None, ge=0)
    vorlagen: int | None = Field(default=None, ge=0)
    unterkonten: int | None = Field(default=None, ge=0)
    speicher_mb: int | None = Field(default=None, ge=0)


def geld(wert: Decimal | float | int) -> str:
    return f"{float(wert):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


vorlagen.env.filters["geld"] = geld


@app.on_event("startup")
def startvorbereitung() -> None:
    Basis.metadata.create_all(bind=engine)
    with Sitzung() as db:
        if db.scalar(select(func.count(Tarif.id))) == 0:
            _beispieldaten(db)


def _beispieldaten(db: Session) -> None:
    starter = Tarif(name="Start", monatspreis=Decimal("29.00"), dokumente_monat=50, vorlagen=3, unterkonten=1, speicher_mb=2048)
    business = Tarif(name="Unternehmen", monatspreis=Decimal("69.00"), dokumente_monat=250, vorlagen=15, unterkonten=5, speicher_mb=10240)
    pro = Tarif(name="Professionell", monatspreis=Decimal("149.00"), dokumente_monat=1000, vorlagen=60, unterkonten=20, speicher_mb=51200)
    db.add_all([starter, business, pro])
    db.flush()

    daten = [
        ("Müller Gebäudeservice GmbH", "Gebäudeservice", business, Decimal("69.00"), 184),
        ("RheinMain Entrümpelung", "Entrümpelung", pro, Decimal("129.00"), 611),
        ("Praxis am Main", "Gesundheit", business, Decimal("79.00"), 228),
        ("Klarwerk Montage", "Handwerk", starter, Decimal("29.00"), 31),
    ]
    for nummer, (name, branche, tarif, preis, verwendung) in enumerate(daten, start=1):
        organisation = Organisation(name=name, branche=branche)
        db.add(organisation)
        db.flush()
        db.add(
            Abonnement(
                organisation_id=organisation.id,
                tarif_id=tarif.id,
                status="aktiv",
                individueller_preis=preis if preis != tarif.monatspreis else None,
                dokumente_override=800 if nummer == 2 else None,
                unterkonten_override=12 if nummer == 2 else None,
                verlaengert_am=datetime.now(timezone.utc) + timedelta(days=nummer * 4),
            )
        )
        db.add(
            Mitglied(
                organisation_id=organisation.id,
                name=f"Beispiel Nutzer {nummer}",
                email=f"nutzer{nummer}@beispiel.de",
                rolle=Kontorolle.INHABER,
                letzter_zugriff=datetime.now(timezone.utc) - timedelta(hours=nummer * 3),
            )
        )
        db.add(
            Nutzungsereignis(
                organisation_id=organisation.id,
                art="dokument_erstellt",
                menge=verwendung,
                kosten_euro=Decimal(str(round(verwendung * 0.0032, 4))),
            )
        )

    db.add_all(
        [
            Dokumentvorlage(name="Abnahmeprotokoll", dateiname="abnahmeprotokoll.pdf", speicherort="/beispiel/abnahme.pdf", status="bereit", seiten=3, erkannte_felder=18, zusammenfassung="Projektabnahme mit Leistungsübersicht, Unterschriften und Fotobereich."),
            Dokumentvorlage(name="Fotodokumentation", dateiname="fotodokumentation.pdf", speicherort="/beispiel/foto.pdf", status="bereit", seiten=6, erkannte_felder=11, zusammenfassung="Wiederholbarer Bildbericht mit Objekt- und Datumsfeldern."),
            Dokumentvorlage(name="Leistungsnachweis", dateiname="leistungsnachweis.pdf", speicherort="/beispiel/leistung.pdf", status="bereit", seiten=2, erkannte_felder=14, zusammenfassung="Tätigkeitsnachweis mit Arbeitszeiten und Kundenbestätigung."),
        ]
    )
    db.commit()


def _grunddaten(db: Session) -> dict:
    abonnement_anzahl = db.scalar(select(func.count(Abonnement.id)).where(Abonnement.status == "aktiv")) or 0
    abonnements = db.scalars(select(Abonnement).options(joinedload(Abonnement.tarif))).all()
    monatsumsatz = sum((a.preis for a in abonnements if a.status == "aktiv"), Decimal("0"))
    dokumente = db.scalar(select(func.coalesce(func.sum(Nutzungsereignis.menge), 0)).where(Nutzungsereignis.art == "dokument_erstellt")) or 0
    ki_kosten = db.scalar(select(func.coalesce(func.sum(Nutzungsereignis.kosten_euro), 0))) or Decimal("0")
    return {
        "aktive_abonnements": abonnement_anzahl,
        "monatsumsatz": monatsumsatz,
        "dokumente": dokumente,
        "ki_kosten": ki_kosten,
    }


@app.get("/", response_class=HTMLResponse)
def startseite(request: Request, db: Session = Depends(datenbank_sitzung)):
    return vorlagen.TemplateResponse("start.html", {"request": request, "kennzahlen": _grunddaten(db), "bereich": "start"})


@app.get("/arbeitsbereich", response_class=HTMLResponse)
def arbeitsbereich(request: Request, db: Session = Depends(datenbank_sitzung)):
    dokumentvorlagen = db.scalars(select(Dokumentvorlage).order_by(Dokumentvorlage.erstellt_am.desc()).limit(8)).all()
    return vorlagen.TemplateResponse(
        "arbeitsbereich.html",
        {
            "request": request,
            "kennzahlen": _grunddaten(db),
            "vorlagen_liste": dokumentvorlagen,
            "bereich": "arbeitsbereich",
        },
    )


@app.get("/vorlagen/neu", response_class=HTMLResponse)
def neue_vorlage(request: Request):
    return vorlagen.TemplateResponse("vorlage_neu.html", {"request": request, "bereich": "vorlagen"})


@app.get("/verwaltung", response_class=HTMLResponse)
def verwaltung(request: Request, db: Session = Depends(datenbank_sitzung)):
    organisationen = db.scalars(
        select(Organisation)
        .options(joinedload(Organisation.abonnement).joinedload(Abonnement.tarif), joinedload(Organisation.mitglieder))
        .order_by(Organisation.erstellt_am.desc())
    ).unique().all()
    tarife = db.scalars(select(Tarif).order_by(Tarif.monatspreis)).all()
    return vorlagen.TemplateResponse(
        "verwaltung.html",
        {
            "request": request,
            "kennzahlen": _grunddaten(db),
            "organisationen": organisationen,
            "tarife": tarife,
            "bereich": "verwaltung",
        },
    )


@app.post("/api/vorlagen/analysieren")
def vorlage_analysieren(
    datei: UploadFile = File(...),
    name: str = Form(default="Neue Dokumentvorlage"),
    db: Session = Depends(datenbank_sitzung),
):
    cfg = einstellungen()
    erlaubte_typen = {"application/pdf", "image/png", "image/jpeg", "image/webp"}
    if datei.content_type not in erlaubte_typen:
        raise HTTPException(status_code=415, detail="Bitte lade eine PDF-, PNG-, JPG- oder WEBP-Datei hoch.")

    endung = Path(datei.filename or "dokument.pdf").suffix.lower() or ".pdf"
    ziel = cfg.upload_pfad / f"{uuid.uuid4().hex}{endung}"
    groesse = 0
    with ziel.open("wb") as ausgabe:
        while block := datei.file.read(1024 * 1024):
            groesse += len(block)
            if groesse > cfg.max_upload_mb * 1024 * 1024:
                ausgabe.close()
                ziel.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Die Datei darf höchstens {cfg.max_upload_mb} MB groß sein.")
            ausgabe.write(block)

    eintrag = Dokumentvorlage(
        name=name.strip() or "Neue Dokumentvorlage",
        dateiname=datei.filename or ziel.name,
        speicherort=str(ziel),
        status="wird analysiert",
    )
    db.add(eintrag)
    db.commit()
    db.refresh(eintrag)

    try:
        schema, nutzung = dokument_analysieren(ziel, eintrag.dateiname)
        felder = schema.get("felder", []) if isinstance(schema, dict) else []
        eintrag.schema = schema
        eintrag.erkannte_felder = len(felder)
        eintrag.zusammenfassung = str(schema.get("zusammenfassung", ""))
        eintrag.status = "Bestätigung erforderlich"
        db.add(
            Vorlagendialog(
                vorlage_id=eintrag.id,
                rolle="assistent",
                nachricht=f"Ich habe {len(felder)} veränderliche Felder erkannt. Bitte prüfe die Vorschläge und nenne mir notwendige Korrekturen.",
            )
        )
        db.add(
            Nutzungsereignis(
                art="vorlage_analysiert",
                menge=1,
                kosten_euro=Decimal(str(round((nutzung["eingabe"] * 0.0000004) + (nutzung["ausgabe"] * 0.0000016), 4))),
                einzelheiten=nutzung,
            )
        )
        db.commit()
        return {"erfolg": True, "vorlage_id": eintrag.id, "schema": schema, "status": eintrag.status}
    except Exception as exc:
        eintrag.status = "Analyse fehlgeschlagen"
        db.commit()
        raise HTTPException(status_code=502, detail=f"Die Analyse konnte nicht abgeschlossen werden: {exc}") from exc


@app.post("/api/vorlagen/korrigieren")
def vorlage_korrigieren(eingabe: KorrekturEingabe, db: Session = Depends(datenbank_sitzung)):
    eintrag = db.get(Dokumentvorlage, eingabe.vorlage_id)
    if not eintrag:
        raise HTTPException(status_code=404, detail="Die Dokumentvorlage wurde nicht gefunden.")
    if not eintrag.schema:
        raise HTTPException(status_code=409, detail="Für diese Vorlage liegt noch kein Analyseschema vor.")

    db.add(Vorlagendialog(vorlage_id=eintrag.id, rolle="nutzer", nachricht=eingabe.nachricht))
    try:
        neues_schema, nutzung = schema_korrigieren(eintrag.schema, eingabe.nachricht)
        eintrag.schema = neues_schema
        eintrag.erkannte_felder = len(neues_schema.get("felder", []))
        eintrag.zusammenfassung = str(neues_schema.get("zusammenfassung", eintrag.zusammenfassung))
        antwort = "Die Vorlage wurde entsprechend angepasst. Prüfe bitte die aktualisierten Felder."
        db.add(Vorlagendialog(vorlage_id=eintrag.id, rolle="assistent", nachricht=antwort))
        db.add(Nutzungsereignis(art="vorlage_korrigiert", menge=1, einzelheiten=nutzung))
        db.commit()
        return {"erfolg": True, "schema": neues_schema, "antwort": antwort}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Die Korrektur konnte nicht verarbeitet werden: {exc}") from exc


@app.post("/api/vorlagen/{vorlage_id}/bestaetigen")
def vorlage_bestaetigen(vorlage_id: int, db: Session = Depends(datenbank_sitzung)):
    eintrag = db.get(Dokumentvorlage, vorlage_id)
    if not eintrag:
        raise HTTPException(status_code=404, detail="Die Dokumentvorlage wurde nicht gefunden.")
    eintrag.status = "bereit"
    db.add(Vorlagendialog(vorlage_id=eintrag.id, rolle="assistent", nachricht="Die Vorlage ist bestätigt und kann ab sofort wiederverwendet werden."))
    db.commit()
    return {"erfolg": True, "status": "bereit"}


@app.patch("/api/verwaltung/konten/{organisation_id}/grenzen")
def konto_grenzen_aendern(organisation_id: int, grenzen: KontoGrenzen, db: Session = Depends(datenbank_sitzung)):
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


@app.get("/api/status")
def status():
    return {"zustand": "bereit", "zeit": datetime.now(timezone.utc).isoformat(), "dienst": "A+ SmartDocs"}
