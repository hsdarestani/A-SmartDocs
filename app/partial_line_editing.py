from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import fitz

from . import live_document_engine as _engine
from . import live_workspace as _workspace
from . import workspace_interaction_v2 as _interaction


_URSPRUNG_ZIEL_AUFLOESEN = _engine.ziel_aufloesen


def _normalisierte_bbox(rect: fitz.Rect, seite: fitz.Page) -> dict[str, float]:
    breite = max(1.0, float(seite.rect.width))
    hoehe = max(1.0, float(seite.rect.height))
    return {
        "x": round(rect.x0 / breite, 6),
        "y": round(rect.y0 / hoehe, 6),
        "breite": round(rect.width / breite, 6),
        "hoehe": round(rect.height / hoehe, 6),
    }


def _span_stil(seite: fitz.Page) -> list[dict[str, Any]]:
    stile: list[dict[str, Any]] = []
    for block in seite.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = str(span.get("text") or "").strip()
                rect = fitz.Rect(span.get("bbox", (0, 0, 0, 0)))
                if not text or rect.is_empty:
                    continue
                origin = span.get("origin") or (rect.x0, rect.y1 - 2)
                stile.append(
                    {
                        "rect": rect,
                        "schriftgroesse": float(span.get("size") or 10),
                        "farbe": int(span.get("color") or 0),
                        "baseline": float(origin[1]),
                    }
                )
    return stile


def _stil_fuer_wort(rect: fitz.Rect, stile: list[dict[str, Any]]) -> dict[str, Any]:
    bester: dict[str, Any] | None = None
    beste_flaeche = -1.0
    for stil in stile:
        schnitt = rect & stil["rect"]
        flaeche = 0.0 if schnitt.is_empty else float(schnitt.get_area())
        if flaeche > beste_flaeche:
            beste_flaeche = flaeche
            bester = stil
    return bester or {
        "schriftgroesse": max(7.0, min(18.0, rect.height * 0.82)),
        "farbe": 0,
        "baseline": rect.y1 - max(1.0, rect.height * 0.16),
    }


def pdf_index_auf_wortebene(dateipfad: Path, maximale_anker: int = 3000) -> dict[str, Any]:
    """Erzeugt klickbare Wortanker statt eines einzigen Ankers für einen ganzen Span."""
    dokument = fitz.open(dateipfad)
    seiten: list[dict[str, Any]] = []
    gesamter_text: list[str] = []
    anzahl = 0
    try:
        for seitenzahl, seite in enumerate(dokument, start=1):
            stile = _span_stil(seite)
            woerter = list(seite.get_text("words", sort=True) or [])
            anker: list[dict[str, Any]] = []
            for index, wort in enumerate(woerter):
                if anzahl >= maximale_anker or len(wort) < 8:
                    break
                x0, y0, x1, y1, text, block, zeile, wort_nr = wort[:8]
                text = str(text or "").strip()
                rect = fitz.Rect(float(x0), float(y0), float(x1), float(y1))
                if not text or rect.width <= 0.8 or rect.height <= 0.8:
                    continue
                stil = _stil_fuer_wort(rect, stile)
                naechster_x = float(seite.rect.width) - 24.0
                if index + 1 < len(woerter):
                    folgend = woerter[index + 1]
                    if int(folgend[5]) == int(block) and int(folgend[6]) == int(zeile):
                        naechster_x = max(rect.x1 + 0.7, float(folgend[0]) - 0.7)
                linien_id = f"p{seitenzahl}-b{int(block)}-l{int(zeile)}"
                anker_id = f"{linien_id}-w{int(wort_nr)}"
                anker.append(
                    {
                        "id": anker_id,
                        "seite": seitenzahl,
                        "text": text,
                        "bbox": [round(rect.x0, 3), round(rect.y0, 3), round(rect.x1, 3), round(rect.y1, 3)],
                        "position": _normalisierte_bbox(rect, seite),
                        "schriftgroesse": round(float(stil["schriftgroesse"]), 2),
                        "farbe": int(stil["farbe"]),
                        "origin": [round(rect.x0, 3), round(float(stil["baseline"]), 3)],
                        "write_x1": round(float(naechster_x), 3),
                        "block": int(block),
                        "zeile": int(zeile),
                        "wort": int(wort_nr),
                        "linien_id": linien_id,
                    }
                )
                gesamter_text.append(text)
                anzahl += 1
            seiten.append(
                {
                    "seite": seitenzahl,
                    "breite": round(float(seite.rect.width), 3),
                    "hoehe": round(float(seite.rect.height), 3),
                    "anker": anker,
                }
            )
    finally:
        dokument.close()
    return {"seiten": seiten, "text": " ".join(gesamter_text), "anzahl": anzahl, "anker_ebene": "wort"}


def _alle_anker(index: dict[str, Any]) -> list[dict[str, Any]]:
    return [anker for seite in index.get("seiten", []) for anker in seite.get("anker", [])]


def _anker_mit_id(index: dict[str, Any], anker_id: str) -> dict[str, Any] | None:
    return next((copy.deepcopy(a) for a in _alle_anker(index) if a.get("id") == anker_id), None)


def _text_verbinden(anker: list[dict[str, Any]]) -> str:
    text = ""
    ohne_leerzeichen_davor = re.compile(r"^[,.;:!?%\)\]\}»”’]$")
    ohne_leerzeichen_danach = re.compile(r"[\(\[\{«„‘]$")
    for eintrag in anker:
        wort = str(eintrag.get("text") or "")
        if not text:
            text = wort
        elif ohne_leerzeichen_davor.match(wort) or ohne_leerzeichen_danach.search(text):
            text += wort
        else:
            text += " " + wort
    return text


