from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import fitz

from . import live_document_engine as _engine
from . import live_workspace as _workspace
from . import partial_line_editing as _partial
from . import workspace_interaction_v2 as _interaction


_WORT_INDEX = _partial.pdf_index_auf_wortebene


def _phrasen_alias(seite: fitz.Page, seitenzahl: int, block: int, zeile: int, span_index: int, span: dict[str, Any]):
    text = str(span.get("text") or "").strip()
    rect = fitz.Rect(span.get("bbox", (0, 0, 0, 0)))
    if not text or rect.is_empty or rect.width <= 1 or rect.height <= 1:
        return None
    origin = span.get("origin") or (rect.x0, rect.y1 - 2)
    return {
        "id": f"legacy-p{seitenzahl}-b{block}-l{zeile}-s{span_index}",
        "seite": seitenzahl,
        "text": text,
        "bbox": [round(rect.x0, 3), round(rect.y0, 3), round(rect.x1, 3), round(rect.y1, 3)],
        "position": _partial._normalisierte_bbox(rect, seite),
        "schriftgroesse": round(float(span.get("size") or 10), 2),
        "farbe": int(span.get("color") or 0),
        "origin": [round(float(origin[0]), 3), round(float(origin[1]), 3)],
        "write_x1": round(float(rect.x1), 3),
        "block": int(block),
        "zeile": int(zeile),
        "wort": -1,
        "linien_id": f"p{seitenzahl}-b{block}-l{zeile}",
        "klickbar": False,
        "alias_typ": "phrase",
    }


def pdf_index_mit_phrasen(dateipfad: Path, maximale_anker: int = 3000) -> dict[str, Any]:
    index = _WORT_INDEX(dateipfad, maximale_anker=maximale_anker)
    dokument = fitz.open(dateipfad)
    try:
        for seitenzahl, seite in enumerate(dokument, start=1):
            aliases: list[dict[str, Any]] = []
            daten = seite.get_text("dict")
            for block_index, block in enumerate(daten.get("blocks", [])):
                if block.get("type") != 0:
                    continue
                for line_index, line in enumerate(block.get("lines", [])):
                    for span_index, span in enumerate(line.get("spans", [])):
                        alias = _phrasen_alias(seite, seitenzahl, block_index, line_index, span_index, span)
                        if alias:
                            aliases.append(alias)
            index["seiten"][seitenzahl - 1]["anker"].extend(aliases)
    finally:
        dokument.close()
    index["anker_ebene"] = "wort-mit-phrasenalias"
    return index


def ziel_aufloesen_mit_phrasen(index: dict[str, Any], zustand: dict[str, Any], ziel: str, anker_id: str | None = None):
    if anker_id:
        return _partial.ankergruppe_nach_ids(index, anker_id)

    phrase = _partial._phrasenanker(index, ziel)
    if phrase:
        return phrase

    hinweis = _engine._hinweis_treffer(list((zustand or {}).get("hinweise") or []), ziel)
    if hinweis:
        beispiel = str(hinweis.get("beispiel") or "").strip()
        seite = int(hinweis.get("seite") or 0) or None
        if beispiel:
            phrase = _partial._phrasenanker(index, beispiel, seite=seite)
            if phrase:
                phrase["feldbezeichnung"] = hinweis.get("bezeichnung") or ziel
                return phrase

    # Unsichtbare vollständige Span-Aliase erhalten die frühere API für Tests,
    # KI-Pläne und ältere gespeicherte Hinweise.
    gesucht = _engine._norm(ziel)
    if gesucht:
        aliases = [
            a
            for seite in index.get("seiten", [])
            for a in seite.get("anker", [])
            if a.get("klickbar") is False and gesucht in _engine._norm(a.get("text"))
        ]
        if aliases:
            aliases.sort(key=lambda a: len(str(a.get("text") or "")))
            return copy.deepcopy(aliases[0])

    return _partial._URSPRUNG_ZIEL_AUFLOESEN(index, zustand, ziel, anker_id=None)


def anker_auf_seite_mit_phrasen(index: dict[str, Any], text: str, seite: int | None = None):
    phrase = _partial._phrasenanker(index, text, seite=seite)
    if phrase:
        return phrase
    gesucht = _engine._norm(text)
    for seiteninfo in index.get("seiten", []):
        if seite is not None and int(seiteninfo.get("seite") or 0) != seite:
            continue
        for anker in seiteninfo.get("anker", []):
            if anker.get("klickbar") is False and gesucht and gesucht in _engine._norm(anker.get("text")):
                return copy.deepcopy(anker)
    return None


_engine.pdf_index = pdf_index_mit_phrasen
_engine.ziel_aufloesen = ziel_aufloesen_mit_phrasen

_workspace.pdf_index = pdf_index_mit_phrasen
_workspace.ziel_aufloesen = ziel_aufloesen_mit_phrasen
_workspace._anker_auf_seite = anker_auf_seite_mit_phrasen

_interaction.pdf_index = pdf_index_mit_phrasen
_interaction.ziel_aufloesen = ziel_aufloesen_mit_phrasen
_interaction._anker_auf_seite = anker_auf_seite_mit_phrasen


__all__ = ["pdf_index_mit_phrasen", "ziel_aufloesen_mit_phrasen"]
