from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import fitz


ABSCHNITTS_TEXTE = {
    "personalfragebogen",
    "angaben zur person",
    "bankverbindung",
    "lohnsteuer",
    "sozialversicherung",
    "weitere beschäftigungsverhältnisse bei anderen unternehmen",
    "weitere beschaeftigungsverhaeltnisse bei anderen unternehmen",
}

OPTIONENGRUPPEN = [
    ({"herr", "frau", "divers", "unbestimmt"}, "Anrede"),
    ({"gesetzlich", "privat"}, "Art der Krankenversicherung"),
    ({"ja", "nein"}, "Auswahl"),
    ({"geringfügig", "sozialversicherungspflichtig"}, "Art der Beschäftigung"),
    ({"geringfuegig", "sozialversicherungspflichtig"}, "Art der Beschäftigung"),
]

GENERIC_KEYS = {"kundenname", "datum", "beschreibung", "unterschrift"}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text.lower()).strip()
    return re.sub(r"\s+", " ", text)


def _schluessel(text: str, vorhanden: set[str]) -> str:
    basis = _norm(text).replace(" ", "_") or "feld"
    basis = basis[:64]
    kandidat = basis
    nummer = 2
    while kandidat in vorhanden:
        kandidat = f"{basis}_{nummer}"
        nummer += 1
    vorhanden.add(kandidat)
    return kandidat


def _typ_fuer(label: str) -> str:
    wert = _norm(label)
    if any(token in wert for token in ("unterschrift", "signatur")):
        return "unterschrift"
    if any(token in wert for token in ("datum", "geburtstag", "beginn", "ende", "seit wann")):
        return "datum"
    if any(token in wert for token in ("betrag", "brutto", "netto", "gehalt", "verdienst", "lohn")):
        return "betrag"
    if any(token in wert for token in ("beschreibung", "bemerkung", "hinweis", "taetigkeit", "tatigkeit")):
        return "mehrzeilig"
    return "text"


def _normalisierte_position(rect: fitz.Rect, seite: fitz.Page) -> dict[str, float]:
    breite = max(1.0, float(seite.rect.width))
    hoehe = max(1.0, float(seite.rect.height))
    x = max(0.0, min(0.99, rect.x0 / breite))
    y = max(0.0, min(0.99, rect.y0 / hoehe))
    w = max(0.015, min(1.0 - x, rect.width / breite))
    h = max(0.012, min(1.0 - y, rect.height / hoehe))
    return {
        "x": round(x, 5),
        "y": round(y, 5),
        "breite": round(w, 5),
        "hoehe": round(h, 5),
    }


def _textzeilen(seite: fitz.Page) -> list[dict[str, Any]]:
    ergebnis: list[dict[str, Any]] = []
    daten = seite.get_text("dict")
    for block in daten.get("blocks", []):
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
                ergebnis.append(
                    {
                        "text": " ".join(texte).strip(),
                        "rect": rect,
                        "schriftgroesse": max(groessen or [0]),
                    }
                )
    return ergebnis


def _linien(seite: fitz.Page) -> list[tuple[float, float, float]]:
    kandidaten: list[tuple[float, float, float]] = []
    for zeichnung in seite.get_drawings():
        for element in zeichnung.get("items", []):
            art = element[0]
            if art == "l":
                p1, p2 = element[1], element[2]
                if abs(p1.y - p2.y) <= 1.6 and abs(p2.x - p1.x) >= 45:
                    kandidaten.append((min(p1.x, p2.x), max(p1.x, p2.x), (p1.y + p2.y) / 2))
            elif art == "re":
                rect = fitz.Rect(element[1])
                if rect.width >= 45 and 5 <= rect.height <= 45:
                    kandidaten.append((rect.x0, rect.x1, rect.y1))

    kandidaten.sort(key=lambda wert: (round(wert[2], 1), wert[0]))
    bereinigt: list[tuple[float, float, float]] = []
    for kandidat in kandidaten:
        if any(
            abs(kandidat[2] - alt[2]) < 2
            and abs(kandidat[0] - alt[0]) < 4
            and abs(kandidat[1] - alt[1]) < 4
            for alt in bereinigt
        ):
            continue
        bereinigt.append(kandidat)
    return bereinigt


