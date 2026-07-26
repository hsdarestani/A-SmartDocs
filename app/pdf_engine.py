from __future__ import annotations

import io
import json
import re
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

import fitz
from PIL import Image, ImageOps
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# Starlette erzeugt bei request.form() standardmäßig seine eigene UploadFile-Klasse.
# Die Anwendung prüft gegen fastapi.UploadFile. Durch diese kompatible Zuordnung
# werden hochgeladene Bilder und Unterschriften zuverlässig als Dateien erkannt.
try:
    import starlette.formparsers as starlette_formparsers
    from fastapi import UploadFile as FastAPIUploadFile

    starlette_formparsers.UploadFile = FastAPIUploadFile
except Exception:
    pass

APPLUS_DUNKEL = HexColor("#071C2E")
APPLUS_BLAU = HexColor("#1676A7")
GRAU = HexColor("#68758A")
HELL = HexColor("#F3F7FA")


class RenderingFehler(ValueError):
    """Verständlicher Fehler für nicht verarbeitbare Dokumentfelder."""


def _wert_als_text(wert: Any, feldtyp: str = "text") -> str:
    if wert is None:
        return ""
    if isinstance(wert, bool):
        return "Ja" if wert else "Nein"
    if isinstance(wert, (list, dict)):
        return json.dumps(wert, ensure_ascii=False)
    text = str(wert).strip()
    if feldtyp == "datum" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return datetime.strptime(text, "%Y-%m-%d").strftime("%d.%m.%Y")
        except ValueError:
            return text
    return text


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
        raise RenderingFehler("Bitte füllen Sie alle Pflichtfelder aus: " + ", ".join(fehlend))


def _positionswert(feld: dict[str, Any], schluessel: str, standard: float) -> float:
    position = feld.get("position") or {}
    try:
        wert = float(position.get(schluessel, standard))
    except (TypeError, ValueError):
        wert = standard
    return max(0.0, min(1.0, wert))


def _normalisiertes_rechteck(seite: fitz.Page, feld: dict[str, Any]) -> fitz.Rect:
    seitenrechteck = seite.rect
    x = _positionswert(feld, "x", 0.08) * seitenrechteck.width
    y = _positionswert(feld, "y", 0.12) * seitenrechteck.height
    breite = max(22.0, _positionswert(feld, "breite", 0.34) * seitenrechteck.width)
    hoehe = max(11.0, _positionswert(feld, "hoehe", 0.035) * seitenrechteck.height)
    x = min(x, max(0.0, seitenrechteck.width - breite))
    y = min(y, max(0.0, seitenrechteck.height - hoehe))
    return fitz.Rect(x, y, x + breite, y + hoehe)


def _suchtext_varianten(beispiel: Any) -> list[str]:
    text = str(beispiel or "").strip()
    if not text or text in {"-", "–", "…", "..."}:
        return []
    varianten = [text]
    erste_zeile = next((zeile.strip() for zeile in text.splitlines() if zeile.strip()), "")
    if erste_zeile and erste_zeile not in varianten:
        varianten.append(erste_zeile)
    if len(text) > 72:
        kurz = text[:72].rsplit(" ", 1)[0].strip()
        if len(kurz) >= 12 and kurz not in varianten:
            varianten.append(kurz)
    return varianten


def _treffer_rechteck(seite: fitz.Page, feld: dict[str, Any], schaetzung: fitz.Rect) -> fitz.Rect | None:
    treffer: list[fitz.Rect] = []
    for suchtext in _suchtext_varianten(feld.get("beispiel")):
        try:
            treffer.extend(seite.search_for(suchtext, quads=False))
        except Exception:
            continue
        if treffer:
            break
    if not treffer:
        return None

    mitte = fitz.Point((schaetzung.x0 + schaetzung.x1) / 2, (schaetzung.y0 + schaetzung.y1) / 2)
    bester = min(
        treffer,
        key=lambda rect: ((rect.x0 + rect.x1) / 2 - mitte.x) ** 2 + ((rect.y0 + rect.y1) / 2 - mitte.y) ** 2,
    )
    # X/Y stammen aus dem tatsächlich gefundenen Beispielwert. Breite und Höhe
    # bleiben mindestens so groß wie die vom Vorlageneditor definierte Eingabefläche.
    breite = max(schaetzung.width, bester.width + 2)
    hoehe = max(schaetzung.height, bester.height + 2)
    return fitz.Rect(bester.x0, bester.y0 - 1, min(seite.rect.width, bester.x0 + breite), min(seite.rect.height, bester.y0 - 1 + hoehe))


