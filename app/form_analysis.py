from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

from .local_analysis import (
    formular_lokal_analysieren as _struktur_analysieren,
    schema_kombinieren,
)


def _position(rect: fitz.Rect, seite: fitz.Page) -> dict[str, float]:
    breite = max(1.0, float(seite.rect.width))
    hoehe = max(1.0, float(seite.rect.height))
    x = max(0.0, min(0.99, rect.x0 / breite))
    y = max(0.0, min(0.99, rect.y0 / hoehe))
    return {
        "x": round(x, 5),
        "y": round(y, 5),
        "breite": round(max(0.02, min(1.0 - x, rect.width / breite)), 5),
        "hoehe": round(max(0.015, min(1.0 - y, rect.height / hoehe)), 5),
    }


def _sichtbare_textkandidaten(dateipfad: Path, dateiname: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Für sehr einfache PDFs: nur tatsächlich sichtbare kurze Textbereiche anbieten.

    Das ist ausdrücklich kein allgemeines Ersatzschema. Es werden ausschließlich
    Textobjekte mit ihrer echten Position und ihrem echten Beispielwert übernommen.
    Umfangreiche Dokumente ohne Formularstruktur bleiben dagegen im Fehlerstatus.
    """
    if dateipfad.suffix.lower() != ".pdf":
        return None

    dokument = fitz.open(dateipfad)
    felder: list[dict[str, Any]] = []
    try:
        alle_zeilen: list[tuple[int, fitz.Page, str, fitz.Rect, float]] = []
        for seitenindex, seite in enumerate(dokument):
            for block in seite.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for zeile in block.get("lines", []):
                    texte: list[str] = []
                    groessen: list[float] = []
                    rect: fitz.Rect | None = None
                    for span in zeile.get("spans", []):
                        text = str(span.get("text", "")).strip()
                        if not text:
                            continue
                        texte.append(text)
                        groessen.append(float(span.get("size", 0) or 0))
                        span_rect = fitz.Rect(span.get("bbox", (0, 0, 0, 0)))
                        rect = span_rect if rect is None else rect | span_rect
                    if texte and rect is not None:
                        alle_zeilen.append((seitenindex + 1, seite, " ".join(texte), rect, max(groessen or [0])))

        # Nur sehr kleine, überschaubare Dokumente dürfen diesen Modus verwenden.
        # Bei Verträgen oder Fließtexten wäre jeder automatisch erzeugte Textkandidat irreführend.
        geeignete = [
            eintrag
            for eintrag in alle_zeilen
            if 2 <= len(eintrag[2].strip()) <= 100 and eintrag[4] <= 18
        ]
        if not geeignete or len(geeignete) > 5:
            return None

        for index, (seitenzahl, seite, text, rect, schriftgroesse) in enumerate(geeignete, start=1):
            felder.append(
                {
                    "schluessel": f"sichtbarer_text_{index}",
                    "bezeichnung": text,
                    "typ": "text",
                    "pflichtfeld": False,
                    "beispiel": text,
                    "seite": seitenzahl,
                    "hinweis": "Direkt sichtbarer Textbereich des Original-PDFs; bitte als variabel bestätigen oder entfernen.",
                    "optionen": [],
                    "position": _position(rect, seite),
                    "schriftgroesse": max(7, min(14, round(schriftgroesse))),
                    "ausrichtung": "links",
                    "hintergrundmodus": "automatisch",
                    "erkennungsquelle": "pdf-textkandidat",
                }
            )
    finally:
        dokument.close()

    schema = {
        "dokumentart": Path(dateiname).stem.replace("_", " ").replace("-", " ").strip() or "Dokumentvorlage",
        "zusammenfassung": f"{len(felder)} tatsächlich sichtbare Textbereiche wurden als prüfpflichtige Kandidaten übernommen.",
        "felder": felder,
        "rueckfragen": ["Welche dieser sichtbaren Texte sollen bei der Wiederverwendung veränderlich sein?"],
        "analysequelle": "pdf-textkandidaten",
        "analysequalitaet": {"erkannte_felder": len(felder), "pruefung_erforderlich": True},
    }
    return schema, {"felder": len(felder), "quelle": "pdf-textkandidaten", "pruefung_erforderlich": True}


def formular_lokal_analysieren(dateipfad: Path, dateiname: str) -> tuple[dict[str, Any], dict[str, Any]]:
    schema, diagnostik = _struktur_analysieren(dateipfad, dateiname)
    if list(schema.get("felder", []) or []):
        return schema, diagnostik

    textkandidaten = _sichtbare_textkandidaten(dateipfad, dateiname)
    if textkandidaten is not None:
        return textkandidaten
    return schema, diagnostik


__all__ = ["formular_lokal_analysieren", "schema_kombinieren"]
