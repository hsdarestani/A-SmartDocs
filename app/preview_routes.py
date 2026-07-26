from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse

from .database import datenbank_sitzung
from .main import app, muss_angemeldet_sein, vorlage_fuer_mitglied
from .quality import schema_fingerabdruck, schema_mit_qualitaet
from .quality_routes import _preview_pfad


VORSCHAU_PFADE = {
    "/vorlagen/{vorlage_id}/datei",
    "/vorlagen/{vorlage_id}/testausfuellung.pdf",
}


def _ist_alte_vorschau_route(route: Any) -> bool:
    return (
        getattr(route, "path", None) in VORSCHAU_PFADE
        and "GET" in (getattr(route, "methods", set()) or set())
    )


# FileResponse setzt bei einem filename standardmäßig attachment. Da diese beiden
# Routen automatisch in iframes geladen werden, müssen sie ausdrücklich inline sein.
app.router.routes[:] = [route for route in app.router.routes if not _ist_alte_vorschau_route(route)]


def _inline_datei(pfad: Path, media_type: str) -> FileResponse:
    return FileResponse(
        pfad,
        media_type=media_type,
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store, max-age=0",
        },
    )


@app.get("/vorlagen/{vorlage_id}/datei")
def vorlage_inline_anzeigen(vorlage_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    pfad = Path(eintrag.speicherort)
    if not pfad.exists():
        raise HTTPException(status_code=404, detail="Die Originaldatei ist nicht mehr verfügbar.")
    return _inline_datei(pfad, eintrag.inhaltstyp or "application/octet-stream")


@app.get("/vorlagen/{vorlage_id}/testausfuellung.pdf")
def testausfuellung_inline_anzeigen(vorlage_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    schema = schema_mit_qualitaet(eintrag.schema)
    pfad = _preview_pfad(eintrag, schema)
    if not pfad.exists() or schema.get("testausfuellung_hash") != schema_fingerabdruck(schema):
        raise HTTPException(status_code=404, detail="Bitte erzeugen Sie zuerst eine aktuelle Testausfüllung.")
    return _inline_datei(pfad, "application/pdf")


__all__ = []