def _pixel_median(werte: list[int], standard: int = 255) -> int:
    return int(median(werte)) if werte else standard


def _hintergrundfarbe(seite: fitz.Page, rechteck: fitz.Rect) -> tuple[float, float, float]:
    """Ermittelt die tatsächliche Dokumentfarbe am Rand des variablen Bereichs."""
    clip = fitz.Rect(
        max(0, rechteck.x0 - 4),
        max(0, rechteck.y0 - 4),
        min(seite.rect.width, rechteck.x1 + 4),
        min(seite.rect.height, rechteck.y1 + 4),
    )
    try:
        pix = seite.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, alpha=False)
        bild = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    except Exception:
        return (1.0, 1.0, 1.0)

    rand = max(2, min(8, min(bild.width, bild.height) // 5))
    pixel = bild.load()
    rot: list[int] = []
    gruen: list[int] = []
    blau: list[int] = []
    for y in range(bild.height):
        for x in range(bild.width):
            if x < rand or y < rand or x >= bild.width - rand or y >= bild.height - rand:
                r, g, b = pixel[x, y]
                # Sehr dunkle Schriftpixel sollen die Hintergrundschätzung nicht verfälschen.
                if max(r, g, b) - min(r, g, b) < 35 and r < 90:
                    continue
                rot.append(r)
                gruen.append(g)
                blau.append(b)
    return (_pixel_median(rot) / 255, _pixel_median(gruen) / 255, _pixel_median(blau) / 255)


def _hex_farbe(wert: Any, standard: tuple[float, float, float] = (0.035, 0.11, 0.18)) -> tuple[float, float, float]:
    text = str(wert or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", text):
        return tuple(int(text[index:index + 2], 16) / 255 for index in (0, 2, 4))
    return standard


def _signatur_als_png(pfad: Path) -> bytes:
    """Entfernt weiße Scan-/Foto-Flächen und behält die Unterschrift transparent."""
    with Image.open(pfad) as original:
        bild = ImageOps.exif_transpose(original).convert("RGBA")
        daten = list(bild.getdata())
        bereinigt = []
        for r, g, b, a in daten:
            helligkeit = min(r, g, b)
            farbabstand = max(r, g, b) - min(r, g, b)
            if helligkeit > 238 and farbabstand < 24:
                bereinigt.append((255, 255, 255, 0))
            else:
                bereinigt.append((r, g, b, a))
        bild.putdata(bereinigt)
        alpha = bild.getchannel("A")
        bbox = alpha.getbbox()
        if bbox:
            bild = bild.crop(bbox)
        speicher = io.BytesIO()
        bild.save(speicher, format="PNG", optimize=True)
        return speicher.getvalue()


def _bild_als_bytes(pfad: Path, signatur: bool = False) -> bytes:
    if signatur:
        return _signatur_als_png(pfad)
    with Image.open(pfad) as original:
        bild = ImageOps.exif_transpose(original).convert("RGBA")
        speicher = io.BytesIO()
        bild.save(speicher, format="PNG", optimize=True)
        return speicher.getvalue()


def _text_einfuegen(seite: fitz.Page, rechteck: fitz.Rect, text: str, feld: dict[str, Any]) -> None:
    feldtyp = str(feld.get("typ") or "text")
    text = _wert_als_text(text, feldtyp)
    if not text:
        return
    if feldtyp == "kontrollfeld":
        text = "X" if text.lower() in {"1", "true", "ja", "on", "x"} else ""
        if not text:
            return

    schrift = float(feld.get("schriftgroesse") or 10)
    schrift = max(5.5, min(32.0, schrift))
    farbe = _hex_farbe(feld.get("textfarbe"))
    ausrichtung = {"links": 0, "zentriert": 1, "rechts": 2}.get(str(feld.get("ausrichtung") or "links"), 0)
    ziel = fitz.Rect(rechteck.x0, rechteck.y0, rechteck.x1, rechteck.y1)

    # insert_textbox liefert einen negativen Wert, wenn der Inhalt nicht passt.
    # In diesem Fall wird die Schrift kontrolliert verkleinert, statt aus dem Feld zu laufen.
    for groesse in [schrift - schritt * 0.5 for schritt in range(int(max(0, (schrift - 5.5) / 0.5)) + 1)]:
        ergebnis = seite.insert_textbox(
            ziel,
            text[:4000],
            fontname="helv",
            fontsize=max(5.5, groesse),
            color=farbe,
            align=ausrichtung,
            lineheight=1.08,
            overlay=True,
        )
        if ergebnis >= 0:
            return
    # Letzte sichere Ausgabe für extrem lange Einzeiler.
    seite.insert_text((ziel.x0, ziel.y1 - 2), text[:180], fontname="helv", fontsize=5.5, color=farbe, overlay=True)


def _felder_auf_seite_rendern(seite: fitz.Page, felder: list[dict[str, Any]], eingaben: dict[str, Any]) -> None:
    operationen: list[tuple[dict[str, Any], Any, fitz.Rect, bool]] = []

    for feld in felder:
        schluessel = str(feld.get("schluessel") or "")
        wert = eingaben.get(schluessel)
        if wert in (None, "", []):
            continue
        schaetzung = _normalisiertes_rechteck(seite, feld)
        treffer = _treffer_rechteck(seite, feld, schaetzung)
        rechteck = treffer or schaetzung
        beispiel_vorhanden = bool(_suchtext_varianten(feld.get("beispiel")))
        operationen.append((feld, wert, rechteck, beispiel_vorhanden))

        hintergrundmodus = str(feld.get("hintergrundmodus") or "automatisch")
        if beispiel_vorhanden and hintergrundmodus != "transparent":
            farbe = _hintergrundfarbe(seite, rechteck)
            seite.add_redact_annot(rechteck, fill=farbe, cross_out=False)

    if any(beispiel for _, _, _, beispiel in operationen):
        try:
            seite.apply_redactions(images=0, graphics=0, text=0)
        except TypeError:
            seite.apply_redactions(images=0)

    for feld, wert, rechteck, _ in operationen:
        feldtyp = str(feld.get("typ") or "text")
        if feldtyp in {"bild", "unterschrift"}:
            pfad = Path(str(wert))
            if not pfad.exists():
                raise RenderingFehler(f"Die Datei für „{feld.get('bezeichnung') or feld.get('schluessel')}“ ist nicht verfügbar.")
            try:
                bilddaten = _bild_als_bytes(pfad, signatur=feldtyp == "unterschrift")
                seite.insert_image(rechteck, stream=bilddaten, keep_proportion=True, overlay=True)
            except Exception as exc:
                raise RenderingFehler(f"Das Bild für „{feld.get('bezeichnung') or feld.get('schluessel')}“ konnte nicht verarbeitet werden.") from exc
        else:
            _text_einfuegen(seite, rechteck, wert, feld)


def _pdf_aus_bild(original: Path) -> fitz.Document:
    with Image.open(original) as quelle:
        bild = ImageOps.exif_transpose(quelle).convert("RGB")
        speicher = io.BytesIO()
        bild.save(speicher, format="PNG", optimize=True)
    dokument = fitz.open()
    a4 = fitz.paper_rect("a4")
    seite = dokument.new_page(width=a4.width, height=a4.height)
    seite.insert_image(seite.rect, stream=speicher.getvalue(), keep_proportion=True)
    return dokument


def _deckblatt(c: canvas.Canvas, titel: str, vorlagenname: str, eingaben: dict[str, Any], schema: dict[str, Any]) -> None:
    breite, hoehe = A4
    c.setFillColor(APPLUS_DUNKEL)
    c.rect(0, hoehe - 105, breite, 105, fill=1, stroke=0)
    c.setFillColor(APPLUS_BLAU)
    c.rect(42, hoehe - 76, 42, 42, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(63, hoehe - 61, "A+")
    c.setFont("Helvetica-Bold", 20)
    c.drawString(98, hoehe - 53, "SmartDocs")
    c.setFont("Helvetica", 8)
    c.setFillColor(HexColor("#A8C8D8"))
    c.drawString(99, hoehe - 70, "AUTOMATISCH ERSTELLTES DOKUMENT")
    c.setFillColor(APPLUS_DUNKEL)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(42, hoehe - 154, titel)
    c.setFont("Helvetica", 10)
    c.setFillColor(GRAU)
    c.drawString(42, hoehe - 174, f"Vorlage: {vorlagenname}")
    y = hoehe - 220
    c.setFillColor(HELL)
    c.rect(42, 64, breite - 84, y - 30, fill=1, stroke=0)
    c.setFillColor(APPLUS_DUNKEL)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(62, y - 2, "Eingegebene Informationen")
    y -= 28
    feld_index = {str(f.get("schluessel")): f for f in schema.get("felder", [])}
    for schluessel, wert in eingaben.items():
        if not wert or schluessel.startswith("_"):
            continue
        feld = feld_index.get(schluessel, {})
        bezeichnung = str(feld.get("bezeichnung") or schluessel.replace("_", " ").title())
        if str(feld.get("typ")) in {"bild", "unterschrift"}:
            text = "[Bilddatei]"
        else:
            text = _wert_als_text(wert, str(feld.get("typ") or "text"))
        if len(text) > 95:
            text = text[:92] + "…"
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(GRAU)
        c.drawString(62, y, bezeichnung.upper())
        c.setFont("Helvetica", 10)
        c.setFillColor(APPLUS_DUNKEL)
        c.drawString(220, y, text)
        y -= 24
        if y < 88:
            break
    c.setFont("Helvetica", 7)
    c.setFillColor(GRAU)
    c.drawString(42, 38, "Erstellt mit A+ SmartDocs · smartdocs.aplus-solution.de")


def dokument_erzeugen(
    original: Path,
    inhaltstyp: str,
    schema: dict[str, Any],
    eingaben: dict[str, Any],
    ziel: Path,
    titel: str,
    vorlagenname: str,
) -> int:
    _pflichtfelder_pruefen(schema, eingaben)
    ziel.parent.mkdir(parents=True, exist_ok=True)

    if original.exists() and inhaltstyp == "application/pdf":
        dokument = fitz.open(original)
    elif original.exists() and inhaltstyp.startswith("image/"):
        dokument = _pdf_aus_bild(original)
    else:
        return _eigenstaendiges_pdf(schema, eingaben, ziel, titel, vorlagenname)

    try:
        felder = schema.get("felder", []) if isinstance(schema, dict) else []
        for index, seite in enumerate(dokument, start=1):
            seitenfelder = [feld for feld in felder if int(feld.get("seite", 1) or 1) == index]
            if seitenfelder:
                _felder_auf_seite_rendern(seite, seitenfelder, eingaben)
        if dokument.page_count == 0:
            return _eigenstaendiges_pdf(schema, eingaben, ziel, titel, vorlagenname)
        dokument.save(ziel, garbage=4, deflate=True, clean=True)
        return dokument.page_count
    finally:
        dokument.close()


def _eigenstaendiges_pdf(schema: dict[str, Any], eingaben: dict[str, Any], ziel: Path, titel: str, vorlagenname: str) -> int:
    c = canvas.Canvas(str(ziel), pagesize=A4)
    _deckblatt(c, titel, vorlagenname, eingaben, schema)
    c.save()
    return 1