def _ist_feldbezeichnung(text: str, schriftgroesse: float, linienbreite: float, seitenbreite: float) -> bool:
    sauber = _norm(text)
    if not sauber or len(sauber) < 2 or len(sauber) > 90:
        return False
    if sauber in {_norm(wert) for wert in ABSCHNITTS_TEXTE}:
        return False
    if schriftgroesse >= 12.5:
        return False
    if linienbreite > seitenbreite * 0.9 and len(sauber.split()) <= 4:
        return False
    if any(fragment in sauber for fragment in ("kostenlose vorlage", "stand 06 2025", "fuer die inhalte", "ich versichere")):
        return False
    return True


def _naechste_bezeichnung(
    zeilen: list[dict[str, Any]],
    x0: float,
    x1: float,
    y: float,
    seitenbreite: float,
) -> tuple[dict[str, Any] | None, str]:
    breite = x1 - x0
    oberhalb: list[tuple[float, float, dict[str, Any]]] = []
    unterhalb: list[tuple[float, float, dict[str, Any]]] = []
    for zeile in zeilen:
        rect: fitz.Rect = zeile["rect"]
        ueberlappung = max(0.0, min(x1, rect.x1) - max(x0, rect.x0))
        x_nahe = abs(rect.x0 - x0) <= max(18.0, breite * 0.18)
        if ueberlappung <= 0 and not x_nahe:
            continue
        if not _ist_feldbezeichnung(zeile["text"], zeile["schriftgroesse"], breite, seitenbreite):
            continue
        abstand_oben = y - rect.y1
        if -2 <= abstand_oben <= 25:
            oberhalb.append((abs(abstand_oben), abs(rect.x0 - x0), zeile))
        abstand_unten = rect.y0 - y
        if -1 <= abstand_unten <= 15:
            unterhalb.append((abs(abstand_unten), abs(rect.x0 - x0), zeile))

    if oberhalb:
        oberhalb.sort(key=lambda wert: (wert[0], wert[1]))
        return oberhalb[0][2], "oberhalb"
    if unterhalb:
        unterhalb.sort(key=lambda wert: (wert[0], wert[1]))
        return unterhalb[0][2], "unterhalb"
    return None, ""


def _widget_felder(seite: fitz.Page, seitenzahl: int, vorhanden: set[str]) -> list[dict[str, Any]]:
    felder: list[dict[str, Any]] = []
    widgets = list(seite.widgets() or [])
    typ_map = {
        "Text": "text",
        "CheckBox": "kontrollfeld",
        "RadioButton": "auswahl",
        "ComboBox": "auswahl",
        "ListBox": "auswahl",
        "Signature": "unterschrift",
    }
    for widget in widgets:
        label = (widget.field_label or widget.field_name or "Formularfeld").strip()
        typ_string = str(getattr(widget, "field_type_string", "Text") or "Text")
        typ = typ_map.get(typ_string, "text")
        optionen = list(getattr(widget, "choice_values", None) or [])
        felder.append(
            {
                "schluessel": _schluessel(widget.field_name or label, vorhanden),
                "bezeichnung": label,
                "typ": typ,
                "pflichtfeld": False,
                "beispiel": str(widget.field_value or ""),
                "seite": seitenzahl,
                "hinweis": "Interaktives PDF-Formularfeld",
                "optionen": optionen,
                "position": _normalisierte_position(widget.rect, seite),
                "schriftgroesse": 9,
                "ausrichtung": "links",
                "hintergrundmodus": "transparent",
                "erkennungsquelle": "pdf-formularfeld",
            }
        )
    return felder


