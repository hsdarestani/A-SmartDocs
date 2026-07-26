from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from pypdf import PdfReader

from .ai import dokument_analysieren
from .database import Sitzung, datenbank_sitzung
from .form_analysis import formular_lokal_analysieren, schema_kombinieren
from .main import (
    _organisation_kennzahlen,
    app,
    cfg,
    muss_angemeldet_sein,
    vorlage_fuer_mitglied,
)
from .models import Dokumentvorlage, Nutzungsereignis, Vorlagendialog

logger = logging.getLogger("smartdocs.analyse")


def _alte_analyseroute(route: Any) -> bool:
    return (
        getattr(route, "path", None) == "/api/vorlagen/analysieren"
        and "POST" in (getattr(route, "methods", set()) or set())
    )


# Die bisherige Route hält die HTTP-Verbindung während des vollständigen KI-Laufs offen.
# Sie wird durch eine kurze Upload-Route mit nachgelagerter Analyse ersetzt.
app.router.routes[:] = [route for route in app.router.routes if not _alte_analyseroute(route)]


def _utc(wert: datetime | None) -> datetime:
    if wert is None:
        return datetime.now(timezone.utc)
    if wert.tzinfo is None:
        return wert.replace(tzinfo=timezone.utc)
    return wert.astimezone(timezone.utc)


