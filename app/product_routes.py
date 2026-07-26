from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from .database import datenbank_sitzung
from .form_presentation import formularabschnitte, formularfelder
from .main import (
    _organisation_kennzahlen,
    aktuelles_mitglied,
    app,
    ausgabe_fuer_mitglied,
    cfg,
    grundkontext,
    hinweis_setzen,
    muss_angemeldet_sein,
    vorlage_fuer_mitglied,
    vorlagen,
    weiterleitung_anmeldung,
)
from .models import Dokumentausgabe, Kontorolle, Nutzungsereignis
from .pdf_engine import dokument_erzeugen


def _ersetzte_route(route: Any) -> bool:
    pfad = getattr(route, "path", None)
    methoden = getattr(route, "methods", set()) or set()
    return (
        (pfad == "/vorlagen/{vorlage_id}/datei" and "GET" in methoden)
        or (pfad == "/vorlagen/{vorlage_id}/verwenden" and bool({"GET", "POST"} & set(methoden)))
        or (pfad == "/dokumente/{ausgabe_id}/loeschen" and "POST" in methoden)
    )


app.router.routes[:] = [route for route in app.router.routes if not _ersetzte_route(route)]


def _darf_loeschen(mitglied) -> bool:
    return bool(
        mitglied.ist_superadmin
        or mitglied.rolle in {Kontorolle.INHABER, Kontorolle.VERWALTUNG}
    )


def _loeschrecht_pruefen(mitglied) -> None:
    if not _darf_loeschen(mitglied):
        raise HTTPException(
            status_code=403,
            detail="Nur Inhaber und Administratoren des Unternehmens dürfen Vorlagen oder Dokumente löschen.",
        )


def _formular_schema(eintrag) -> dict[str, Any]:
    schema = copy.deepcopy(eintrag.schema or {})
    schema["felder"] = formularfelder(schema, Path(eintrag.speicherort))
    return schema