def ankergruppe_nach_ids(index: dict[str, Any], anker_id: str) -> dict[str, Any] | None:
    ids = [teil for teil in str(anker_id or "").split("|") if teil]
    if not ids:
        return None
    gefunden = [_anker_mit_id(index, einzel_id) for einzel_id in ids]
    if any(a is None for a in gefunden):
        return None
    anker = [a for a in gefunden if a is not None]
    erste = anker[0]
    if any(int(a.get("seite") or 0) != int(erste.get("seite") or 0) or a.get("linien_id") != erste.get("linien_id") for a in anker):
        return None

    linienanker = sorted(
        [
            a
            for a in _alle_anker(index)
            if int(a.get("seite") or 0) == int(erste.get("seite") or 0) and a.get("linien_id") == erste.get("linien_id")
        ],
        key=lambda a: int(a.get("wort") or 0),
    )
    positionen = {a.get("id"): i for i, a in enumerate(linienanker)}
    try:
        start = min(positionen[a.get("id")] for a in anker)
        ende = max(positionen[a.get("id")] for a in anker)
    except (KeyError, ValueError):
        return None
    gruppe = linienanker[start : ende + 1]
    rect = fitz.Rect(*(gruppe[0].get("bbox") or [0, 0, 0, 0]))
    for eintrag in gruppe[1:]:
        rect |= fitz.Rect(*(eintrag.get("bbox") or [0, 0, 0, 0]))
    erstes = gruppe[0]
    letztes = gruppe[-1]
    return {
        "id": "|".join(str(a.get("id")) for a in gruppe),
        "seite": int(erstes.get("seite") or 1),
        "text": _text_verbinden(gruppe),
        "bbox": [round(rect.x0, 3), round(rect.y0, 3), round(rect.x1, 3), round(rect.y1, 3)],
        "position": {
            "x": min(float(a.get("position", {}).get("x", 0)) for a in gruppe),
            "y": min(float(a.get("position", {}).get("y", 0)) for a in gruppe),
            "breite": max(float(a.get("position", {}).get("x", 0)) + float(a.get("position", {}).get("breite", 0)) for a in gruppe)
            - min(float(a.get("position", {}).get("x", 0)) for a in gruppe),
            "hoehe": max(float(a.get("position", {}).get("hoehe", 0)) for a in gruppe),
        },
        "schriftgroesse": float(erstes.get("schriftgroesse") or 10),
        "farbe": int(erstes.get("farbe") or 0),
        "origin": list(erstes.get("origin") or [rect.x0, rect.y1 - 2]),
        "write_x1": float(letztes.get("write_x1") or rect.x1),
        "block": erstes.get("block"),
        "zeile": erstes.get("zeile"),
        "linien_id": erstes.get("linien_id"),
        "wort_ids": [a.get("id") for a in gruppe],
    }


def _phrasenanker(index: dict[str, Any], text: str, seite: int | None = None) -> dict[str, Any] | None:
    gesucht = _engine._norm(text)
    if not gesucht:
        return None
    nach_linie: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for anker in _alle_anker(index):
        seitenzahl = int(anker.get("seite") or 0)
        if seite is not None and seitenzahl != seite:
            continue
        nach_linie.setdefault((seitenzahl, str(anker.get("linien_id") or "")), []).append(anker)
    for linienanker in nach_linie.values():
        linienanker.sort(key=lambda a: int(a.get("wort") or 0))
        for start in range(len(linienanker)):
            for ende in range(start, min(len(linienanker), start + 18)):
                kandidat = _text_verbinden(linienanker[start : ende + 1])
                normalisiert = _engine._norm(kandidat)
                if normalisiert == gesucht:
                    return ankergruppe_nach_ids(index, "|".join(str(a.get("id")) for a in linienanker[start : ende + 1]))
                if len(normalisiert) > len(gesucht) + 18:
                    break
    return None


def ziel_aufloesen_teilbereich(index: dict[str, Any], zustand: dict[str, Any], ziel: str, anker_id: str | None = None):
    if anker_id:
        return ankergruppe_nach_ids(index, anker_id)
    phrase = _phrasenanker(index, ziel)
    if phrase:
        return phrase
    return _URSPRUNG_ZIEL_AUFLOESEN(index, zustand, ziel, anker_id=None)


def anker_auf_seite_teilbereich(index: dict[str, Any], text: str, seite: int | None = None):
    return _phrasenanker(index, text, seite=seite)


# Alle bereits importierten Funktionsreferenzen werden bewusst aktualisiert. So
# verwenden UI, Chat, Preview und Export dieselbe Wort- und Phrasenlogik.
_engine.pdf_index = pdf_index_auf_wortebene
_engine.anker_nach_id = ankergruppe_nach_ids
_engine.ziel_aufloesen = ziel_aufloesen_teilbereich

_workspace.pdf_index = pdf_index_auf_wortebene
_workspace.anker_nach_id = ankergruppe_nach_ids
_workspace.ziel_aufloesen = ziel_aufloesen_teilbereich
_workspace._anker_auf_seite = anker_auf_seite_teilbereich

_interaction.pdf_index = pdf_index_auf_wortebene
_interaction.anker_nach_id = ankergruppe_nach_ids
_interaction.ziel_aufloesen = ziel_aufloesen_teilbereich
_interaction._anker_auf_seite = anker_auf_seite_teilbereich


__all__ = [
    "pdf_index_auf_wortebene",
    "ankergruppe_nach_ids",
    "ziel_aufloesen_teilbereich",
]