def _lokale_analyse(dateipfad: Path, dateiname: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return formular_lokal_analysieren(dateipfad, dateiname)
    except Exception as exc:
        logger.warning("Lokale Formularerkennung für %s fehlgeschlagen: %s", dateiname, exc)
        return {
            "dokumentart": Path(dateiname).stem or "Dokumentvorlage",
            "zusammenfassung": "Die Dokumentstruktur konnte lokal nicht sicher ausgewertet werden.",
            "felder": [],
            "rueckfragen": [],
            "analysequelle": "lokale-analyse-fehlgeschlagen",
        }, {"felder": 0, "quelle": "lokale-analyse-fehlgeschlagen"}


def _analyse_abschliessen(vorlage_id: int) -> None:
    """Verarbeitet eine gespeicherte Vorlage außerhalb der Upload-Anfrage."""
    with Sitzung() as db:
        eintrag = db.get(Dokumentvorlage, vorlage_id)
        if not eintrag:
            return

        eintrag.status = "wird analysiert"
        eintrag.aktualisiert_am = datetime.now(timezone.utc)
        db.commit()

        dateipfad = Path(eintrag.speicherort)
        lokales_schema, lokale_diagnostik = _lokale_analyse(dateipfad, eintrag.dateiname)
        lokale_felder = list(lokales_schema.get("felder", []) or [])
        nutzung: dict[str, Any] = {"eingabe": 0, "ausgabe": 0, "lokale_analyse": lokale_diagnostik}
        analyse_hinweis = ""

        try:
            ki_schema, ki_nutzung = dokument_analysieren(dateipfad, eintrag.dateiname)
            schema = schema_kombinieren(ki_schema, lokales_schema)
            nutzung.update(ki_nutzung)
            nutzung["analysequelle"] = schema.get("analysequelle", "ki")
            if len(lokale_felder) >= 6 and len(list(ki_schema.get("felder", []) or [])) < len(lokale_felder) * 0.5:
                analyse_hinweis = (
                    " Der allgemeine KI-Vorschlag war für dieses Formular unvollständig; "
                    "deshalb wurden die konkret aus dem PDF erkannten Eingabebereiche verwendet."
                )
        except Exception as exc:
            logger.warning("KI-Analyse für Vorlage %s fehlgeschlagen: %s", vorlage_id, exc)
            if lokale_felder:
                schema = lokales_schema
                nutzung["analysequelle"] = "pdf-struktur-ohne-ki"
                analyse_hinweis = (
                    " Die KI-Verbindung war nicht verfügbar. Die angezeigten Felder stammen direkt "
                    "aus Text, Linien und Formularstruktur des Original-PDFs."
                )
            else:
                schema = lokales_schema
                nutzung["analysequelle"] = "keine-verlaessliche-erkennung"
                analyse_hinweis = (
                    " Es konnten keine verlässlichen Eingabebereiche erkannt werden. "
                    "Die Datei wurde gespeichert, aber nicht als fertige Analyse freigegeben."
                )

        try:
            felder = list(schema.get("felder", []) or []) if isinstance(schema, dict) else []
            eintrag.schema = schema
            eintrag.erkannte_felder = len(felder)
            eintrag.zusammenfassung = str(schema.get("zusammenfassung", ""))
            eintrag.aktualisiert_am = datetime.now(timezone.utc)

            if felder:
                eintrag.status = "Bestätigung erforderlich"
                nachricht = (
                    f"Ich habe {len(felder)} konkrete Eingabebereiche erkannt. "
                    f"Bitte prüfen Sie die Positionen und Feldtypen.{analyse_hinweis}"
                )
            else:
                eintrag.status = "Analyse fehlgeschlagen"
                nachricht = (
                    "Aus diesem Dokument konnte noch kein belastbares Feldschema erstellt werden. "
                    "Bitte starten Sie den Prüflauf erneut oder verwenden Sie ein textbasiertes PDF."
                    f"{analyse_hinweis}"
                )

            db.add(Vorlagendialog(vorlage_id=eintrag.id, rolle="assistent", nachricht=nachricht))
            kosten = round(
                (int(nutzung.get("eingabe", 0)) * 0.0000004)
                + (int(nutzung.get("ausgabe", 0)) * 0.0000016),
                4,
            )
            db.add(
                Nutzungsereignis(
                    organisation_id=eintrag.organisation_id,
                    art="vorlage_analysiert" if felder else "vorlage_analyse_fehlgeschlagen",
                    menge=1,
                    kosten_euro=Decimal(str(kosten)),
                    einzelheiten=nutzung,
                )
            )
            db.commit()
        except Exception as exc:
            logger.exception("Analyseergebnis für Vorlage %s konnte nicht gespeichert werden", vorlage_id)
            db.rollback()
            eintrag = db.get(Dokumentvorlage, vorlage_id)
            if eintrag:
                eintrag.status = "Analyse unterbrochen"
                eintrag.aktualisiert_am = datetime.now(timezone.utc)
                db.add(
                    Vorlagendialog(
                        vorlage_id=eintrag.id,
                        rolle="assistent",
                        nachricht="Der Prüflauf wurde unterbrochen. Starten Sie die Analyse bitte erneut; die hochgeladene Datei ist weiterhin gespeichert.",
                    )
                )
                db.commit()
            logger.warning("Speicherfehler: %s", exc)


@app.post("/api/vorlagen/analysieren")
async def vorlage_analysieren_robust(
    request: Request,
    background_tasks: BackgroundTasks,
    datei: UploadFile = File(...),
    name: str = Form(default="Neue Dokumentvorlage"),
    db=Depends(datenbank_sitzung),
):
    mitglied = muss_angemeldet_sein(request, db)
    kennzahlen = _organisation_kennzahlen(db, mitglied.organisation_id)
    if kennzahlen["vorlagen"] >= kennzahlen["abonnement"].vorlagen_limit:
        raise HTTPException(status_code=409, detail="Das Vorlagenlimit des aktuellen Tarifs ist erreicht.")

    erlaubte_typen = {"application/pdf", "image/png", "image/jpeg", "image/webp"}
    inhaltstyp = datei.content_type or "application/octet-stream"
    if inhaltstyp not in erlaubte_typen:
        raise HTTPException(status_code=415, detail="Bitte laden Sie eine PDF-, PNG-, JPG- oder WEBP-Datei hoch.")

    ursprungsname = datei.filename or "dokument.pdf"
    endung = Path(ursprungsname).suffix.lower() or ".pdf"
    ziel = cfg.upload_pfad / f"{mitglied.organisation_id}-{uuid.uuid4().hex}{endung}"
    groesse = 0
    try:
        with ziel.open("wb") as ausgabe:
            while True:
                block = await datei.read(1024 * 1024)
                if not block:
                    break
                groesse += len(block)
                if groesse > cfg.max_upload_mb * 1024 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Die Datei darf höchstens {cfg.max_upload_mb} MB groß sein.",
                    )
                ausgabe.write(block)
    except Exception:
        ziel.unlink(missing_ok=True)
        raise
    finally:
        await datei.close()

    seiten = 1
    if inhaltstyp == "application/pdf":
        try:
            seiten = max(1, len(PdfReader(str(ziel)).pages))
        except Exception:
            ziel.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail="Die PDF-Datei ist beschädigt oder kann nicht gelesen werden.")

    # Bereits vor dem externen KI-Lauf werden echte PDF-Felder und Eingabelinien lokal erkannt.
    # Dadurch wird niemals mehr ein allgemeines Vier-Felder-Schema als Dokumentanalyse ausgegeben.
    vorlaeufiges_schema, lokale_diagnostik = _lokale_analyse(ziel, ursprungsname)
    vorlaeufige_felder = list(vorlaeufiges_schema.get("felder", []) or [])
    eintrag = Dokumentvorlage(
        organisation_id=mitglied.organisation_id,
        erstellt_von_id=mitglied.id,
        name=name.strip() or "Neue Dokumentvorlage",
        dateiname=ursprungsname,
        speicherort=str(ziel),
        inhaltstyp=inhaltstyp,
        originalgroesse=groesse,
        status="wird analysiert",
        seiten=seiten,
        schema=vorlaeufiges_schema,
        erkannte_felder=len(vorlaeufige_felder),
        zusammenfassung=str(vorlaeufiges_schema.get("zusammenfassung", "")),
        aktualisiert_am=datetime.now(timezone.utc),
    )
    db.add(eintrag)
    db.commit()
    db.refresh(eintrag)

    background_tasks.add_task(_analyse_abschliessen, eintrag.id)
    return {
        "erfolg": True,
        "vorlage_id": eintrag.id,
        "status": "Bestätigung erforderlich" if vorlaeufige_felder else "wird analysiert",
        "analyse_status": eintrag.status,
        "schema": vorlaeufiges_schema if vorlaeufige_felder else None,
        "lokale_diagnostik": lokale_diagnostik,
        "status_url": f"/api/vorlagen/{eintrag.id}/analyse-status",
        "weiter": f"/vorlagen/{eintrag.id}",
        "hinweis": (
            f"Die Datei ist gespeichert. {len(vorlaeufige_felder)} konkrete Bereiche wurden bereits lokal erkannt; "
            "der Prüflauf wird im Hintergrund verfeinert."
            if vorlaeufige_felder
            else "Die Datei ist gespeichert. Der Prüflauf wird im Hintergrund fortgesetzt."
        ),
    }