@app.get("/vorlagen/{vorlage_id}/datei")
def vorlage_datei_inline(vorlage_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    pfad = Path(eintrag.speicherort)
    if not pfad.exists():
        raise HTTPException(status_code=404, detail="Die Originaldatei ist nicht mehr verfügbar.")
    return FileResponse(
        pfad,
        media_type=eintrag.inhaltstyp,
        filename=eintrag.dateiname,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=60"},
    )


@app.get("/vorlagen/{vorlage_id}/verwenden", response_class=HTMLResponse)
def vorlage_verwenden_kompakt(vorlage_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    if eintrag.status != "bereit":
        hinweis_setzen(request, "Bitte bestätigen Sie die erkannten Felder, bevor Sie die Vorlage verwenden.", "fehler")
        return RedirectResponse(f"/vorlagen/{vorlage_id}", status_code=303)

    felder = formularfelder(eintrag.schema, Path(eintrag.speicherort))
    kontext = grundkontext(request, db, "vorlagen")
    kontext.update(
        {
            "eintrag": eintrag,
            "formular_felder": felder,
            "formular_abschnitte": formularabschnitte(felder),
            "darf_loeschen": _darf_loeschen(mitglied),
        }
    )
    return vorlagen.TemplateResponse("vorlage_verwenden.html", kontext)


@app.post("/vorlagen/{vorlage_id}/verwenden")
async def dokument_aus_bereinigter_vorlage(
    vorlage_id: int,
    request: Request,
    db=Depends(datenbank_sitzung),
):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    if eintrag.status != "bereit":
        hinweis_setzen(request, "Die Vorlage muss vor der Verwendung bestätigt werden.", "fehler")
        return RedirectResponse(f"/vorlagen/{vorlage_id}", status_code=303)

    kennzahlen = _organisation_kennzahlen(db, mitglied.organisation_id)
    if kennzahlen["dokumente"] >= kennzahlen["dokument_limit"]:
        hinweis_setzen(
            request,
            "Das monatliche Dokumentenlimit ist erreicht. Bitte wechseln Sie den Tarif oder kontaktieren Sie die A+ Verwaltung.",
            "fehler",
        )
        return RedirectResponse("/abrechnung", status_code=303)

    formular = await request.form()
    titel = str(formular.get("dokumenttitel") or f"{eintrag.name} {datetime.now().strftime('%d.%m.%Y')}").strip()
    schema = _formular_schema(eintrag)
    eingaben: dict[str, Any] = {}
    temp_dateien: list[Path] = []

    for feld in schema.get("felder", []):
        schluessel = str(feld.get("schluessel") or "")
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

    ziel = cfg.ausgabe_pfad / f"{uuid.uuid4().hex}.pdf"
    try:
        seiten = dokument_erzeugen(
            Path(eintrag.speicherort),
            eintrag.inhaltstyp,
            schema,
            eingaben,
            ziel,
            titel,
            eintrag.name,
        )
    except Exception as exc:
        ziel.unlink(missing_ok=True)
        hinweis_setzen(request, f"Das PDF konnte nicht erstellt werden: {exc}", "fehler")
        return RedirectResponse(f"/vorlagen/{vorlage_id}/verwenden", status_code=303)
    finally:
        for temp_pfad in temp_dateien:
            temp_pfad.unlink(missing_ok=True)

    temp_werte = {str(pfad) for pfad in temp_dateien}
    ausgabe = Dokumentausgabe(
        organisation_id=mitglied.organisation_id,
        vorlage_id=eintrag.id,
        erstellt_von_id=mitglied.id,
        titel=titel,
        dateiname=f"{re.sub(r'[^A-Za-z0-9ÄÖÜäöüß_-]+', '-', titel).strip('-') or 'Dokument'}.pdf",
        speicherort=str(ziel),
        eingaben={
            schluessel: ("[Datei]" if isinstance(wert, str) and wert in temp_werte else wert)
            for schluessel, wert in eingaben.items()
        },
        status="fertig",
        seiten=seiten,
        dateigroesse=ziel.stat().st_size,
    )
    db.add(ausgabe)
    db.add(
        Nutzungsereignis(
            organisation_id=mitglied.organisation_id,
            art="dokument_erstellt",
            menge=1,
            kosten_euro=Decimal("0.002"),
            einzelheiten={"vorlage_id": eintrag.id},
        )
    )
    db.commit()
    hinweis_setzen(request, "Das Dokument wurde erfolgreich erstellt und im Firmenarchiv gespeichert.")
    return RedirectResponse("/dokumente", status_code=303)


@app.post("/dokumente/{ausgabe_id}/loeschen")
def dokument_durch_admin_loeschen(ausgabe_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    _loeschrecht_pruefen(mitglied)
    eintrag = ausgabe_fuer_mitglied(db, mitglied, ausgabe_id)
    pfad = Path(eintrag.speicherort)
    db.delete(eintrag)
    db.commit()
    pfad.unlink(missing_ok=True)
    hinweis_setzen(request, "Das Dokument wurde dauerhaft gelöscht.")
    return RedirectResponse("/dokumente", status_code=303)


@app.post("/vorlagen/{vorlage_id}/loeschen")
def vorlage_durch_admin_loeschen(vorlage_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    _loeschrecht_pruefen(mitglied)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)

    dateipfade = {Path(eintrag.speicherort)}
    dateipfade.update(Path(dokument.speicherort) for dokument in list(eintrag.dokumente))
    vorschauen = list(cfg.ausgabe_pfad.glob(f"testausfuellung-{eintrag.organisation_id}-{eintrag.id}-*.pdf"))
    vorschauen.append(cfg.ausgabe_pfad / f"test-signatur-{eintrag.id}.png")

    db.delete(eintrag)
    db.commit()

    for pfad in [*dateipfade, *vorschauen]:
        pfad.unlink(missing_ok=True)

    hinweis_setzen(request, "Die Vorlage und ihre zugehörigen PDF-Ausgaben wurden dauerhaft gelöscht.")
    return RedirectResponse("/vorlagen", status_code=303)


__all__ = []
