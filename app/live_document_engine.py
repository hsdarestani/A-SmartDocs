from __future__ import annotations

import copy
import io
import math
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Any

import fitz

from .pdf_engine import _hintergrundfarbe


class LiveBearbeitungsFehler(ValueError):
    pass


def _norm(text: Any) -> str:
    wert = unicodedata.normalize("NFKD", str(text or "").lower())
    wert = "".join(zeichen for zeichen in wert if not unicodedata.combining(zeichen))
    wert = wert.replace("ß", "ss")
    wert = re.sub(r"[^a-z0-9]+", " ", wert)
    return re.sub(r"\s+", " ", wert).strip()


def _farbe_aus_int(wert: Any) -> tuple[float, float, float]:
    try:
        zahl = int(wert or 0)
    except (TypeError, ValueError):
        zahl = 0
    return (
        ((zahl >> 16) & 255) / 255,
        ((zahl >> 8) & 255) / 255,
        (zahl & 255) / 255,
    )


def _normalisierte_bbox(rect: fitz.Rect, seite: fitz.Page) -> dict[str, float]:
    breite = max(1.0, float(seite.rect.width))
    hoehe = max(1.0, float(seite.rect.height))
    return {
        "x": round(rect.x0 / breite, 6),
        "y": round(rect.y0 / hoehe, 6),
        "breite": round(rect.width / breite, 6),
        "hoehe": round(rect.height / hoehe, 6),
    }


def pdf_index(dateipfad: Path, maximale_anker: int = 1200) -> dict[str, Any]:
    """Extrahiert klickbare Textanker direkt aus dem PDF, ohne KI-Koordinaten."""
    dokument = fitz.open(dateipfad)
    seiten: list[dict[str, Any]] = []
    gesamter_text: list[str] = []
    anzahl = 0
    try:
        for seitenindex, seite in enumerate(dokument, start=1):
            anker: list[dict[str, Any]] = []
            daten = seite.get_text("dict")
            for block_index, block in enumerate(daten.get("blocks", [])):
                if block.get("type") != 0:
                    continue
                for line_index, line in enumerate(block.get("lines", [])):
                    spans = [span for span in line.get("spans", []) if str(span.get("text") or "").strip()]
                    for span_index, span in enumerate(spans):
                        if anzahl >= maximale_anker:
                            break
                        text = str(span.get("text") or "").strip()
                        if not text:
                            continue
                        rect = fitz.Rect(span.get("bbox", (0, 0, 0, 0)))
                        if rect.width <= 1 or rect.height <= 1:
                            continue
                        naechster_x = seite.rect.width - 24
                        if span_index + 1 < len(spans):
                            naechster_rect = fitz.Rect(spans[span_index + 1].get("bbox", (seite.rect.width, 0, seite.rect.width, 0)))
                            if abs(naechster_rect.y0 - rect.y0) <= max(4, rect.height * 0.65) and naechster_rect.x0 > rect.x1:
                                naechster_x = max(rect.x1 + 2, naechster_rect.x0 - 2)
                        origin = span.get("origin") or (rect.x0, rect.y1 - 2)
                        anker_id = f"p{seitenindex}-b{block_index}-l{line_index}-s{span_index}"
                        anker.append(
                            {
                                "id": anker_id,
                                "seite": seitenindex,
                                "text": text,
                                "bbox": [round(rect.x0, 3), round(rect.y0, 3), round(rect.x1, 3), round(rect.y1, 3)],
                                "position": _normalisierte_bbox(rect, seite),
                                "schriftgroesse": round(float(span.get("size") or 10), 2),
                                "farbe": int(span.get("color") or 0),
                                "origin": [round(float(origin[0]), 3), round(float(origin[1]), 3)],
                                "write_x1": round(float(naechster_x), 3),
                            }
                        )
                        gesamter_text.append(text)
                        anzahl += 1
                    if anzahl >= maximale_anker:
                        break
                if anzahl >= maximale_anker:
                    break
            seiten.append(
                {
                    "seite": seitenindex,
                    "breite": round(float(seite.rect.width), 3),
                    "hoehe": round(float(seite.rect.height), 3),
                    "anker": anker,
                }
            )
    finally:
        dokument.close()
    return {"seiten": seiten, "text": "\n".join(gesamter_text), "anzahl": anzahl}


def anker_nach_id(index: dict[str, Any], anker_id: str) -> dict[str, Any] | None:
    for seite in index.get("seiten", []):
        for anker in seite.get("anker", []):
            if anker.get("id") == anker_id:
                return copy.deepcopy(anker)
    return None