@app.get("/api/vorlagen/{vorlage_id}/analyse-status")
def analyse_status(vorlage_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)

    if eintrag.status == "wird analysiert" and _utc(eintrag.aktualisiert_am) < datetime.now(timezone.utc) - timedelta(minutes=4):
        eintrag.status = "Analyse unterbrochen"
        eintrag.aktualisiert_am = datetime.now(timezone.utc)
        db.commit()

    fertig = eintrag.status in {"Bestätigung erforderlich", "bereit"}
    fehler = eintrag.status in {"Analyse unterbrochen", "Analyse fehlgeschlagen"}
    return {
        "erfolg": True,
        "vorlage_id": eintrag.id,
        "status": eintrag.status,
        "fertig": fertig,
        "fehler": fehler,
        "schema": eintrag.schema if fertig else None,
        "weiter": f"/vorlagen/{eintrag.id}",
        "hinweis": (
            "Die Analyse ist abgeschlossen."
            if fertig
            else "Der Prüflauf läuft weiter."
            if not fehler
            else "Es wurde kein belastbares Feldschema erzeugt. Die Datei bleibt gespeichert und kann erneut analysiert werden."
        ),
    }


@app.post("/api/vorlagen/{vorlage_id}/analyse-neu-starten", status_code=202)
def analyse_neu_starten(
    vorlage_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db=Depends(datenbank_sitzung),
):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    if not Path(eintrag.speicherort).exists():
        raise HTTPException(status_code=404, detail="Die hochgeladene Datei ist nicht mehr verfügbar.")
    if eintrag.status == "wird analysiert":
        return {"erfolg": True, "status": eintrag.status, "status_url": f"/api/vorlagen/{eintrag.id}/analyse-status"}

    eintrag.status = "wird analysiert"
    eintrag.aktualisiert_am = datetime.now(timezone.utc)
    db.commit()
    background_tasks.add_task(_analyse_abschliessen, eintrag.id)
    return {
        "erfolg": True,
        "status": eintrag.status,
        "status_url": f"/api/vorlagen/{eintrag.id}/analyse-status",
    }


__all__ = ["app"]
