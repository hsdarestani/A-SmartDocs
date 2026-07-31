from __future__ import annotations

import copy
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .database import datenbank_sitzung
from .live_chat import ki_bearbeitungsplan
from . import live_document_engine as _engine
from .live_document_engine import (
    anker_nach_id,
    edit_aus_anker,
    edit_speichern,
    lokale_anweisung,
    pdf_index,
    ziel_aufloesen,
)
from .main import app, muss_angemeldet_sein
from .models import Nutzungsereignis
from .live_workspace import _anker_auf_seite, _dialog_anhaengen, _entwurf_fuer_mitglied


class LiveEditEingabeV2(BaseModel):
    nachricht: str = ""
    anker_id: str | None = None
    edit_id: str | None = None
    seite: int | None = Field(default=None, ge=1)
    x: float | None = Field(default=None, ge=0.0, le=1.0)
    y: float | None = Field(default=None, ge=0.0, le=1.0)


class CheckboxTrefferEingabe(BaseModel):
    seite: int = Field(ge=1)
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


def _alte_edit_route(route: Any) -> bool:
    return (
        getattr(route, "path", None) == "/api/workspace/{entwurf_id}/edit"
        and "POST" in (getattr(route, "methods", set()) or set())
    )


app.router.routes[:] = [route for route in app.router.routes if not _alte_edit_route(route)]


def _naechster_textanker(index: dict[str, Any], seite: int, x: float, y: float) -> dict[str, Any] | None:
    kandidaten: list[tuple[float, dict[str, Any]]] = []
    for seiteninfo in index.get("seiten", []):
        if int(seiteninfo.get("seite") or 0) != seite:
            continue
        for anker in seiteninfo.get("anker", []):
            position = anker.get("position") or {}
            ax = float(position.get("x") or 0) + float(position.get("breite") or 0) / 2
            ay = float(position.get("y") or 0) + float(position.get("hoehe") or 0) / 2
            abstand = (ax - x) ** 2 + (ay - y) ** 2
            kandidaten.append((abstand, anker))
    kandidaten.sort(key=lambda item: item[0])
    return copy.deepcopy(kandidaten[0][1]) if kandidaten else None


def _edit_aus_freier_position(
    dateipfad: Path,
    index: dict[str, Any],
    seite: int,
    x: float,
    y: float,
    wert: str,
) -> dict[str, Any]:
    dokument = fitz.open(dateipfad)
    try:
        if seite < 1 or seite > len(dokument):
            raise HTTPException(status_code=422, detail="Die gewählte Dokumentseite ist nicht vorhanden.")
        pdf_seite = dokument[seite - 1]
        px = max(10.0, min(float(pdf_seite.rect.width) - 18.0, x * float(pdf_seite.rect.width)))
        py = max(10.0, min(float(pdf_seite.rect.height) - 18.0, y * float(pdf_seite.rect.height)))
        nachbar = _naechster_textanker(index, seite, x, y) or {}
        schriftgroesse = max(7.0, min(18.0, float(nachbar.get("schriftgroesse") or 10.0)))
        farbe = int(nachbar.get("farbe") or 0)
        max_breite = max(45.0, min(240.0, float(pdf_seite.rect.width) - px - 16.0))
        hoehe = max(12.0, schriftgroesse * 1.35)
        rect = fitz.Rect(px, py, min(float(pdf_seite.rect.width) - 10.0, px + max_breite), min(float(pdf_seite.rect.height) - 6.0, py + hoehe))
        baseline = min(float(pdf_seite.rect.height) - 5.0, py + schriftgroesse)
        return {
            "id": uuid.uuid4().hex,
            "anker_id": "",
            "seite": seite,
            "alter_text": "",
            "neuer_text": str(wert or ""),
            "ziel": f"Freie Position auf Seite {seite}",
            "bbox": [round(rect.x0, 3), round(rect.y0, 3), round(rect.x1, 3), round(rect.y1, 3)],
            "origin": [round(px, 3), round(baseline, 3)],
            "write_x1": round(rect.x1, 3),
            "schriftgroesse": schriftgroesse,
            "farbe": farbe,
            "quelle": "freie-position",
            "entfernen": False,
        }
    finally:
        dokument.close()


def _bestehende_freie_edit(zustand: dict[str, Any], edit_id: str) -> dict[str, Any] | None:
    for edit in list(zustand.get("edits") or []):
        if str(edit.get("id") or "") == edit_id and edit.get("quelle") == "freie-position":
            return copy.deepcopy(edit)
    return None


