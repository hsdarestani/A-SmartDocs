from __future__ import annotations

import copy
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
from fastapi import BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, select

from .database import Sitzung, datenbank_sitzung
from .form_analysis import formular_lokal_analysieren
from .live_chat import ki_bearbeitungsplan
from .live_document_engine import (
    anker_nach_id,
    edit_aus_anker,
    edit_speichern,
    letztes_edit_entfernen,
    lokale_anweisung,
    pdf_exportieren,
    pdf_index,
    seite_als_png,
    ziel_aufloesen,
)
from .main import (
    _organisation_kennzahlen,
    app,
    aktuelles_mitglied,
    cfg,
    grundkontext,
    muss_angemeldet_sein,
    vorlagen,
    weiterleitung_anmeldung,
)
from .models import Arbeitsausgabe, Arbeitsdokument, Dokumentausgabe, Nutzungsereignis


class LiveEditEingabe(BaseModel):
    nachricht: str
    anker_id: str | None = None


def _route_entfernen(pfad: str, methode: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == pfad
            and methode in (getattr(route, "methods", set()) or set())
        )
    ]


_route_entfernen("/arbeitsbereich", "GET")


def _entwurf_fuer_mitglied(db, mitglied, entwurf_id: int) -> Arbeitsdokument:
    eintrag = db.get(Arbeitsdokument, entwurf_id)
    if not eintrag or eintrag.organisation_id != mitglied.organisation_id:
        raise HTTPException(status_code=404, detail="Das Arbeitsdokument wurde nicht gefunden.")
    return eintrag


def _ausgabe_fuer_mitglied(db, mitglied, ausgabe_id: int) -> Arbeitsausgabe:
    eintrag = db.get(Arbeitsausgabe, ausgabe_id)
    if not eintrag or eintrag.organisation_id != mitglied.organisation_id:
        raise HTTPException(status_code=404, detail="Die PDF-Ausgabe wurde nicht gefunden.")
    return eintrag


def _dialog_anhaengen(zustand: dict[str, Any], rolle: str, text: str) -> dict[str, Any]:
    daten = copy.deepcopy(zustand or {})
    dialog = list(daten.get("dialog") or [])
    dialog.append({"rolle": rolle, "text": str(text)[:3000]})
    daten["dialog"] = dialog[-40:]
    return daten


def _hinweise_im_hintergrund(entwurf_id: int) -> None:
    with Sitzung() as db:
        eintrag = db.get(Arbeitsdokument, entwurf_id)
        if not eintrag:
            return
        pfad = Path(eintrag.speicherort)
        if not pfad.exists():
            return
        try:
            schema, _diagnostik = formular_lokal_analysieren(pfad, eintrag.dateiname)
            felder = []
            for feld in list(schema.get("felder") or [])[:120]:
                beispiel = str(feld.get("beispiel") or "").strip()
                bezeichnung = str(feld.get("bezeichnung") or "").strip()
                if not beispiel and not bezeichnung:
                    continue
                felder.append(
                    {
                        "schluessel": str(feld.get("schluessel") or ""),
                        "bezeichnung": bezeichnung,
                        "beispiel": beispiel,
                        "seite": max(1, int(feld.get("seite") or 1)),
                        "hinweis": str(feld.get("hinweis") or ""),
                    }
                )
            daten = copy.deepcopy(eintrag.zustand or {})
            daten["hinweise"] = felder
            daten["hinweise_bereit"] = True
            eintrag.zustand = daten
            eintrag.aktualisiert_am = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            daten = copy.deepcopy(eintrag.zustand or {})
            daten["hinweise_bereit"] = False
            eintrag.zustand = daten
            db.commit()


def _dateiname(text: str, standard: str = "Dokument") -> str:
    basis = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß_-]+", "-", str(text or "")).strip("-")
    return (basis or standard)[:120]


def _anker_auf_seite(index: dict[str, Any], text: str, seite: int | None) -> dict[str, Any] | None:
    gesucht = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not gesucht:
        return None
    for seiteninfo in index.get("seiten", []):
        if seite and int(seiteninfo.get("seite") or 0) != seite:
            continue
        for anker in seiteninfo.get("anker", []):
            vorhanden = re.sub(r"\s+", " ", str(anker.get("text") or "")).strip().lower()
            if vorhanden == gesucht or gesucht in vorhanden:
                return copy.deepcopy(anker)
    return None


