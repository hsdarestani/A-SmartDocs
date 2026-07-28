from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import fitz
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from PIL import Image, ImageOps
from sqlalchemy import select

from .database import datenbank_sitzung
from .main import (
    app,
    aktuelles_mitglied,
    grundkontext,
    vorlage_fuer_mitglied,
    vorlagen,
    weiterleitung_anmeldung,
)
from .models import Vorlagendialog


def _alte_detailroute(route: Any) -> bool:
    return (
        getattr(route, "path", None) == "/vorlagen/{vorlage_id}"
        and "GET" in (getattr(route, "methods", set()) or set())
    )


app.router.routes[:] = [route for route in app.router.routes if not _alte_detailroute(route)]


def _pflichtfelder_initial_optional(schema: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    daten = dict(schema or {})
    if daten.get("pflichtfelder_initialisiert") is True:
        return daten, False
    felder = []
    for original in list(daten.get("felder", []) or []):
        feld = dict(original)
        feld["pflichtfeld"] = False
        feld.setdefault("alten_inhalt_entfernen", bool(str(feld.get("beispiel") or "").strip()))
        feld.setdefault("vorschlag_status", "vorgeschlagen")
        felder.append(feld)
    daten["felder"] = felder
    daten["pflichtfelder_initialisiert"] = True
    return daten, True


@app.get("/vorlagen/{vorlage_id}", response_class=HTMLResponse)
def vorlage_chat_editor(vorlage_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    schema, geaendert = _pflichtfelder_initial_optional(eintrag.schema)
    if geaendert:
        eintrag.schema = schema
        eintrag.erkannte_felder = len(schema.get("felder", []))
        db.commit()
    dialoge = db.scalars(
        select(Vorlagendialog)
        .where(Vorlagendialog.vorlage_id == eintrag.id)
        .order_by(Vorlagendialog.erstellt_am)
    ).all()
    kontext = grundkontext(request, db, "vorlagen")
    kontext.update({"eintrag": eintrag, "dialoge": dialoge})
    return vorlagen.TemplateResponse("vorlage_detail.html", kontext)


def _png_aus_pdf(pfad: Path, seite: int) -> bytes:
    dokument = fitz.open(pfad)
    try:
        if seite < 1 or seite > len(dokument):
            raise HTTPException(status_code=404, detail="Diese Dokumentseite ist nicht vorhanden.")
        pdf_seite = dokument.load_page(seite - 1)
        pixmap = pdf_seite.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False)
        return pixmap.tobytes("png")
    finally:
        dokument.close()


def _png_aus_bild(pfad: Path, seite: int) -> bytes:
    if seite != 1:
        raise HTTPException(status_code=404, detail="Diese Dokumentseite ist nicht vorhanden.")
    with Image.open(pfad) as original:
        bild = ImageOps.exif_transpose(original).convert("RGB")
        bild.thumbnail((1500, 2100))
        speicher = io.BytesIO()
        bild.save(speicher, format="PNG", optimize=True)
        return speicher.getvalue()


@app.get("/vorlagen/{vorlage_id}/seiten/{seite}.png")
def vorlage_seite_als_bild(vorlage_id: int, seite: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        raise HTTPException(status_code=401, detail="Bitte melden Sie sich zuerst an.")
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    pfad = Path(eintrag.speicherort)
    if not pfad.exists():
        raise HTTPException(status_code=404, detail="Die Originaldatei ist nicht mehr verfügbar.")
    if pfad.suffix.lower() == ".pdf" or eintrag.inhaltstyp == "application/pdf":
        inhalt = _png_aus_pdf(pfad, seite)
    else:
        inhalt = _png_aus_bild(pfad, seite)
    return Response(
        content=inhalt,
        media_type="image/png",
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


# Der bestehende Renderer wird an einer Stelle präziser gemacht, ohne alle Aufrufer
# umzubauen: Löschen und Schreiben erhalten getrennte Rechtecke.
from . import pdf_engine as _pdf_engine  # noqa: E402


def _exakter_treffer(seite: fitz.Page, feld: dict[str, Any], schaetzung: fitz.Rect) -> fitz.Rect | None:
    treffer: list[fitz.Rect] = []
    for suchtext in _pdf_engine._suchtext_varianten(feld.get("beispiel")):
        try:
            treffer.extend(seite.search_for(suchtext, quads=False))
        except Exception:
            continue
        if treffer:
            break
    if not treffer:
        return None
    mitte = fitz.Point((schaetzung.x0 + schaetzung.x1) / 2, (schaetzung.y0 + schaetzung.y1) / 2)
    return min(
        treffer,
        key=lambda rect: ((rect.x0 + rect.x1) / 2 - mitte.x) ** 2 + ((rect.y0 + rect.y1) / 2 - mitte.y) ** 2,
    )


def _felder_auf_seite_rendern_v2(seite: fitz.Page, felder: list[dict[str, Any]], eingaben: dict[str, Any]) -> None:
    operationen: list[tuple[dict[str, Any], Any, fitz.Rect, fitz.Rect | None]] = []
    for feld in felder:
        schluessel = str(feld.get("schluessel") or "")
        wert = eingaben.get(schluessel)
        if wert in (None, "", []):
            continue
        schaetzung = _pdf_engine._normalisiertes_rechteck(seite, feld)
        treffer = _exakter_treffer(seite, feld, schaetzung)
        if treffer is not None:
            render_rechteck = fitz.Rect(
                treffer.x0,
                min(treffer.y0, schaetzung.y0),
                min(seite.rect.width, max(treffer.x1 + 2, treffer.x0 + schaetzung.width)),
                min(seite.rect.height, max(treffer.y1 + 2, treffer.y0 + schaetzung.height)),
            )
        else:
            render_rechteck = schaetzung
        entfernen = bool(feld.get("alten_inhalt_entfernen", bool(str(feld.get("beispiel") or "").strip())))
        loesch_rechteck = None
        if entfernen and treffer is not None:
            loesch_rechteck = fitz.Rect(
                max(0, treffer.x0 - 1.25),
                max(0, treffer.y0 - 1.25),
                min(seite.rect.width, treffer.x1 + 1.25),
                min(seite.rect.height, treffer.y1 + 1.25),
            )
            farbe = _pdf_engine._hintergrundfarbe(seite, loesch_rechteck)
            seite.add_redact_annot(loesch_rechteck, fill=farbe, cross_out=False)
        operationen.append((feld, wert, render_rechteck, loesch_rechteck))

    if any(loesch is not None for _, _, _, loesch in operationen):
        try:
            seite.apply_redactions(images=0, graphics=0, text=0)
        except TypeError:
            seite.apply_redactions(images=0)

    for feld, wert, rechteck, _ in operationen:
        feldtyp = str(feld.get("typ") or "text")
        if feldtyp in {"bild", "unterschrift"}:
            pfad = Path(str(wert))
            if not pfad.exists():
                raise _pdf_engine.RenderingFehler(
                    f"Die Datei für „{feld.get('bezeichnung') or feld.get('schluessel')}“ ist nicht verfügbar."
                )
            try:
                bilddaten = _pdf_engine._bild_als_bytes(pfad, signatur=feldtyp == "unterschrift")
                seite.insert_image(rechteck, stream=bilddaten, keep_proportion=True, overlay=True)
            except Exception as exc:
                raise _pdf_engine.RenderingFehler(
                    f"Das Bild für „{feld.get('bezeichnung') or feld.get('schluessel')}“ konnte nicht verarbeitet werden."
                ) from exc
        else:
            _pdf_engine._text_einfuegen(seite, rechteck, wert, feld)


_pdf_engine._felder_auf_seite_rendern = _felder_auf_seite_rendern_v2


__all__ = ["app", "_pflichtfelder_initial_optional"]
