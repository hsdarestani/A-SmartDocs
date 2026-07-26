from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from .database import datenbank_sitzung
from .main import app, cfg, muss_angemeldet_sein, vorlage_fuer_mitglied
from .models import Kontorolle, Vorlagendialog
from .pdf_engine import dokument_erzeugen
from .quality import schema_fingerabdruck, schema_mit_qualitaet, testwert_fuer_feld


class SchemaQualitaetsEingabe(BaseModel):
    daten: dict[str, Any] = Field(alias="schema")


class PruefungEingabe(BaseModel):
    schluessel: list[str] = Field(default_factory=list)
    alle_pruefpflichtigen: bool = False
    testausfuellung_geprueft: bool = False


def _alte_route(route: Any) -> bool:
    pfad = getattr(route, "path", None)
    methoden = getattr(route, "methods", set()) or set()
    return (
        (pfad == "/api/vorlagen/{vorlage_id}/schema" and "PUT" in methoden)
        or (pfad == "/api/vorlagen/{vorlage_id}/bestaetigen" and "POST" in methoden)
    )


app.router.routes[:] = [route for route in app.router.routes if not _alte_route(route)]


def _bearbeitung_erlaubt(mitglied) -> None:
    if mitglied.ist_superadmin:
        return
    if mitglied.rolle not in {Kontorolle.INHABER, Kontorolle.VERWALTUNG, Kontorolle.BEARBEITUNG}:
        raise HTTPException(status_code=403, detail="Ihre Rolle darf Dokumentvorlagen nicht verändern.")


def _signatur_pfad(vorlage_id: int) -> Path:
    ziel = cfg.ausgabe_pfad / f"test-signatur-{vorlage_id}.png"
    if ziel.exists():
        return ziel
    bild = Image.new("RGBA", (900, 260), (255, 255, 255, 0))
    zeichner = ImageDraw.Draw(bild)
    punkte = [(45, 190), (110, 120), (170, 180), (235, 70), (300, 175), (390, 105), (470, 165), (590, 80), (720, 155), (850, 115)]
    zeichner.line(punkte, fill=(15, 47, 77, 255), width=9, joint="curve")
    zeichner.line([(80, 220), (830, 220)], fill=(22, 118, 167, 140), width=3)
    bild.save(ziel, format="PNG", optimize=True)
    return ziel


def _preview_pfad(eintrag, schema: dict[str, Any]) -> Path:
    fingerabdruck = schema_fingerabdruck(schema)
    return cfg.ausgabe_pfad / f"testausfuellung-{eintrag.organisation_id}-{eintrag.id}-{fingerabdruck[:16]}.pdf"


def _direktfreigabe_moeglich(schema: dict[str, Any]) -> bool:
    """Nur ein einzelner, im PDF wirklich vorhandener Text darf ohne Vergleich durchlaufen.

    Dieser Sonderfall hält einfache Ein-Feld-Dokumente schnell. Mehrfeldformulare,
    Auswahlen, Tabellen, Bilder und Unterschriften benötigen immer eine Testausfüllung.
    """
    felder = list(schema.get("felder") or [])
    if len(felder) != 1:
        return False
    feld = felder[0]
    if str(feld.get("typ") or "text") not in {"text", "datum", "zahl", "betrag"}:
        return False
    if str(feld.get("erkennungsquelle") or "") not in {"pdf-textkandidat", "pdf-formularfeld", "manuell-korrigiert"}:
        return False
    if not str(feld.get("beispiel") or "").strip():
        return False
    position = feld.get("position") or {}
    try:
        return all(float(position.get(name, 0)) > 0 for name in ("breite", "hoehe"))
    except (TypeError, ValueError):
        return False