def _freie_edit_aktualisieren(zustand: dict[str, Any], edit_id: str, wert: str) -> tuple[dict[str, Any], dict[str, Any]]:
    edit = _bestehende_freie_edit(zustand, edit_id)
    if not edit:
        raise HTTPException(status_code=404, detail="Der eingefügte Text wurde nicht mehr gefunden.")
    edit["neuer_text"] = str(wert or "")
    edit["entfernen"] = False
    edit["quelle"] = "freie-position"
    return edit_speichern(zustand, edit), edit


def _rechteck_ist_checkbox(rect: fitz.Rect) -> bool:
    if rect.is_empty:
        return False
    breite = float(rect.width)
    hoehe = float(rect.height)
    if not (5.0 <= breite <= 24.0 and 5.0 <= hoehe <= 24.0):
        return False
    ratio = breite / max(1.0, hoehe)
    return 0.68 <= ratio <= 1.47


def _checkbox_kandidaten(seite: fitz.Page, seitenzahl: int) -> list[dict[str, Any]]:
    kandidaten: list[dict[str, Any]] = []

    try:
        for index, widget in enumerate(list(seite.widgets() or [])):
            typ = getattr(widget, "field_type", None)
            typ_text = str(getattr(widget, "field_type_string", "") or "").lower()
            if typ == getattr(fitz, "PDF_WIDGET_TYPE_CHECKBOX", -999) or "check" in typ_text:
                rect = fitz.Rect(widget.rect)
                if _rechteck_ist_checkbox(rect):
                    kandidaten.append({"rect": rect, "quelle": "widget", "nr": index})
    except Exception:
        pass

    try:
        for zeichnung_index, zeichnung in enumerate(seite.get_drawings() or []):
            gefundene: list[fitz.Rect] = []
            for item in zeichnung.get("items", []):
                if not item:
                    continue
                if item[0] == "re" and len(item) > 1:
                    try:
                        gefundene.append(fitz.Rect(item[1]))
                    except Exception:
                        pass
            if not gefundene:
                try:
                    gefundene.append(fitz.Rect(zeichnung.get("rect")))
                except Exception:
                    pass
            for rect in gefundene:
                if _rechteck_ist_checkbox(rect):
                    kandidaten.append({"rect": rect, "quelle": "zeichnung", "nr": zeichnung_index})
    except Exception:
        pass

    # Viele PDF-Formulare enthalten das Kästchen als einzelnes Unicode-Zeichen.
    try:
        for block in seite.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = str(span.get("text") or "").strip()
                    if text not in {"□", "☐", "◻", "○", "◯"}:
                        continue
                    rect = fitz.Rect(span.get("bbox", (0, 0, 0, 0)))
                    if _rechteck_ist_checkbox(rect):
                        kandidaten.append({"rect": rect, "quelle": "zeichen", "nr": len(kandidaten)})
    except Exception:
        pass

    eindeutig: list[dict[str, Any]] = []
    for kandidat in kandidaten:
        rect = kandidat["rect"]
        if any((rect & alt["rect"]).get_area() >= min(rect.get_area(), alt["rect"].get_area()) * 0.72 for alt in eindeutig):
            continue
        kandidat["id"] = f"p{seitenzahl}-{rect.x0:.1f}-{rect.y0:.1f}-{rect.x1:.1f}-{rect.y1:.1f}"
        eindeutig.append(kandidat)
    return eindeutig


def _checkbox_bei_position(dateipfad: Path, seitenzahl: int, x: float, y: float) -> dict[str, Any] | None:
    dokument = fitz.open(dateipfad)
    try:
        if seitenzahl < 1 or seitenzahl > len(dokument):
            return None
        seite = dokument[seitenzahl - 1]
        punkt = fitz.Point(float(x) * float(seite.rect.width), float(y) * float(seite.rect.height))
        kandidaten = _checkbox_kandidaten(seite, seitenzahl)
        treffer: list[tuple[float, dict[str, Any]]] = []
        for kandidat in kandidaten:
            rect = fitz.Rect(kandidat["rect"])
            toleranz = max(2.5, min(rect.width, rect.height) * 0.35)
            hit = fitz.Rect(rect.x0 - toleranz, rect.y0 - toleranz, rect.x1 + toleranz, rect.y1 + toleranz)
            if punkt in hit:
                cx = (rect.x0 + rect.x1) / 2
                cy = (rect.y0 + rect.y1) / 2
                abstand = math.hypot(float(punkt.x) - cx, float(punkt.y) - cy)
                treffer.append((abstand, kandidat))
        treffer.sort(key=lambda item: item[0])
        if not treffer:
            return None
        kandidat = treffer[0][1]
        rect = fitz.Rect(kandidat["rect"])
        return {
            "id": kandidat["id"],
            "seite": seitenzahl,
            "bbox": [round(rect.x0, 3), round(rect.y0, 3), round(rect.x1, 3), round(rect.y1, 3)],
        }
    finally:
        dokument.close()


