from __future__ import annotations

import copy
import re
import unicodedata
from pathlib import Path
from typing import Any

import fitz


GENERISCHE_HINWEISE = {
    "interaktives pdf formularfeld",
    "interactive pdf form field",
    "automatisch erkannt",
    "bearbeitbares feld",
}

GENERISCHE_LABEL_MUSTER = (
    r"^(?:option|options|auswahl|text|checkbox|check box|radio|formular|form)(?:\s+(?:field|feld))?\s*\d*$",
    r"^(?:field|feld|formularfeld)\s*\d*$",
)


def _norm(text: Any) -> str:
    wert = unicodedata.normalize("NFKD", str(text or ""))
    wert = "".join(zeichen for zeichen in wert if not unicodedata.combining(zeichen))
    wert = re.sub(r"[^a-zA-Z0-9]+", " ", wert.lower()).strip()
    return re.sub(r"\s+", " ", wert)


def _ist_generisch(text: Any) -> bool:
    sauber = _norm(text)
    if not sauber:
        return True
    return any(re.fullmatch(muster, sauber, flags=re.IGNORECASE) for muster in GENERISCHE_LABEL_MUSTER)


def _label_bereinigen(text: Any) -> str:
    wert = re.sub(r"[_\s]+", " ", str(text or "")).strip(" :-–—")
    muster = (
        r"^(?:please\s+)?(?:enter|type|insert)\s+",
        r"^geben\s+sie\s+",
        r"^(?:bitte|hier)\s+",
        r"\s+(?:here|hier)$",
        r"\s+hier\s+ein$",
        r"\s+(?:eingeben|eintragen)$",
    )
    for ausdruck in muster:
        wert = re.sub(ausdruck, "", wert, flags=re.IGNORECASE).strip(" :-–—")
    return re.sub(r"\s+", " ", wert)


def _position_als_rechteck(feld: dict[str, Any], seite: fitz.Page) -> fitz.Rect | None:
    position = feld.get("position") or {}
    try:
        x = float(position.get("x", 0)) * seite.rect.width
        y = float(position.get("y", 0)) * seite.rect.height
        breite = float(position.get("breite", 0)) * seite.rect.width
        hoehe = float(position.get("hoehe", 0)) * seite.rect.height
    except (TypeError, ValueError):
        return None
    if breite <= 0 or hoehe <= 0:
        return None
    return fitz.Rect(x, y, min(seite.rect.width, x + breite), min(seite.rect.height, y + hoehe))


def _textzeilen(seite: fitz.Page) -> list[dict[str, Any]]:
    zeilen: list[dict[str, Any]] = []
    for block in seite.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for zeile in block.get("lines", []):
            texte: list[str] = []
            groessen: list[float] = []
            rechteck: fitz.Rect | None = None
            for span in zeile.get("spans", []):
                text = str(span.get("text", "")).strip()
                if not text:
                    continue
                texte.append(text)
                groessen.append(float(span.get("size", 0) or 0))
                span_rechteck = fitz.Rect(span.get("bbox", (0, 0, 0, 0)))
                rechteck = span_rechteck if rechteck is None else rechteck | span_rechteck
            if texte and rechteck is not None:
                zeilen.append({"text": " ".join(texte), "rect": rechteck, "schriftgroesse": max(groessen or [0])})
    return zeilen


def _nahe_beschriftung(seite: fitz.Page, rechteck: fitz.Rect, feldtyp: str) -> str:
    kandidaten: list[tuple[float, str]] = []
    mitte_y = (rechteck.y0 + rechteck.y1) / 2
    auswahl = feldtyp in {"auswahl", "kontrollfeld"}

    for zeile in _textzeilen(seite):
        text = _label_bereinigen(zeile["text"])
        zeilenrechteck: fitz.Rect = zeile["rect"]
        if not text or len(text) > 110 or float(zeile["schriftgroesse"]) > 12.5:
            continue
        if _ist_generisch(text):
            continue
        schnitt = rechteck & zeilenrechteck
        if schnitt.get_area() > min(rechteck.get_area(), zeilenrechteck.get_area()) * 0.45:
            continue

        ueberlappung_x = max(0.0, min(rechteck.x1, zeilenrechteck.x1) - max(rechteck.x0, zeilenrechteck.x0))
        zeilen_mitte_y = (zeilenrechteck.y0 + zeilenrechteck.y1) / 2
        y_abstand = abs(zeilen_mitte_y - mitte_y)

        rechts = zeilenrechteck.x0 - rechteck.x1
        links = rechteck.x0 - zeilenrechteck.x1
        oben = rechteck.y0 - zeilenrechteck.y1
        unten = zeilenrechteck.y0 - rechteck.y1

        if auswahl and 0 <= rechts <= 120 and y_abstand <= 13:
            kandidaten.append((rechts + y_abstand * 2, text))
        if auswahl and 0 <= links <= 220 and y_abstand <= 14:
            kandidaten.append((18 + links * 0.18 + y_abstand * 2, text))
        if ueberlappung_x > 3 and 0 <= unten <= 20:
            kandidaten.append(((30 if auswahl else 0) + unten, text))
        if ueberlappung_x > 3 and 0 <= oben <= 26:
            kandidaten.append(((38 if auswahl else 10) + oben, text))

    if not kandidaten:
        return ""
    kandidaten.sort(key=lambda eintrag: (eintrag[0], len(eintrag[1])))
    return kandidaten[0][1]


