from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


VIOLETT = HexColor("#6F52ED")
DUNKEL = HexColor("#172033")
GRAU = HexColor("#68758A")
HELL = HexColor("#F3F5F9")


def _wert_als_text(wert: Any) -> str:
    if wert is None:
        return ""
    if isinstance(wert, bool):
        return "Ja" if wert else "Nein"
    if isinstance(wert, (list, dict)):
        return json.dumps(wert, ensure_ascii=False)
    return str(wert)


def _pflichtfelder_pruefen(schema: dict[str, Any], eingaben: dict[str, Any]) -> None:
    fehlend: list[str] = []
    felder = schema.get("felder", []) if isinstance(schema, dict) else []
    for feld in felder:
        if not bool(feld.get("pflichtfeld")):
            continue
        schluessel = str(feld.get("schluessel") or "").strip()
        if not schluessel:
            continue
        wert = eingaben.get(schluessel)
        leer = wert is None or wert == "" or wert == []
        if isinstance(wert, str):
            leer = not wert.strip()
        if leer:
            fehlend.append(str(feld.get("bezeichnung") or schluessel))
    if fehlend:
        raise ValueError("Bitte füllen Sie alle Pflichtfelder aus: " + ", ".join(fehlend))


def _text_einpassen(c: canvas.Canvas, text: str, x: float, y: float, breite: float, hoehe: float, schrift: float) -> None:
    text = text.strip()
    if not text:
        return
    groesse = max(6.0, min(schrift, hoehe * 0.55))
    while groesse > 6 and stringWidth(text, "Helvetica", groesse) > breite:
        groesse -= 0.5
    c.setFont("Helvetica", groesse)
    c.setFillColor(DUNKEL)
    c.drawString(x, y + max(1, (hoehe - groesse) / 2), text[:400])


def _positionswert(feld: dict[str, Any], schluessel: str, standard: float) -> float:
    position = feld.get("position") or {}
    try:
        wert = float(position.get(schluessel, standard))
    except (TypeError, ValueError):
        wert = standard
    return max(0.0, min(1.0, wert))


def _overlay_fuer_seite(seitenbreite: float, seitenhoehe: float, felder: list[dict[str, Any]], eingaben: dict[str, Any]) -> bytes:
    speicher = io.BytesIO()
    c = canvas.Canvas(speicher, pagesize=(seitenbreite, seitenhoehe))
    for feld in felder:
        schluessel = str(feld.get("schluessel", ""))
        wert = eingaben.get(schluessel)
        if wert in (None, "", []):
            continue
        x = _positionswert(feld, "x", 0.08) * seitenbreite
        y_oben = _positionswert(feld, "y", 0.12) * seitenhoehe
        breite = max(45, _positionswert(feld, "breite", 0.34) * seitenbreite)
        hoehe = max(16, _positionswert(feld, "hoehe", 0.035) * seitenhoehe)
        y = seitenhoehe - y_oben - hoehe
        typ = str(feld.get("typ", "text"))
        c.saveState()
        try:
            c.setFillAlpha(0.94)
        except AttributeError:
            pass
        c.setFillColor(white)
        c.roundRect(x - 2, y - 1, breite + 4, hoehe + 2, 2, fill=1, stroke=0)
        try:
            c.setFillAlpha(1)
        except AttributeError:
            pass
        if typ in {"bild", "unterschrift"} and isinstance(wert, str) and Path(wert).exists():
            try:
                c.drawImage(ImageReader(wert), x, y, width=breite, height=hoehe, preserveAspectRatio=True, anchor="c", mask="auto")
            except Exception:
                _text_einpassen(c, "[Bild]", x, y, breite, hoehe, 9)
        elif typ == "kontrollfeld":
            _text_einpassen(c, "✓" if str(wert).lower() in {"1", "true", "ja", "on"} else "", x, y, breite, hoehe, 12)
        else:
            _text_einpassen(c, _wert_als_text(wert), x, y, breite, hoehe, float(feld.get("schriftgroesse", 10) or 10))
        c.restoreState()
    c.save()
    speicher.seek(0)
    return speicher.read()