def _checkbox_edit(zustand: dict[str, Any], checkbox: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    anker_id = f"checkbox:{checkbox['id']}"
    vorhanden = next((edit for edit in list(zustand.get("edits") or []) if edit.get("anker_id") == anker_id), None)
    checked = not bool((vorhanden or {}).get("checked"))
    rect = fitz.Rect(*checkbox["bbox"])
    edit = {
        "id": str((vorhanden or {}).get("id") or uuid.uuid4().hex),
        "anker_id": anker_id,
        "seite": int(checkbox["seite"]),
        "alter_text": "",
        "neuer_text": "",
        "ziel": "Checkbox",
        "bbox": list(checkbox["bbox"]),
        "origin": [round(rect.x0, 3), round(rect.y1, 3)],
        "write_x1": round(rect.x1, 3),
        "schriftgroesse": max(7.0, min(14.0, rect.height * 0.9)),
        "farbe": 0,
        "quelle": "checkbox",
        "entfernen": False,
        "checked": checked,
    }
    return edit_speichern(zustand, edit), edit


def _checkbox_einzeichnen(seite: fitz.Page, edit: dict[str, Any]) -> None:
    if not bool(edit.get("checked")):
        return
    rect = fitz.Rect(*(edit.get("bbox") or [0, 0, 0, 0]))
    if rect.is_empty:
        return
    w = float(rect.width)
    h = float(rect.height)
    p1 = fitz.Point(rect.x0 + w * 0.20, rect.y0 + h * 0.53)
    p2 = fitz.Point(rect.x0 + w * 0.42, rect.y0 + h * 0.76)
    p3 = fitz.Point(rect.x0 + w * 0.82, rect.y0 + h * 0.25)
    linienbreite = max(1.0, min(w, h) * 0.105)
    seite.draw_line(p1, p2, color=(0, 0, 0), width=linienbreite, overlay=True)
    seite.draw_line(p2, p3, color=(0, 0, 0), width=linienbreite, overlay=True)


def _seite_bearbeiten_ohne_unnoetige_loeschung(seite: fitz.Page, edits: list[dict[str, Any]]) -> None:
    operationen: list[tuple[dict[str, Any], fitz.Rect]] = []
    checkbox_edits: list[dict[str, Any]] = []
    hat_loeschung = False
    for edit in edits:
        if edit.get("quelle") == "checkbox":
            checkbox_edits.append(edit)
            continue
        rect = fitz.Rect(*(edit.get("bbox") or [0, 0, 0, 0]))
        if rect.is_empty or rect.width <= 0 or rect.height <= 0:
            continue
        entfernen = bool(edit.get("entfernen", bool(str(edit.get("alter_text") or "").strip())))
        if entfernen:
            loeschrect = fitz.Rect(
                max(0, rect.x0 - 1.6),
                max(0, rect.y0 - 1.4),
                min(seite.rect.width, rect.x1 + 1.8),
                min(seite.rect.height, rect.y1 + 1.5),
            )
            hintergrund = _engine._hintergrundfarbe(seite, loeschrect)
            seite.add_redact_annot(loeschrect, fill=hintergrund, cross_out=False)
            hat_loeschung = True
        operationen.append((edit, rect))

    if hat_loeschung:
        try:
            seite.apply_redactions(images=0, graphics=0, text=0)
        except TypeError:
            seite.apply_redactions(images=0)

    for edit, _ in operationen:
        _engine._ersatz_einfuegen(seite, edit)
    for edit in checkbox_edits:
        _checkbox_einzeichnen(seite, edit)


# Preview und Export benutzen dadurch denselben Renderer: freie Einfügungen löschen
# keine Linien, Hintergründe oder benachbarte Inhalte des Originaldokuments.
_engine._seite_bearbeiten = _seite_bearbeiten_ohne_unnoetige_loeschung


@app.post("/api/workspace/{entwurf_id}/checkbox-at")
def live_checkbox_an_position(
    entwurf_id: int,
    eingabe: CheckboxTrefferEingabe,
    request: Request,
    db=Depends(datenbank_sitzung),
):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = _entwurf_fuer_mitglied(db, mitglied, entwurf_id)
    checkbox = _checkbox_bei_position(Path(eintrag.speicherort), int(eingabe.seite), float(eingabe.x), float(eingabe.y))
    if not checkbox:
        return {"treffer": False}

    zustand, edit = _checkbox_edit(copy.deepcopy(eintrag.zustand or {}), checkbox)
    eintrag.zustand = zustand
    eintrag.aktualisiert_am = datetime.now(timezone.utc)
    db.add(
        Nutzungsereignis(
            organisation_id=mitglied.organisation_id,
            art="live_checkbox",
            menge=1,
            kosten_euro=0,
            einzelheiten={"seite": edit["seite"], "checked": bool(edit["checked"])},
        )
    )
    db.commit()
    return {
        "treffer": True,
        "checked": bool(edit["checked"]),
        "revision": int(zustand.get("revision") or 0),
        "seite": int(edit["seite"]),
        "bbox": edit["bbox"],
    }


@app.post("/api/workspace/{entwurf_id}/edit")
def live_edit_v2(entwurf_id: int, eingabe: LiveEditEingabeV2, request: Request, db=Depends(datenbank_sitzung)):
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

    if eingabe.edit_id:
        zustand, edit = _freie_edit_aktualisieren(zustand, eingabe.edit_id, nachricht)
        angewendete_edits.append(edit)
        geaenderte_seiten.add(int(edit["seite"]))
        antworttext = "Der eingefügte Text wurde aktualisiert."
        modus = "freie-position-edit"
    else:
        freie_position = eingabe.seite is not None and eingabe.x is not None and eingabe.y is not None
        if freie_position and not eingabe.anker_id:
            edit = _edit_aus_freier_position(pfad, index, int(eingabe.seite), float(eingabe.x), float(eingabe.y), nachricht)
            zustand = edit_speichern(zustand, edit)
            angewendete_edits.append(edit)
            geaenderte_seiten.add(int(edit["seite"]))
            antworttext = f"Text wurde auf Seite {edit['seite']} an der gewählten freien Stelle eingefügt."
            modus = "freie-position"
        elif eingabe.anker_id:
            anker = anker_nach_id(index, eingabe.anker_id)
            if not anker:
                raise HTTPException(status_code=404, detail="Der ausgewählte Text wurde nicht mehr gefunden.")
            wert = "" if nachricht.lower() in {"entfernen", "löschen", "loschen", "remove", "delete"} else nachricht
            edit = edit_aus_anker(anker, wert, quelle="auswahl", ziel=str(anker.get("text") or ""))
            edit["entfernen"] = True
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
                    edit["entfernen"] = True
                    zustand = edit_speichern(zustand, edit)
                    angewendete_edits.append(edit)
                    geaenderte_seiten.add(int(edit["seite"]))
                    antworttext = f"„{edit['ziel']}“ wurde sofort aktualisiert."

            if not angewendete_edits:
                modus = "ki"
                try:
                    plan, _nutzung = ki_bearbeitungsplan(index.get("text", ""), list(zustand.get("hinweise") or []), nachricht)
                except Exception:
                    plan = {"edits": [], "antwort": "Ich konnte die Stelle nicht schnell genug sicher zuordnen. Klicken Sie den Text oder eine freie Stelle im Dokument an."}
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
                    edit["entfernen"] = True
                    zustand = edit_speichern(zustand, edit)
                    angewendete_edits.append(edit)
                    geaenderte_seiten.add(int(edit["seite"]))
                antworttext = str(plan.get("antwort") or "").strip()
                if not angewendete_edits:
                    antworttext = antworttext or "Klicken Sie den zu ändernden Text oder eine freie Stelle direkt im Dokument an."

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
                "quelle": edit.get("quelle"),
            }
            for edit in angewendete_edits
        ],
        "dauer_ms": round((time.perf_counter() - start) * 1000),
        "braucht_auswahl": not angewendete_edits,
    }


__all__ = ["live_edit_v2"]