@app.get("/arbeitsbereich", response_class=HTMLResponse)
def live_startseite(request: Request, db=Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    entwuerfe = db.scalars(
        select(Arbeitsdokument)
        .where(Arbeitsdokument.organisation_id == mitglied.organisation_id)
        .order_by(Arbeitsdokument.aktualisiert_am.desc())
        .limit(6)
    ).all()
    ausgaben = db.scalars(
        select(Arbeitsausgabe)
        .where(Arbeitsausgabe.organisation_id == mitglied.organisation_id)
        .order_by(Arbeitsausgabe.erstellt_am.desc())
        .limit(5)
    ).all()
    kontext = grundkontext(request, db, "arbeitsbereich")
    kontext.update(
        {
            "hauptfluss": True,
            "entwuerfe": entwuerfe,
            "live_ausgaben": ausgaben,
            "kennzahlen": _organisation_kennzahlen(db, mitglied.organisation_id),
        }
    )
    return vorlagen.TemplateResponse("workspace_start.html", kontext)


@app.post("/api/workspace/upload")
async def live_upload(
    background_tasks: BackgroundTasks,
    request: Request,
    datei: UploadFile = File(...),
    db=Depends(datenbank_sitzung),
):
    mitglied = muss_angemeldet_sein(request, db)
    originalname = Path(datei.filename or "Dokument.pdf").name
    if Path(originalname).suffix.lower() != ".pdf" and datei.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Im direkten Arbeitsfluss werden derzeit PDF-Dokumente unterstützt.")

    ziel = cfg.upload_pfad / f"live-{mitglied.organisation_id}-{uuid.uuid4().hex}.pdf"
    groesse = 0
    try:
        with ziel.open("wb") as ausgabe:
            while True:
                block = await datei.read(1024 * 1024)
                if not block:
                    break
                groesse += len(block)
                if groesse > cfg.max_upload_mb * 1024 * 1024:
                    raise HTTPException(status_code=413, detail=f"Die PDF-Datei darf höchstens {cfg.max_upload_mb} MB groß sein.")
                ausgabe.write(block)
    except Exception:
        ziel.unlink(missing_ok=True)
        raise
    finally:
        await datei.close()

    try:
        dokument = fitz.open(ziel)
        if dokument.needs_pass:
            dokument.close()
            raise HTTPException(status_code=422, detail="Passwortgeschützte PDFs können nicht direkt bearbeitet werden.")
        seiten = len(dokument)
        dokument.close()
        if seiten < 1:
            raise ValueError("leer")
    except HTTPException:
        ziel.unlink(missing_ok=True)
        raise
    except Exception:
        ziel.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Die PDF-Datei ist beschädigt oder kann nicht gelesen werden.")

    eintrag = Arbeitsdokument(
        organisation_id=mitglied.organisation_id,
        erstellt_von_id=mitglied.id,
        name=Path(originalname).stem[:180] or "Dokument",
        dateiname=originalname,
        speicherort=str(ziel),
        inhaltstyp="application/pdf",
        originalgroesse=groesse,
        seiten=seiten,
        status="bearbeitung",
        zustand={"version": 2, "revision": 0, "edits": [], "hinweise": [], "hinweise_bereit": False, "dialog": []},
        aktualisiert_am=datetime.now(timezone.utc),
    )
    db.add(eintrag)
    db.commit()
    db.refresh(eintrag)
    background_tasks.add_task(_hinweise_im_hintergrund, eintrag.id)
    return {
        "erfolg": True,
        "arbeitsdokument_id": eintrag.id,
        "weiter": f"/workspace/{eintrag.id}",
        "hinweis": "PDF ist bereit. Sie können sofort im Dokument klicken oder eine Änderung schreiben.",
    }


@app.get("/workspace/{entwurf_id}", response_class=HTMLResponse)
def live_editor(entwurf_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    eintrag = _entwurf_fuer_mitglied(db, mitglied, entwurf_id)
    pfad = Path(eintrag.speicherort)
    if not pfad.exists():
        raise HTTPException(status_code=404, detail="Die Originaldatei ist nicht mehr verfügbar.")
    index = pdf_index(pfad)
    kontext = grundkontext(request, db, "workspace")
    kontext.update(
        {
            "hauptfluss": True,
            "entwurf": eintrag,
            "dokument_index": index,
            "revision": int((eintrag.zustand or {}).get("revision") or 0),
            "dialog": list((eintrag.zustand or {}).get("dialog") or []),
        }
    )
    return vorlagen.TemplateResponse("workspace_editor.html", kontext)


@app.get("/workspace/{entwurf_id}/seiten/{seitenzahl}.png")
def live_seite(entwurf_id: int, seitenzahl: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = _entwurf_fuer_mitglied(db, mitglied, entwurf_id)
    try:
        inhalt = seite_als_png(Path(eintrag.speicherort), eintrag.zustand, seitenzahl)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Die Vorschau konnte nicht erstellt werden: {exc}") from exc
    return Response(
        content=inhalt,
        media_type="image/png",
        headers={"Cache-Control": "private, no-store, max-age=0", "X-Content-Type-Options": "nosniff"},
    )


@app.post("/api/workspace/{entwurf_id}/edit")
def live_edit(entwurf_id: int, eingabe: LiveEditEingabe, request: Request, db=Depends(datenbank_sitzung)):
    start = time.perf_counter()
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = _entwurf_fuer_mitglied(db, mitglied, entwurf_id)
    nachricht = eingabe.nachricht.strip()
    if not nachricht:
        raise HTTPException(status_code=422, detail="Bitte schreiben Sie die gewünschte Änderung.")

    pfad = Path(eintrag.speicherort)
    index = pdf_index(pfad)
    zustand = copy.deepcopy(eintrag.zustand or {})
    geaenderte_seiten: set[int] = set()
    angewendete_edits: list[dict[str, Any]] = []
    modus = "lokal"
    antworttext = ""

    if eingabe.anker_id:
        anker = anker_nach_id(index, eingabe.anker_id)
        if not anker:
            raise HTTPException(status_code=404, detail="Der ausgewählte Text wurde nicht mehr gefunden.")
        wert = "" if nachricht.lower() in {"entfernen", "löschen", "loschen", "remove", "delete"} else nachricht
        edit = edit_aus_anker(anker, wert, quelle="auswahl", ziel=str(anker.get("text") or ""))
        zustand = edit_speichern(zustand, edit)
        angewendete_edits.append(edit)
        geaenderte_seiten.add(int(edit["seite"]))
        antworttext = f"„{edit['alter_text']}“ wurde direkt im Dokument ersetzt."
        modus = "auswahl"
    else:
        lokal = lokale_anweisung(nachricht)
        if lokal:
            anker = ziel_aufloesen(index, zustand, lokal["ziel"])
            if anker:
                edit = edit_aus_anker(anker, lokal["wert"], quelle="lokal", ziel=lokal["ziel"])
                zustand = edit_speichern(zustand, edit)
                angewendete_edits.append(edit)
                geaenderte_seiten.add(int(edit["seite"]))
                antworttext = f"„{edit['ziel']}“ wurde sofort aktualisiert."

        if not angewendete_edits:
            modus = "ki"
            try:
                plan, _nutzung = ki_bearbeitungsplan(index.get("text", ""), list(zustand.get("hinweise") or []), nachricht)
            except Exception:
                plan = {"edits": [], "antwort": "Ich konnte die Stelle nicht schnell genug sicher zuordnen. Klicken Sie den Text im Dokument an; dann ist die Änderung sofort eindeutig."}
            for plan_edit in list(plan.get("edits") or [])[:6]:
                alter_text = str(plan_edit.get("alter_text") or "").strip()
                seite = int(plan_edit.get("seite") or 0) or None
                anker = _anker_auf_seite(index, alter_text, seite) or ziel_aufloesen(index, zustand, alter_text)
                if not anker:
                    continue
                edit = edit_aus_anker(
                    anker,
                    str(plan_edit.get("neuer_text") or ""),
                    quelle="ki-plan",
                    ziel=str(plan_edit.get("ziel") or alter_text),
                )
                zustand = edit_speichern(zustand, edit)
                angewendete_edits.append(edit)
                geaenderte_seiten.add(int(edit["seite"]))
            antworttext = str(plan.get("antwort") or "").strip()
            if not angewendete_edits:
                antworttext = antworttext or "Klicken Sie den zu ändernden Text direkt im Dokument an. Danach genügt der neue Wert."

    zustand = _dialog_anhaengen(zustand, "nutzer", nachricht)
    zustand = _dialog_anhaengen(zustand, "assistent", antworttext)
    eintrag.zustand = zustand
    eintrag.aktualisiert_am = datetime.now(timezone.utc)
    db.add(
        Nutzungsereignis(
            organisation_id=mitglied.organisation_id,
            art="live_bearbeitung",
            menge=1,
            kosten_euro=0,
            einzelheiten={"modus": modus, "edits": len(angewendete_edits)},
        )
    )
    db.commit()

    return {
        "erfolg": bool(angewendete_edits),
        "modus": modus,
        "antwort": antworttext,
        "revision": int(zustand.get("revision") or 0),
        "seiten": sorted(geaenderte_seiten),
        "edits": [
            {
                "id": edit.get("id"),
                "seite": edit.get("seite"),
                "alter_text": edit.get("alter_text"),
                "neuer_text": edit.get("neuer_text"),
                "bbox": edit.get("bbox"),
            }
            for edit in angewendete_edits
        ],
        "dauer_ms": round((time.perf_counter() - start) * 1000),
        "braucht_auswahl": not angewendete_edits,
    }


@app.post("/api/workspace/{entwurf_id}/undo")
def live_undo(entwurf_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = _entwurf_fuer_mitglied(db, mitglied, entwurf_id)
    vorher = list((eintrag.zustand or {}).get("edits") or [])
    zustand = letztes_edit_entfernen(eintrag.zustand)
    eintrag.zustand = zustand
    eintrag.aktualisiert_am = datetime.now(timezone.utc)
    db.commit()
    seite = int(vorher[-1].get("seite") or 1) if vorher else 1
    return {"erfolg": True, "revision": int(zustand.get("revision") or 0), "seiten": [seite]}


@app.post("/api/workspace/{entwurf_id}/export")
def live_export(entwurf_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = _entwurf_fuer_mitglied(db, mitglied, entwurf_id)
    kennzahlen = _organisation_kennzahlen(db, mitglied.organisation_id)
    monat_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    live_monat = int(
        db.scalar(
            select(func.count(Arbeitsausgabe.id)).where(
                Arbeitsausgabe.organisation_id == mitglied.organisation_id,
                Arbeitsausgabe.erstellt_am >= monat_start,
            )
        )
        or 0
    )
    if int(kennzahlen.get("dokumente", 0)) + live_monat >= int(kennzahlen.get("dokument_limit", 0) or 0):
        raise HTTPException(status_code=409, detail="Das monatliche Dokumentenlimit ist erreicht.")

    titel = eintrag.name or Path(eintrag.dateiname).stem or "Dokument"
    dateiname = f"{_dateiname(titel)}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pdf"
    ziel = cfg.ausgabe_pfad / f"live-{uuid.uuid4().hex}.pdf"
    try:
        seiten = pdf_exportieren(Path(eintrag.speicherort), eintrag.zustand, ziel)
    except Exception as exc:
        ziel.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Das PDF konnte nicht exportiert werden: {exc}") from exc

    ausgabe = Arbeitsausgabe(
        organisation_id=mitglied.organisation_id,
        arbeitsdokument_id=eintrag.id,
        erstellt_von_id=mitglied.id,
        titel=titel,
        dateiname=dateiname,
        speicherort=str(ziel),
        seiten=seiten,
        dateigroesse=ziel.stat().st_size,
    )
    db.add(ausgabe)
    db.add(
        Nutzungsereignis(
            organisation_id=mitglied.organisation_id,
            art="dokument_erstellt",
            menge=1,
            kosten_euro=0,
            einzelheiten={"quelle": "live-workspace", "arbeitsdokument_id": eintrag.id},
        )
    )
    db.commit()
    db.refresh(ausgabe)
    return {
        "erfolg": True,
        "ausgabe_id": ausgabe.id,
        "dateiname": ausgabe.dateiname,
        "download_url": f"/live-ausgaben/{ausgabe.id}/download",
    }


@app.get("/live-ausgaben/{ausgabe_id}/download")
def live_download(ausgabe_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = _ausgabe_fuer_mitglied(db, mitglied, ausgabe_id)
    pfad = Path(eintrag.speicherort)
    if not pfad.exists():
        raise HTTPException(status_code=404, detail="Die PDF-Datei ist nicht mehr verfügbar.")
    return FileResponse(pfad, media_type="application/pdf", filename=eintrag.dateiname)


@app.get("/verlauf", response_class=HTMLResponse)
def live_verlauf(request: Request, db=Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    live_ausgaben = db.scalars(
        select(Arbeitsausgabe)
        .where(Arbeitsausgabe.organisation_id == mitglied.organisation_id)
        .order_by(Arbeitsausgabe.erstellt_am.desc())
        .limit(100)
    ).all()
    alte_ausgaben = db.scalars(
        select(Dokumentausgabe)
        .where(Dokumentausgabe.organisation_id == mitglied.organisation_id)
        .order_by(Dokumentausgabe.erstellt_am.desc())
        .limit(100)
    ).all()
    kontext = grundkontext(request, db, "verlauf")
    kontext.update({"hauptfluss": False, "live_ausgaben": live_ausgaben, "alte_ausgaben": alte_ausgaben})
    return vorlagen.TemplateResponse("workspace_history.html", kontext)


from . import workspace_interaction_v2 as _workspace_interaction_v2  # noqa: E402,F401

__all__ = ["app", "LiveEditEingabe"]