def _alle_anker(index: dict[str, Any]) -> list[dict[str, Any]]:
    return [anker for seite in index.get("seiten", []) for anker in seite.get("anker", [])]


def _anker_fuer_text(index: dict[str, Any], text: str, seite: int | None = None) -> dict[str, Any] | None:
    gesucht = _norm(text)
    if not gesucht:
        return None
    kandidaten = [anker for anker in _alle_anker(index) if seite is None or int(anker.get("seite") or 0) == seite]
    exakt = [anker for anker in kandidaten if _norm(anker.get("text")) == gesucht]
    if exakt:
        return copy.deepcopy(exakt[0])
    enthalten = [anker for anker in kandidaten if gesucht in _norm(anker.get("text"))]
    if enthalten:
        enthalten.sort(key=lambda anker: len(str(anker.get("text") or "")))
        return copy.deepcopy(enthalten[0])
    return None


_SYNONYME = {
    "employee": "arbeitnehmer",
    "worker": "arbeitnehmer",
    "mitarbeiter": "arbeitnehmer",
    "employer": "arbeitgeber",
    "company": "arbeitgeber",
    "firm": "arbeitgeber",
    "companyname": "firmenname",
    "firmname": "firmenname",
    "address": "anschrift",
    "adresse": "anschrift",
    "street": "anschrift",
    "strasse": "anschrift",
    "name": "name",
    "date": "datum",
    "signature": "unterschrift",
    "signatur": "unterschrift",
}


def _tokens(text: Any) -> set[str]:
    stop = {"der", "die", "das", "den", "dem", "des", "ein", "eine", "von", "fur", "the", "of", "field", "feld"}
    return {_SYNONYME.get(token, token) for token in _norm(text).split() if token and token not in stop}


def _hinweis_treffer(hinweise: list[dict[str, Any]], ziel: str) -> dict[str, Any] | None:
    gesucht = _tokens(ziel)
    if not gesucht:
        return None
    kandidaten: list[tuple[float, dict[str, Any]]] = []
    for hinweis in hinweise:
        text = " ".join(str(hinweis.get(key) or "") for key in ("bezeichnung", "schluessel", "hinweis"))
        vorhanden = _tokens(text)
        if not vorhanden:
            continue
        gemeinsam = len(gesucht & vorhanden)
        score = gemeinsam / max(1, len(gesucht | vorhanden))
        if "arbeitnehmer" in gesucht and "arbeitnehmer" not in vorhanden:
            continue
        if "arbeitgeber" in gesucht and "arbeitgeber" not in vorhanden:
            continue
        if "anschrift" in gesucht and "anschrift" not in vorhanden:
            continue
        if "name" in gesucht and "anschrift" in vorhanden:
            score -= 0.25
        if "anschrift" in gesucht and "name" in vorhanden and "anschrift" not in vorhanden:
            continue
        kandidaten.append((score, hinweis))
    kandidaten.sort(key=lambda eintrag: eintrag[0], reverse=True)
    if not kandidaten or kandidaten[0][0] < 0.22:
        return None
    if len(kandidaten) > 1 and kandidaten[0][0] - kandidaten[1][0] < 0.08:
        return None
    return copy.deepcopy(kandidaten[0][1])


def ziel_aufloesen(
    index: dict[str, Any],
    zustand: dict[str, Any],
    ziel: str,
    anker_id: str | None = None,
) -> dict[str, Any] | None:
    if anker_id:
        return anker_nach_id(index, anker_id)

    direkt = _anker_fuer_text(index, ziel)
    if direkt:
        return direkt

    hinweis = _hinweis_treffer(list(zustand.get("hinweise") or []), ziel)
    if hinweis:
        beispiel = str(hinweis.get("beispiel") or "").strip()
        seite = int(hinweis.get("seite") or 0) or None
        if beispiel:
            anker = _anker_fuer_text(index, beispiel, seite=seite)
            if anker:
                anker["feldbezeichnung"] = hinweis.get("bezeichnung") or ziel
                return anker
    return None