def schema_mit_dokumentbeschriftungen(schema: dict[str, Any] | None, dateipfad: Path | None = None) -> dict[str, Any]:
    """Bereinigt technische AcroForm-Namen, ohne Schlüssel oder Positionen zu verändern."""
    ergebnis = copy.deepcopy(schema or {})
    felder = list(ergebnis.get("felder") or [])
    dokument: fitz.Document | None = None

    if dateipfad and dateipfad.suffix.lower() == ".pdf" and dateipfad.exists():
        try:
            dokument = fitz.open(dateipfad)
        except Exception:
            dokument = None

    verwendete_labels: dict[str, int] = {}
    bereinigt: list[dict[str, Any]] = []
    try:
        for index, original in enumerate(felder, start=1):
            feld = copy.deepcopy(original)
            typ = str(feld.get("typ") or "text")
            label_original = str(feld.get("bezeichnung") or "")
            label = _label_bereinigen(label_original)
            nahe = ""

            seitenzahl = max(1, int(feld.get("seite") or 1))
            if dokument is not None and seitenzahl <= len(dokument):
                seite = dokument[seitenzahl - 1]
                rechteck = _position_als_rechteck(feld, seite)
                if rechteck is not None:
                    nahe = _nahe_beschriftung(seite, rechteck, typ)

            if nahe and (_ist_generisch(label) or len(nahe) < len(label) + 18):
                label = nahe

            beispiel = _label_bereinigen(feld.get("beispiel"))
            if _ist_generisch(label) and beispiel and _norm(beispiel) not in {"off", "on", "yes", "no", "ja", "nein"}:
                label = beispiel

            optionen = []
            for option in list(feld.get("optionen") or []):
                option_text = _label_bereinigen(option)
                if option_text and option_text not in optionen:
                    optionen.append(option_text)

            if typ == "auswahl" and len(optionen) < 2:
                # Ein leeres Select ist unbedienbar. Einzelne PDF-Radio-/Optionsfelder
                # werden als anklickbare Markierung an ihrer echten Position behandelt.
                typ = "kontrollfeld"
                optionen = []

            if not label or _ist_generisch(label):
                label = "Option" if typ == "kontrollfeld" else "Feld"
                label = f"{label} {index}"

            basis = _norm(label)
            verwendete_labels[basis] = verwendete_labels.get(basis, 0) + 1
            if verwendete_labels[basis] > 1:
                label = f"{label} ({verwendete_labels[basis]})"

            hinweis = str(feld.get("hinweis") or "").strip()
            feld["bezeichnung"] = label
            feld["typ"] = typ
            feld["optionen"] = optionen
            feld["anzeige_hinweis"] = "" if _norm(hinweis) in GENERISCHE_HINWEISE else hinweis
            bereinigt.append(feld)
    finally:
        if dokument is not None:
            dokument.close()

    ergebnis["felder"] = bereinigt
    return ergebnis


def formularfelder(schema: dict[str, Any] | None, dateipfad: Path | None = None) -> list[dict[str, Any]]:
    felder = list(schema_mit_dokumentbeschriftungen(schema, dateipfad).get("felder") or [])
    return sorted(
        felder,
        key=lambda feld: (
            int(feld.get("seite") or 1),
            float((feld.get("position") or {}).get("y", 0)),
            float((feld.get("position") or {}).get("x", 0)),
        ),
    )


def formularabschnitte(felder: list[dict[str, Any]], maximale_felder: int = 10) -> list[dict[str, Any]]:
    abschnitte: list[dict[str, Any]] = []
    nach_seite: dict[int, list[dict[str, Any]]] = {}
    for feld in felder:
        nach_seite.setdefault(max(1, int(feld.get("seite") or 1)), []).append(feld)

    for seite in sorted(nach_seite):
        seitenfelder = nach_seite[seite]
        for start in range(0, len(seitenfelder), maximale_felder):
            teil = seitenfelder[start:start + maximale_felder]
            nummer = start // maximale_felder + 1
            abschnitte.append(
                {
                    "titel": f"Seite {seite} · Abschnitt {nummer}",
                    "beschreibung": f"{len(teil)} Felder in der Reihenfolge des Originaldokuments",
                    "felder": teil,
                }
            )
    return abschnitte


__all__ = ["formularabschnitte", "formularfelder", "schema_mit_dokumentbeschriftungen"]
