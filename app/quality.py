from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any


QUELLEN_VERTRAUEN = {
    "manuell": 1.0,
    "manuell-korrigiert": 1.0,
    "pdf-formularfeld": 0.99,
    "ki-und-pdf-layout": 0.94,
    "pdf-layout": 0.87,
    "pdf-auswahlgruppe": 0.83,
    "pdf-textkandidat": 0.58,
    "ki-und-pdf-struktur": 0.82,
    "ki": 0.66,
}

GENERIC_LABELS = {
    "feld",
    "formularfeld",
    "text",
    "datum",
    "beschreibung",
    "kundenname",
    "unterschrift",
}


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _position_vollstaendig(feld: dict[str, Any]) -> bool:
    position = feld.get("position") or {}
    try:
        x = float(position.get("x"))
        y = float(position.get("y"))
        breite = float(position.get("breite"))
        hoehe = float(position.get("hoehe"))
    except (TypeError, ValueError):
        return False
    return 0 <= x < 1 and 0 <= y < 1 and 0 < breite <= 1 and 0 < hoehe <= 1


def feld_konfidenz(feld: dict[str, Any]) -> tuple[float, str]:
    quelle = str(feld.get("erkennungsquelle") or "ki").strip().lower()
    wert = QUELLEN_VERTRAUEN.get(quelle, 0.62)
    gruende: list[str] = []

    if _position_vollstaendig(feld):
        wert += 0.02
    else:
        wert -= 0.28
        gruende.append("Position ist nicht vollständig bestimmt")

    bezeichnung = _norm(feld.get("bezeichnung"))
    if not bezeichnung or bezeichnung in GENERIC_LABELS:
        wert -= 0.16
        gruende.append("Feldbezeichnung ist allgemein")

    typ = str(feld.get("typ") or "text")
    optionen = list(feld.get("optionen") or [])
    if typ == "auswahl" and len(optionen) < 2:
        wert -= 0.12
        gruende.append("Auswahloptionen sind nicht eindeutig")
    if typ == "unterschrift" and any(token in bezeichnung for token in ("unterschrift", "signatur")):
        wert += 0.03
    if feld.get("beispiel"):
        wert += 0.02

    wert = round(max(0.05, min(1.0, wert)), 2)
    if wert >= 0.88:
        stufe = "sicher"
        standard_hinweis = "Position und Feldart wurden aus einer belastbaren Dokumentstruktur übernommen."
    elif wert >= 0.68:
        stufe = "pruefen"
        standard_hinweis = "Das Feld ist plausibel, sollte aber kurz in der Testausfüllung geprüft werden."
    else:
        stufe = "unsicher"
        standard_hinweis = "Position oder Feldart sind nicht eindeutig und müssen bestätigt werden."
    return wert, "; ".join(gruende) if gruende else standard_hinweis


def schema_mit_qualitaet(schema: dict[str, Any] | None) -> dict[str, Any]:
    ergebnis: dict[str, Any] = copy.deepcopy(schema or {})
    felder = list(ergebnis.get("felder") or [])
    sicher = pruefen = unsicher = offen = 0
    summe = 0.0

    for feld in felder:
        vorher_geprueft = bool(feld.get("geprueft"))
        wert, hinweis = feld_konfidenz(feld)
        stufe = "sicher" if wert >= 0.88 else "pruefen" if wert >= 0.68 else "unsicher"
        feld["konfidenz"] = wert
        feld["konfidenzstufe"] = stufe
        feld["pruefhinweis"] = hinweis
        feld["pruefung_erforderlich"] = stufe != "sicher"
        feld["geprueft"] = vorher_geprueft or str(feld.get("erkennungsquelle")) in {"manuell", "manuell-korrigiert"}
        summe += wert
        if stufe == "sicher":
            sicher += 1
        elif stufe == "pruefen":
            pruefen += 1
        else:
            unsicher += 1
        if stufe != "sicher" and not feld["geprueft"]:
            offen += 1

    ergebnis["felder"] = felder
    ergebnis["qualitaet"] = {
        "gesamt": len(felder),
        "sicher": sicher,
        "pruefen": pruefen,
        "unsicher": unsicher,
        "offene_felder": offen,
        "durchschnitt": round(summe / len(felder), 2) if felder else 0.0,
        "testausfuellung_geprueft": bool(ergebnis.get("testausfuellung_geprueft")),
    }
    return ergebnis


def schema_fingerabdruck(schema: dict[str, Any] | None) -> str:
    relevante_felder: list[dict[str, Any]] = []
    for feld in list((schema or {}).get("felder") or []):
        relevante_felder.append(
            {
                "schluessel": feld.get("schluessel"),
                "bezeichnung": feld.get("bezeichnung"),
                "typ": feld.get("typ"),
                "seite": feld.get("seite"),
                "position": feld.get("position"),
                "optionen": feld.get("optionen"),
                "schriftgroesse": feld.get("schriftgroesse"),
                "beispiel": feld.get("beispiel"),
                "hintergrundmodus": feld.get("hintergrundmodus"),
            }
        )
    roh = json.dumps(relevante_felder, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


def testwert_fuer_feld(feld: dict[str, Any], signatur_pfad: Path) -> Any:
    typ = str(feld.get("typ") or "text")
    label = str(feld.get("bezeichnung") or "Feld").strip()
    if typ in {"unterschrift", "bild"}:
        return str(signatur_pfad)
    if typ == "datum":
        return "2026-07-26"
    if typ == "betrag":
        return "1.234,56 €"
    if typ == "zahl":
        return "123"
    if typ == "kontrollfeld":
        return "Ja"
    if typ == "auswahl":
        optionen = list(feld.get("optionen") or [])
        return str(optionen[0]) if optionen else "Ja"
    if typ in {"mehrzeilig", "tabelle"}:
        return "Musterangabe zur Prüfung von Position, Größe und Zeilenumbruch."
    kurz = label[:28].upper()
    return f"MUSTER {kurz}"


__all__ = [
    "feld_konfidenz",
    "schema_fingerabdruck",
    "schema_mit_qualitaet",
    "testwert_fuer_feld",
]