def lokale_anweisung(nachricht: str) -> dict[str, str] | None:
    """Parst häufige Ersetzungsbefehle ohne Netzwerk- oder KI-Aufruf."""
    text = str(nachricht or "").strip()
    if not text:
        return None
    muster = [
        r"^\s*[„\"']?(.+?)[”\"']?\s*(?:→|->|=>)\s*[„\"']?(.+?)[”\"']?\s*$",
        r"^\s*(?:ersetze|ersetz|replace)\s+[„\"']?(.+?)[”\"']?\s+(?:durch|mit|with)\s+[„\"']?(.+?)[”\"']?\s*$",
        r"^\s*(?:ändere|aendere|change)\s+[„\"']?(.+?)[”\"']?\s+(?:auf|zu|in|to)\s+[„\"']?(.+?)[”\"']?\s*$",
        r"^\s*[„\"']?(.+?)[”\"']?\s+(?:ist|is|=|soll(?:te)?\s+sein)\s+[„\"']?(.+?)[”\"']?\s*[.!]?\s*$",
    ]
    for muster_text in muster:
        treffer = re.match(muster_text, text, flags=re.IGNORECASE)
        if treffer:
            ziel = treffer.group(1).strip(" \t\"'„”")
            wert = treffer.group(2).strip(" \t\"'„”")
            if ziel:
                return {"aktion": "ersetzen", "ziel": ziel, "wert": wert}

    entfernen = re.match(r"^\s*(?:entferne|lösche|losche|remove|delete)\s+[„\"']?(.+?)[”\"']?\s*[.!]?\s*$", text, flags=re.IGNORECASE)
    if entfernen:
        return {"aktion": "ersetzen", "ziel": entfernen.group(1).strip(" \t\"'„”"), "wert": ""}
    return None


def _edit_rect(anker: dict[str, Any]) -> fitz.Rect:
    bbox = anker.get("bbox") or [0, 0, 0, 0]
    return fitz.Rect(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))


def edit_aus_anker(anker: dict[str, Any], wert: str, quelle: str = "chat", ziel: str = "") -> dict[str, Any]:
    rect = _edit_rect(anker)
    return {
        "id": uuid.uuid4().hex,
        "anker_id": str(anker.get("id") or ""),
        "seite": int(anker.get("seite") or 1),
        "alter_text": str(anker.get("text") or ""),
        "neuer_text": str(wert or ""),
        "ziel": ziel or str(anker.get("feldbezeichnung") or anker.get("text") or ""),
        "bbox": [round(rect.x0, 3), round(rect.y0, 3), round(rect.x1, 3), round(rect.y1, 3)],
        "origin": list(anker.get("origin") or [rect.x0, rect.y1 - 2]),
        "write_x1": float(anker.get("write_x1") or rect.x1),
        "schriftgroesse": float(anker.get("schriftgroesse") or 10),
        "farbe": int(anker.get("farbe") or 0),
        "quelle": quelle,
    }


def _schnittquote(a: list[float], b: list[float]) -> float:
    ar = fitz.Rect(*a)
    br = fitz.Rect(*b)
    schnitt = ar & br
    if schnitt.is_empty:
        return 0.0
    basis = max(1.0, min(ar.get_area(), br.get_area()))
    return schnitt.get_area() / basis


def edit_speichern(zustand: dict[str, Any] | None, edit: dict[str, Any]) -> dict[str, Any]:
    daten = copy.deepcopy(zustand or {})
    edits = list(daten.get("edits") or [])
    ersetzt = False
    for index, alt in enumerate(edits):
        gleich = bool(edit.get("anker_id") and alt.get("anker_id") == edit.get("anker_id"))
        ueberlappt = int(alt.get("seite") or 0) == int(edit.get("seite") or 0) and _schnittquote(list(alt.get("bbox") or [0, 0, 0, 0]), list(edit.get("bbox") or [0, 0, 0, 0])) >= 0.75
        if gleich or ueberlappt:
            edit["id"] = alt.get("id") or edit["id"]
            edits[index] = edit
            ersetzt = True
            break
    if not ersetzt:
        edits.append(edit)
    daten["edits"] = edits
    daten["revision"] = int(daten.get("revision") or 0) + 1
    daten["version"] = max(2, int(daten.get("version") or 0))
    return daten


def letztes_edit_entfernen(zustand: dict[str, Any] | None) -> dict[str, Any]:
    daten = copy.deepcopy(zustand or {})
    edits = list(daten.get("edits") or [])
    if edits:
        edits.pop()
    daten["edits"] = edits
    daten["revision"] = int(daten.get("revision") or 0) + 1
    return daten


def _schriftgroesse_fuer_breite(text: str, groesse: float, breite: float) -> float:
    if not text:
        return groesse
    groesse = max(6.0, min(32.0, float(groesse or 10)))
    try:
        textbreite = fitz.get_text_length(text, fontname="helv", fontsize=groesse)
    except Exception:
        textbreite = len(text) * groesse * 0.52
    if textbreite <= breite:
        return groesse
    faktor = breite / max(1.0, textbreite)
    return max(6.0, groesse * faktor * 0.96)