@app.put("/api/vorlagen/{vorlage_id}/schema")
def schema_mit_pruefstatus_speichern(
    vorlage_id: int,
    eingabe: SchemaQualitaetsEingabe,
    request: Request,
    db=Depends(datenbank_sitzung),
):
    mitglied = muss_angemeldet_sein(request, db)
    _bearbeitung_erlaubt(mitglied)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)

    bisheriges_schema = schema_mit_qualitaet(eintrag.schema)
    bisheriger_hash = schema_fingerabdruck(bisheriges_schema)
    neues_schema = schema_mit_qualitaet(eingabe.daten)
    neuer_hash = schema_fingerabdruck(neues_schema)

    if bisheriger_hash != neuer_hash:
        neues_schema["testausfuellung_geprueft"] = False
        neues_schema["testausfuellung_hash"] = None
    else:
        neues_schema["testausfuellung_geprueft"] = bool(bisheriges_schema.get("testausfuellung_geprueft"))
        neues_schema["testausfuellung_hash"] = bisheriges_schema.get("testausfuellung_hash")
    neues_schema = schema_mit_qualitaet(neues_schema)

    eintrag.schema = neues_schema
    eintrag.erkannte_felder = len(neues_schema.get("felder", []))
    eintrag.zusammenfassung = str(neues_schema.get("zusammenfassung", eintrag.zusammenfassung))
    eintrag.aktualisiert_am = datetime.now(timezone.utc)
    if eintrag.status == "bereit" and bisheriger_hash != neuer_hash:
        eintrag.status = "Bestätigung erforderlich"
    db.commit()
    return {
        "erfolg": True,
        "hinweis": "Die Feldkonfiguration wurde gespeichert. Bei Positionsänderungen ist eine neue Testausfüllung erforderlich.",
        "schema": eintrag.schema,
        "qualitaet": eintrag.schema.get("qualitaet", {}),
    }