def _linien_felder(seite: fitz.Page, seitenzahl: int, vorhanden: set[str]) -> list[dict[str, Any]]:
    zeilen = _textzeilen(seite)
    felder: list[dict[str, Any]] = []
    verwendete_bezeichnungen: list[tuple[str, float, float]] = []

    for x0, x1, y in _linien(seite):
        bezeichnung, lage = _naechste_bezeichnung(zeilen, x0, x1, y, seite.rect.width)
        if not bezeichnung:
            continue
        label = str(bezeichnung["text"]).strip().strip(":")
        sauber = _norm(label)
        if any(sauber == alt and abs(y - alt_y) < 8 and abs(x0 - alt_x) < 8 for alt, alt_x, alt_y in verwendete_bezeichnungen):
            continue
        verwendete_bezeichnungen.append((sauber, x0, y))

        typ = _typ_fuer(label)
        if lage == "oberhalb":
            obere_kante = min(y - 5, max(bezeichnung["rect"].y1 + 1, y - (30 if typ == "unterschrift" else 18)))
        else:
            obere_kante = y - (32 if typ == "unterschrift" else 17)
        untere_kante = max(obere_kante + 8, y - 1)
        rect = fitz.Rect(x0 + 1, obere_kante, x1 - 1, untere_kante)
        if rect.width < 25 or rect.height < 6:
            continue

        felder.append(
            {
                "schluessel": _schluessel(label, vorhanden),
                "bezeichnung": label,
                "typ": typ,
                "pflichtfeld": False,
                "beispiel": "",
                "seite": seitenzahl,
                "hinweis": "Aus Beschriftung und Eingabelinie des Originaldokuments erkannt",
                "optionen": [],
                "position": _normalisierte_position(rect, seite),
                "schriftgroesse": 8 if rect.width < 130 else 9,
                "ausrichtung": "links",
                "hintergrundmodus": "transparent",
                "erkennungsquelle": "pdf-layout",
            }
        )
    return felder


def _auswahl_felder(seite: fitz.Page, seitenzahl: int, vorhanden: set[str]) -> list[dict[str, Any]]:
    zeilen = _textzeilen(seite)
    felder: list[dict[str, Any]] = []
    for index, zeile in enumerate(zeilen):
        tokens = set(_norm(zeile["text"]).split())
        for gruppe, standard_label in OPTIONENGRUPPEN:
            optionen = [wort for wort in gruppe if wort in tokens]
            if len(optionen) < 2:
                continue
            label = standard_label
            if standard_label == "Auswahl":
                for vorher in reversed(zeilen[max(0, index - 3):index]):
                    if vorher["rect"].y1 <= zeile["rect"].y1 and len(_norm(vorher["text"])) < 70:
                        label = vorher["text"].strip().strip(":")
                        break
            rect = zeile["rect"]
            felder.append(
                {
                    "schluessel": _schluessel(label, vorhanden),
                    "bezeichnung": label,
                    "typ": "auswahl",
                    "pflichtfeld": False,
                    "beispiel": "",
                    "seite": seitenzahl,
                    "hinweis": "Auswahlgruppe aus dem Originaldokument erkannt",
                    "optionen": [wort.capitalize() for wort in sorted(optionen)],
                    "position": _normalisierte_position(rect, seite),
                    "schriftgroesse": 8,
                    "ausrichtung": "links",
                    "hintergrundmodus": "transparent",
                    "erkennungsquelle": "pdf-auswahlgruppe",
                }
            )
            break
    return felder


