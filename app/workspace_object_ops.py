from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .database import datenbank_sitzung
from .main import app, muss_angemeldet_sein
from .models import Nutzungsereignis
from .live_workspace import _entwurf_fuer_mitglied


class FreiesObjektAktion(BaseModel):
    aktion: str
    edit_id: str
    seite: int | None = Field(default=None, ge=1)
    x: float | None = Field(default=None, ge=0.0, le=1.0)
    y: float | None = Field(default=None, ge=0.0, le=1.0)


def _freie_edit_finden(zustand: dict[str, Any] | None, edit_id: str) -> tuple[int, dict[str, Any]]:
    edits = list((zustand or {}).get("edits") or [])
    for index, edit in enumerate(edits):
        if str(edit.get("id") or "") == str(edit_id) and edit.get("quelle") == "freie-position":
            return index, copy.deepcopy(edit)
    raise HTTPException(status_code=404, detail="Der eingefügte Text wurde nicht mehr gefunden.")


def _zustand_mit_edit(zustand: dict[str, Any] | None, index: int, edit: dict[str, Any] | None) -> dict[str, Any]:
    daten = copy.deepcopy(zustand or {})
    edits = list(daten.get("edits") or [])
    if index < 0 or index >= len(edits):
        raise HTTPException(status_code=404, detail="Der eingefügte Text wurde nicht mehr gefunden.")
    if edit is None:
        edits.pop(index)
    else:
        edits[index] = edit
    daten["edits"] = edits
    daten["revision"] = int(daten.get("revision") or 0) + 1
    daten["version"] = max(2, int(daten.get("version") or 0))
    return daten


def _freie_edit_verschieben(
    dateipfad: Path,
    zustand: dict[str, Any] | None,
    edit_id: str,
    seite: int,
    x: float,
    y: float,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    index, edit = _freie_edit_finden(zustand, edit_id)
    alte_seite = int(edit.get("seite") or 1)
    dokument = fitz.open(dateipfad)
    try:
        if seite < 1 or seite > len(dokument):
            raise HTTPException(status_code=422, detail="Die Zielseite ist nicht vorhanden.")
        zielseite = dokument[seite - 1]
        bbox = list(edit.get("bbox") or [0, 0, 0, 0])
        alt = fitz.Rect(*bbox)
        if alt.is_empty or alt.width <= 0 or alt.height <= 0:
            raise HTTPException(status_code=422, detail="Die Position des eingefügten Textes ist ungültig.")

        breite = min(float(alt.width), max(20.0, float(zielseite.rect.width) - 12.0))
        hoehe = min(float(alt.height), max(10.0, float(zielseite.rect.height) - 12.0))
        x0 = max(6.0, min(float(x) * float(zielseite.rect.width), float(zielseite.rect.width) - breite - 6.0))
        y0 = max(6.0, min(float(y) * float(zielseite.rect.height), float(zielseite.rect.height) - hoehe - 6.0))
        neu = fitz.Rect(x0, y0, x0 + breite, y0 + hoehe)

        alte_origin = list(edit.get("origin") or [alt.x0, alt.y1])
        origin_dx = float(alte_origin[0]) - float(alt.x0)
        origin_dy = float(alte_origin[1]) - float(alt.y0)
        write_offset = float(edit.get("write_x1") or alt.x1) - float(alt.x0)

        edit["seite"] = int(seite)
        edit["bbox"] = [round(neu.x0, 3), round(neu.y0, 3), round(neu.x1, 3), round(neu.y1, 3)]
        edit["origin"] = [round(neu.x0 + origin_dx, 3), round(neu.y0 + origin_dy, 3)]
        edit["write_x1"] = round(min(float(zielseite.rect.width) - 6.0, neu.x0 + max(neu.width, write_offset)), 3)
        edit["ziel"] = f"Freie Position auf Seite {seite}"
        edit["quelle"] = "freie-position"
        edit["entfernen"] = False
        return _zustand_mit_edit(zustand, index, edit), edit, alte_seite
    finally:
        dokument.close()


def _freie_edit_loeschen(zustand: dict[str, Any] | None, edit_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    index, edit = _freie_edit_finden(zustand, edit_id)
    return _zustand_mit_edit(zustand, index, None), edit


@app.post("/api/workspace/{entwurf_id}/free-object")
def freies_objekt_bearbeiten(
    entwurf_id: int,
    eingabe: FreiesObjektAktion,
    request: Request,
    db=Depends(datenbank_sitzung),
):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = _entwurf_fuer_mitglied(db, mitglied, entwurf_id)
    zustand = copy.deepcopy(eintrag.zustand or {})
    aktion = eingabe.aktion.strip().lower()

    if aktion in {"loeschen", "löschen", "delete", "remove"}:
        zustand, entfernt = _freie_edit_loeschen(zustand, eingabe.edit_id)
        seiten = [int(entfernt.get("seite") or 1)]
        antwort = {
            "erfolg": True,
            "aktion": "loeschen",
            "deleted_id": eingabe.edit_id,
            "revision": int(zustand.get("revision") or 0),
            "seiten": seiten,
        }
    elif aktion in {"verschieben", "move"}:
        if eingabe.seite is None or eingabe.x is None or eingabe.y is None:
            raise HTTPException(status_code=422, detail="Für das Verschieben fehlt die Zielposition.")
        zustand, edit, alte_seite = _freie_edit_verschieben(
            Path(eintrag.speicherort),
            zustand,
            eingabe.edit_id,
            int(eingabe.seite),
            float(eingabe.x),
            float(eingabe.y),
        )
        seiten = sorted({alte_seite, int(edit["seite"])})
        antwort = {
            "erfolg": True,
            "aktion": "verschieben",
            "edit": edit,
            "revision": int(zustand.get("revision") or 0),
            "seiten": seiten,
        }
    else:
        raise HTTPException(status_code=422, detail="Diese Objektaktion wird nicht unterstützt.")

    eintrag.zustand = zustand
    eintrag.aktualisiert_am = datetime.now(timezone.utc)
    db.add(
        Nutzungsereignis(
            organisation_id=mitglied.organisation_id,
            art="live_freies_objekt",
            menge=1,
            kosten_euro=0,
            einzelheiten={"aktion": antwort["aktion"], "edit_id": eingabe.edit_id},
        )
    )
    db.commit()
    return antwort


__all__ = ["freies_objekt_bearbeiten"]