@app.post("/api/vorlagen/{vorlage_id}/testausfuellung")
def testausfuellung_erzeugen(vorlage_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    _bearbeitung_erlaubt(mitglied)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    schema = schema_mit_qualitaet(eintrag.schema)
    if not schema.get("felder"):
        raise HTTPException(status_code=409, detail="Für diese Vorlage wurden noch keine Felder erkannt.")

    signatur = _signatur_pfad(eintrag.id)
    eingaben = {
        str(feld.get("schluessel")): testwert_fuer_feld(feld, signatur)
        for feld in schema.get("felder", [])
        if feld.get("schluessel")
    }
    ziel = _preview_pfad(eintrag, schema)
    try:
        dokument_erzeugen(
            Path(eintrag.speicherort),
            eintrag.inhaltstyp,
            schema,
            eingaben,
            ziel,
            "TESTAUSFÜLLUNG – NICHT VERWENDEN",
            eintrag.name,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Die Testausfüllung konnte nicht erzeugt werden: {exc}") from exc

    schema["testausfuellung_hash"] = schema_fingerabdruck(schema)
    schema["testausfuellung_geprueft"] = False
    schema = schema_mit_qualitaet(schema)
    eintrag.schema = schema
    eintrag.aktualisiert_am = datetime.now(timezone.utc)
    db.commit()
    return {
        "erfolg": True,
        "original_url": f"/vorlagen/{eintrag.id}/datei",
        "test_url": f"/vorlagen/{eintrag.id}/testausfuellung.pdf?v={schema['testausfuellung_hash'][:12]}",
        "qualitaet": schema.get("qualitaet", {}),
        "hinweis": "Die Testausfüllung ist fertig. Vergleichen Sie Positionen, Feldtypen und Überlagerungen mit dem Original.",
    }


@app.get("/vorlagen/{vorlage_id}/testausfuellung.pdf")
def testausfuellung_datei(vorlage_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    schema = schema_mit_qualitaet(eintrag.schema)
    ziel = _preview_pfad(eintrag, schema)
    if not ziel.exists() or schema.get("testausfuellung_hash") != schema_fingerabdruck(schema):
        raise HTTPException(status_code=404, detail="Bitte erzeugen Sie zuerst eine aktuelle Testausfüllung.")
    return FileResponse(ziel, media_type="application/pdf", filename=f"Testausfuellung-{eintrag.name}.pdf")


@app.post("/api/vorlagen/{vorlage_id}/pruefung-bestaetigen")
def pruefung_bestaetigen(
    vorlage_id: int,
    eingabe: PruefungEingabe,
    request: Request,
    db=Depends(datenbank_sitzung),
):
    mitglied = muss_angemeldet_sein(request, db)
    _bearbeitung_erlaubt(mitglied)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    schema = schema_mit_qualitaet(eintrag.schema)
    aktueller_hash = schema_fingerabdruck(schema)
    ziel = _preview_pfad(eintrag, schema)
    if schema.get("testausfuellung_hash") != aktueller_hash or not ziel.exists():
        raise HTTPException(status_code=409, detail="Die Testausfüllung ist nicht mehr aktuell. Bitte erzeugen Sie sie erneut.")
    if not eingabe.testausfuellung_geprueft:
        raise HTTPException(status_code=409, detail="Bitte bestätigen Sie, dass Sie Original und Testausfüllung verglichen haben.")

    auswahl = set(eingabe.schluessel)
    for feld in schema.get("felder", []):
        if eingabe.alle_pruefpflichtigen and feld.get("pruefung_erforderlich"):
            feld["geprueft"] = True
        elif feld.get("schluessel") in auswahl:
            feld["geprueft"] = True
    schema["testausfuellung_geprueft"] = True
    schema = schema_mit_qualitaet(schema)
    eintrag.schema = schema
    eintrag.aktualisiert_am = datetime.now(timezone.utc)
    db.commit()
    return {
        "erfolg": True,
        "schema": schema,
        "qualitaet": schema.get("qualitaet", {}),
        "hinweis": "Die Testausfüllung und alle prüfpflichtigen Felder wurden bestätigt.",
    }


@app.post("/api/vorlagen/{vorlage_id}/bestaetigen")
def vorlage_mit_qualitaetskontrolle_bestaetigen(
    vorlage_id: int,
    request: Request,
    db=Depends(datenbank_sitzung),
):
    mitglied = muss_angemeldet_sein(request, db)
    _bearbeitung_erlaubt(mitglied)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    schema = schema_mit_qualitaet(eintrag.schema)

    direkt = _direktfreigabe_moeglich(schema)
    if direkt:
        for feld in schema.get("felder", []):
            feld["geprueft"] = True
        schema["testausfuellung_hash"] = schema_fingerabdruck(schema)
        schema["testausfuellung_geprueft"] = True
        schema = schema_mit_qualitaet(schema)

    qualitaet = schema.get("qualitaet", {})
    if int(qualitaet.get("offene_felder", 0)) > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Noch {qualitaet['offene_felder']} gelbe oder rote Felder sind ungeprüft. Öffnen Sie die Testausfüllung und schließen Sie die Prüfung ab.",
        )
    if not schema.get("testausfuellung_geprueft") or schema.get("testausfuellung_hash") != schema_fingerabdruck(schema):
        raise HTTPException(status_code=409, detail="Bitte erzeugen und bestätigen Sie zuerst eine aktuelle Testausfüllung.")

    eintrag.schema = schema
    eintrag.status = "bereit"
    eintrag.aktualisiert_am = datetime.now(timezone.utc)
    db.add(
        Vorlagendialog(
            vorlage_id=eintrag.id,
            rolle="assistent",
            nachricht=(
                "Das einzelne, exakt im PDF lokalisierbare Textfeld wurde direkt freigegeben."
                if direkt
                else "Qualitätsprüfung abgeschlossen: Die Testausfüllung wurde bestätigt und die Vorlage ist einsatzbereit."
            ),
        )
    )
    db.commit()
    return {"erfolg": True, "status": "bereit", "weiter": f"/vorlagen/{eintrag.id}/verwenden"}


__all__ = []