def _deckblatt(c: canvas.Canvas, titel: str, vorlagenname: str, eingaben: dict[str, Any], schema: dict[str, Any]) -> None:
    breite, hoehe = A4
    c.setFillColor(DUNKEL)
    c.rect(0, hoehe - 105, breite, 105, fill=1, stroke=0)
    c.setFillColor(VIOLETT)
    c.roundRect(42, hoehe - 76, 42, 42, 11, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(63, hoehe - 61, "A+")
    c.setFont("Helvetica-Bold", 20)
    c.drawString(98, hoehe - 53, "SmartDocs")
    c.setFont("Helvetica", 8)
    c.setFillColor(HexColor("#A8B3C6"))
    c.drawString(99, hoehe - 70, "AUTOMATISCH ERSTELLTES DOKUMENT")
    c.setFillColor(DUNKEL)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(42, hoehe - 154, titel)
    c.setFont("Helvetica", 10)
    c.setFillColor(GRAU)
    c.drawString(42, hoehe - 174, f"Vorlage: {vorlagenname}")
    y = hoehe - 220
    c.setFillColor(HELL)
    c.roundRect(42, 64, breite - 84, y - 30, 14, fill=1, stroke=0)
    c.setFillColor(DUNKEL)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(62, y - 2, "Eingegebene Informationen")
    y -= 28
    feld_index = {str(f.get("schluessel")): f for f in schema.get("felder", [])}
    for schluessel, wert in eingaben.items():
        if not wert or schluessel.startswith("_"):
            continue
        feld = feld_index.get(schluessel, {})
        bezeichnung = str(feld.get("bezeichnung") or schluessel.replace("_", " ").title())
        text = _wert_als_text(wert)
        if len(text) > 95:
            text = text[:92] + "…"
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(GRAU)
        c.drawString(62, y, bezeichnung.upper())
        c.setFont("Helvetica", 10)
        c.setFillColor(DUNKEL)
        c.drawString(220, y, text)
        y -= 24
        if y < 88:
            break
    c.setFont("Helvetica", 7)
    c.setFillColor(GRAU)
    c.drawString(42, 38, "Erstellt mit A+ SmartDocs · smartdocs.aplus-solution.de")


def dokument_erzeugen(original: Path, inhaltstyp: str, schema: dict[str, Any], eingaben: dict[str, Any], ziel: Path, titel: str, vorlagenname: str) -> int:
    _pflichtfelder_pruefen(schema, eingaben)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    if inhaltstyp == "application/pdf" and original.exists():
        leser = PdfReader(str(original))
        schreiber = PdfWriter()
        felder = schema.get("felder", []) if isinstance(schema, dict) else []
        for index, seite in enumerate(leser.pages, start=1):
            breite = float(seite.mediabox.width)
            hoehe = float(seite.mediabox.height)
            seitenfelder = [f for f in felder if int(f.get("seite", 1) or 1) == index]
            if seitenfelder:
                overlay = PdfReader(io.BytesIO(_overlay_fuer_seite(breite, hoehe, seitenfelder, eingaben))).pages[0]
                seite.merge_page(overlay)
            schreiber.add_page(seite)
        if not leser.pages:
            return _eigenstaendiges_pdf(schema, eingaben, ziel, titel, vorlagenname)
        with ziel.open("wb") as datei:
            schreiber.write(datei)
        return len(leser.pages)

    if inhaltstyp.startswith("image/") and original.exists():
        bild = Image.open(original).convert("RGB")
        breite, hoehe = A4
        speicher = io.BytesIO()
        c = canvas.Canvas(speicher, pagesize=A4)
        c.drawImage(ImageReader(bild), 0, 0, width=breite, height=hoehe, preserveAspectRatio=True, anchor="c")
        c.save()
        speicher.seek(0)
        basis = PdfReader(speicher)
        seite = basis.pages[0]
        felder = schema.get("felder", []) if isinstance(schema, dict) else []
        overlay = PdfReader(io.BytesIO(_overlay_fuer_seite(breite, hoehe, felder, eingaben))).pages[0]
        seite.merge_page(overlay)
        schreiber = PdfWriter()
        schreiber.add_page(seite)
        with ziel.open("wb") as datei:
            schreiber.write(datei)
        return 1

    return _eigenstaendiges_pdf(schema, eingaben, ziel, titel, vorlagenname)


def _eigenstaendiges_pdf(schema: dict[str, Any], eingaben: dict[str, Any], ziel: Path, titel: str, vorlagenname: str) -> int:
    c = canvas.Canvas(str(ziel), pagesize=A4)
    _deckblatt(c, titel, vorlagenname, eingaben, schema)
    c.save()
    return 1