def formular_lokal_analysieren(dateipfad: Path, dateiname: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Erkennt Formularfelder deterministisch aus AcroForm, Text und Layout eines PDF."""
    if dateipfad.suffix.lower() != ".pdf":
        return {
            "dokumentart": "Dokumentvorlage",
            "zusammenfassung": "Für Bilddateien ist eine visuelle KI-Analyse erforderlich.",
            "felder": [],
            "rueckfragen": [],
            "analysequelle": "keine-lokale-erkennung",
        }, {"felder": 0, "seiten": 0, "quelle": "nicht-pdf"}

    dokument = fitz.open(dateipfad)
    vorhanden: set[str] = set()
    felder: list[dict[str, Any]] = []
    widget_anzahl = 0
    try:
        for index, seite in enumerate(dokument):
            seitenzahl = index + 1
            widgets = _widget_felder(seite, seitenzahl, vorhanden)
            widget_anzahl += len(widgets)
            felder.extend(widgets)
            felder.extend(_linien_felder(seite, seitenzahl, vorhanden))
            felder.extend(_auswahl_felder(seite, seitenzahl, vorhanden))
    finally:
        dokument.close()

    # Gleiche Felder aus Widget- und Layoutanalyse nicht doppelt ausgeben.
    eindeutig: list[dict[str, Any]] = []
    for feld in felder:
        position = feld.get("position", {})
        if any(
            feld.get("seite") == alt.get("seite")
            and _norm(feld.get("bezeichnung", "")) == _norm(alt.get("bezeichnung", ""))
            and abs(float(position.get("x", 0)) - float(alt.get("position", {}).get("x", 0))) < 0.03
            and abs(float(position.get("y", 0)) - float(alt.get("position", {}).get("y", 0))) < 0.03
            for alt in eindeutig
        ):
            continue
        eindeutig.append(feld)

    dokumentart = Path(dateiname).stem.replace("_", " ").replace("-", " ").strip() or "Formular"
    schema = {
        "dokumentart": dokumentart,
        "zusammenfassung": f"{len(eindeutig)} Eingabebereiche wurden direkt aus Struktur und Layout des Originaldokuments erkannt.",
        "felder": eindeutig,
        "rueckfragen": [],
        "analysequelle": "pdf-struktur",
        "analysequalitaet": {
            "erkannte_felder": len(eindeutig),
            "interaktive_pdf_felder": widget_anzahl,
        },
    }
    return schema, {
        "felder": len(eindeutig),
        "seiten": len(dokument) if not dokument.is_closed else 0,
        "interaktive_felder": widget_anzahl,
        "quelle": "pdf-struktur",
    }


def _aehnlichkeit(a: str, b: str) -> float:
    a_tokens = set(_norm(a).split())
    b_tokens = set(_norm(b).split())
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def schema_kombinieren(ki_schema: dict[str, Any], lokales_schema: dict[str, Any]) -> dict[str, Any]:
    ki_felder = list(ki_schema.get("felder", []) or [])
    lokale_felder = list(lokales_schema.get("felder", []) or [])
    if not lokale_felder:
        return ki_schema
    if not ki_felder:
        return lokales_schema

    ki_keys = {_norm(str(feld.get("schluessel", ""))) for feld in ki_felder}
    offensichtlich_generisch = len(ki_felder) <= 4 and ki_keys.issubset(GENERIC_KEYS)
    ki_unvollstaendig = len(lokale_felder) >= 6 and len(ki_felder) < len(lokale_felder) * 0.5
    if offensichtlich_generisch or ki_unvollstaendig:
        ergebnis = dict(lokales_schema)
        ergebnis["zusammenfassung"] = (
            f"Die PDF-Struktur lieferte {len(lokale_felder)} konkrete Eingabebereiche; "
            "ein unvollständiger allgemeiner KI-Vorschlag wurde verworfen."
        )
        ergebnis["analysequelle"] = "pdf-struktur-priorisiert"
        return ergebnis

    verwendet: set[int] = set()
    kombiniert: list[dict[str, Any]] = []
    for ki_feld in ki_felder:
        bester_index = -1
        bester_wert = 0.0
        for index, lokal in enumerate(lokale_felder):
            if index in verwendet or int(ki_feld.get("seite", 1)) != int(lokal.get("seite", 1)):
                continue
            wert = max(
                _aehnlichkeit(str(ki_feld.get("bezeichnung", "")), str(lokal.get("bezeichnung", ""))),
                _aehnlichkeit(str(ki_feld.get("schluessel", "")), str(lokal.get("schluessel", ""))),
            )
            if wert > bester_wert:
                bester_wert = wert
                bester_index = index
        if bester_index >= 0 and bester_wert >= 0.45:
            lokal = lokale_felder[bester_index]
            verwendet.add(bester_index)
            zusammen = dict(ki_feld)
            zusammen["position"] = lokal.get("position")
            zusammen["erkennungsquelle"] = "ki-und-pdf-layout"
            if lokal.get("typ") in {"datum", "betrag", "unterschrift", "auswahl", "kontrollfeld"}:
                zusammen["typ"] = lokal.get("typ")
            if lokal.get("optionen"):
                zusammen["optionen"] = lokal.get("optionen")
            kombiniert.append(zusammen)
        else:
            kombiniert.append(ki_feld)

    kombiniert.extend(feld for index, feld in enumerate(lokale_felder) if index not in verwendet)
    ergebnis = dict(ki_schema)
    ergebnis["felder"] = kombiniert
    ergebnis["analysequelle"] = "ki-und-pdf-struktur"
    ergebnis["analysequalitaet"] = {
        "ki_felder": len(ki_felder),
        "lokale_felder": len(lokale_felder),
        "gesamtfelder": len(kombiniert),
    }
    return ergebnis