def _ersatz_einfuegen(seite: fitz.Page, edit: dict[str, Any]) -> None:
    text = str(edit.get("neuer_text") or "")
    if not text:
        return
    rect = fitz.Rect(*(edit.get("bbox") or [0, 0, 0, 0]))
    write_x1 = max(rect.x1, min(float(edit.get("write_x1") or rect.x1), seite.rect.width - 12))
    breite = max(rect.width, write_x1 - rect.x0)
    groesse = _schriftgroesse_fuer_breite(text, float(edit.get("schriftgroesse") or 10), breite)
    farbe = _farbe_aus_int(edit.get("farbe"))
    origin = edit.get("origin") or [rect.x0, rect.y1 - 1]
    x = max(0, float(origin[0]))
    baseline = float(origin[1])
    # Die Grundlinie des ursprünglichen Textes ist stabiler als ein geschätztes Feldrechteck.
    try:
        seite.insert_text(
            fitz.Point(x, baseline),
            text[:600],
            fontname="helv",
            fontsize=groesse,
            color=farbe,
            overlay=True,
        )
    except Exception:
        ziel = fitz.Rect(rect.x0, rect.y0 - 1, max(rect.x1, write_x1), rect.y1 + max(3, rect.height * 0.35))
        seite.insert_textbox(ziel, text[:600], fontname="helv", fontsize=groesse, color=farbe, overlay=True)


def _seite_bearbeiten(seite: fitz.Page, edits: list[dict[str, Any]]) -> None:
    operationen: list[tuple[dict[str, Any], fitz.Rect]] = []
    for edit in edits:
        rect = fitz.Rect(*(edit.get("bbox") or [0, 0, 0, 0]))
        if rect.is_empty or rect.width <= 0 or rect.height <= 0:
            continue
        loeschrect = fitz.Rect(
            max(0, rect.x0 - 1.6),
            max(0, rect.y0 - 1.4),
            min(seite.rect.width, rect.x1 + 1.8),
            min(seite.rect.height, rect.y1 + 1.5),
        )
        hintergrund = _hintergrundfarbe(seite, loeschrect)
        seite.add_redact_annot(loeschrect, fill=hintergrund, cross_out=False)
        operationen.append((edit, rect))

    if operationen:
        try:
            seite.apply_redactions(images=0, graphics=0, text=0)
        except TypeError:
            seite.apply_redactions(images=0)

    for edit, _ in operationen:
        _ersatz_einfuegen(seite, edit)


def bearbeitetes_dokument(dateipfad: Path, zustand: dict[str, Any] | None) -> fitz.Document:
    dokument = fitz.open(dateipfad)
    edits = list((zustand or {}).get("edits") or [])
    nach_seite: dict[int, list[dict[str, Any]]] = {}
    for edit in edits:
        nach_seite.setdefault(max(1, int(edit.get("seite") or 1)), []).append(edit)
    for seitenzahl, seiten_edits in nach_seite.items():
        if 1 <= seitenzahl <= len(dokument):
            _seite_bearbeiten(dokument[seitenzahl - 1], seiten_edits)
    return dokument


def seite_als_png(dateipfad: Path, zustand: dict[str, Any] | None, seitenzahl: int, faktor: float = 1.8) -> bytes:
    dokument = bearbeitetes_dokument(dateipfad, zustand)
    try:
        if seitenzahl < 1 or seitenzahl > len(dokument):
            raise LiveBearbeitungsFehler("Diese Seite ist nicht vorhanden.")
        pixmap = dokument[seitenzahl - 1].get_pixmap(matrix=fitz.Matrix(faktor, faktor), alpha=False)
        return pixmap.tobytes("png")
    finally:
        dokument.close()


def pdf_exportieren(dateipfad: Path, zustand: dict[str, Any] | None, ziel: Path) -> int:
    dokument = bearbeitetes_dokument(dateipfad, zustand)
    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        dokument.save(ziel, garbage=4, deflate=True, clean=True)
        return len(dokument)
    finally:
        dokument.close()


def text_nach_bearbeitung(dateipfad: Path, zustand: dict[str, Any] | None) -> str:
    dokument = bearbeitetes_dokument(dateipfad, zustand)
    try:
        return "\n".join(seite.get_text("text") for seite in dokument)
    finally:
        dokument.close()


__all__ = [
    "LiveBearbeitungsFehler",
    "pdf_index",
    "anker_nach_id",
    "lokale_anweisung",
    "ziel_aufloesen",
    "edit_aus_anker",
    "edit_speichern",
    "letztes_edit_entfernen",
    "seite_als_png",
    "pdf_exportieren",
    "text_nach_bearbeitung",
]
