from __future__ import annotations

import copy
import re
import unicodedata
from pathlib import Path
from typing import Any

import fitz
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from . import analysis_flow as _analysis_flow
from . import chat_jobs as _chat_jobs
from . import workflow_v2 as _workflow_v2
from .database import datenbank_sitzung
from .main import app, aktuelles_mitglied, grundkontext, vorlage_fuer_mitglied, vorlagen, weiterleitung_anmeldung
from .models import Vorlagendialog


def _norm(text: Any) -> str:
    wert = unicodedata.normalize("NFKD", str(text or "").lower())
    wert = "".join(zeichen for zeichen in wert if not unicodedata.combining(zeichen))
    wert = wert.replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", " ", wert).strip()


_SYNONYME = {
    "employee": "arbeitnehmer",
    "worker": "arbeitnehmer",
    "staff": "arbeitnehmer",
    "mitarbeiter": "arbeitnehmer",
    "employer": "arbeitgeber",
    "company": "arbeitgeber",
    "companyname": "firmenname",
    "firmname": "firmenname",
    "unternehmen": "arbeitgeber",
    "address": "anschrift",
    "adresse": "anschrift",
    "street": "anschrift",
    "strasse": "anschrift",
    "wohnort": "anschrift",
    "signature": "unterschrift",
    "signatur": "unterschrift",
    "date": "datum",
}


def _tokens(text: Any) -> set[str]:
    stop = {"der", "die", "das", "den", "dem", "des", "ein", "eine", "von", "fur", "the", "of", "field", "feld"}
    return {
        _SYNONYME.get(token, token)
        for token in _norm(text).split()
        if token and token not in stop
    }


def _dimensionen(text: Any) -> dict[str, str]:
    tokens = _tokens(text)
    normal = _norm(text)
    actor = ""
    if "arbeitnehmer" in tokens:
        actor = "arbeitnehmer"
    elif "arbeitgeber" in tokens or "firmenname" in tokens:
        actor = "arbeitgeber"

    art = ""
    if "anschrift" in tokens:
        art = "anschrift"
    elif "unterschrift" in tokens:
        art = "unterschrift"
    elif any(token in tokens for token in {"datum", "beginn", "ende", "beendigung", "enddatum"}):
        art = "datum"
    elif any(token in tokens for token in {"iban", "konto", "bank"}):
        art = "bank"
    elif "name" in tokens or "firmenname" in tokens or "vorname" in tokens or "nachname" in tokens:
        art = "name"

    # Zusammengesetzte englische Begriffe müssen beide Dimensionen tragen.
    if any(phrase in normal for phrase in ("employee address", "worker address")):
        actor, art = "arbeitnehmer", "anschrift"
    if any(phrase in normal for phrase in ("employer address", "company address")):
        actor, art = "arbeitgeber", "anschrift"
    if any(phrase in normal for phrase in ("employee name", "worker name")):
        actor, art = "arbeitnehmer", "name"
    if any(phrase in normal for phrase in ("employer name", "company name", "firmname", "companyname")):
        actor, art = "arbeitgeber", "name"
    return {"actor": actor, "art": art}


def _feldtext(feld: dict[str, Any]) -> str:
    return " ".join(
        str(feld.get(schluessel) or "")
        for schluessel in ("bezeichnung", "schluessel", "hinweis", "anzeige_hinweis")
    )


def _striktes_feld(felder: list[dict[str, Any]], suchtext: str) -> tuple[int, dict[str, Any]] | None:
    gesucht = _tokens(suchtext)
    dimension = _dimensionen(suchtext)
    if not gesucht:
        return None

    kandidaten: list[tuple[float, int, dict[str, Any]]] = []
    for index, feld in enumerate(felder):
        beschreibung = _feldtext(feld)
        vorhanden = _tokens(beschreibung)
        feld_dimension = _dimensionen(beschreibung)

        # Explizite Dimensionen sind harte Bedingungen. So darf "employee address"
        # niemals auf "Arbeitnehmer Name" fallen.
        if dimension["actor"] and feld_dimension["actor"] != dimension["actor"]:
            continue
        if dimension["art"] and feld_dimension["art"] != dimension["art"]:
            continue

        gemeinsam = len(gesucht & vorhanden)
        score = gemeinsam / max(1, len(gesucht | vorhanden))
        if dimension["actor"]:
            score += 0.35
        if dimension["art"]:
            score += 0.45
        normal_suche = _norm(suchtext)
        normal_feld = _norm(beschreibung)
        if normal_suche and normal_suche in normal_feld:
            score += 0.55
        kandidaten.append((score, index, feld))

    kandidaten.sort(key=lambda eintrag: eintrag[0], reverse=True)
    if not kandidaten or kandidaten[0][0] < 0.62:
        return None
    if len(kandidaten) > 1 and kandidaten[0][0] - kandidaten[1][0] < 0.12:
        return None
    return kandidaten[0][1], kandidaten[0][2]


def _lokale_korrektur_praezise(schema: dict[str, Any], nachricht: str) -> tuple[dict[str, Any], str] | None:
    daten = copy.deepcopy(schema)
    felder = list(daten.get("felder", []) or [])
    zuweisung = re.match(r"^(.+?)\s+(?:ist|is|=|soll(?:te)?\s+sein)\s+(.+?)\s*[.!]?$", nachricht.strip(), re.IGNORECASE)
    if zuweisung:
        zieltext, wert = zuweisung.group(1).strip(), zuweisung.group(2).strip()
        treffer = _striktes_feld(felder, zieltext)
        if not treffer:
            return daten, (
                f"Ich konnte „{zieltext}“ keinem Feld eindeutig zuordnen. "
                "Klicken Sie das gewünschte Feld kurz im Dokument an und senden Sie den Wert erneut."
            )
        index, original = treffer
        feld = dict(original)

        # Derselbe Testwert darf nach einer früheren Fehlzuordnung nicht in zwei
        # Feldern stehen bleiben.
        for anderer_index, anderes_original in enumerate(felder):
            if anderer_index == index:
                continue
            anderes = dict(anderes_original)
            if str(anderes.get("standardwert") or "").strip() == wert:
                anderes["standardwert"] = ""
                anderes["vorschauwert"] = ""
                felder[anderer_index] = anderes
            elif (
                str(anderes.get("beispiel") or "").strip() == wert
                and anderes.get("geprueft")
                and not anderes.get("ursprungsbeispiel")
            ):
                anderes["beispiel"] = ""
                anderes["standardwert"] = ""
                anderes["vorschauwert"] = ""
                felder[anderer_index] = anderes

        feld.setdefault("ursprungsbeispiel", str(feld.get("beispiel") or ""))
        feld["standardwert"] = wert
        feld["vorschauwert"] = wert
        feld["vorschlag_status"] = "bestaetigt"
        feld["geprueft"] = True
        feld["konfidenz"] = 1
        feld["konfidenzstufe"] = "sicher"
        felder[index] = feld
        daten["felder"] = felder
        return daten, f"„{feld.get('bezeichnung', 'Feld')}“ wurde auf „{wert}“ gesetzt."

    # Für nicht wertsetzende Standardbefehle bleibt die bestehende Logik erhalten,
    # verwendet aber den strikten Matcher.
    return _URSPRUNG_LOKALE_KORREKTUR(daten, nachricht)


def _position(rect: fitz.Rect, seite: fitz.Page, mindestbreite: float | None = None) -> dict[str, float]:
    breite = float(seite.rect.width or 1)
    hoehe = float(seite.rect.height or 1)
    x = max(0.0, rect.x0 / breite)
    y = max(0.0, rect.y0 / hoehe)
    w = rect.width / breite
    h = rect.height / hoehe
    if mindestbreite:
        w = max(w, mindestbreite)
    return {
        "x": round(min(0.99, x), 5),
        "y": round(min(0.99, y), 5),
        "breite": round(max(0.02, min(1.0 - x, w)), 5),
        "hoehe": round(max(0.015, min(1.0 - y, h)), 5),
    }


def _rechteck_aus_position(feld: dict[str, Any], seite: fitz.Page) -> fitz.Rect:
    pos = feld.get("position") or {}
    return fitz.Rect(
        float(pos.get("x", 0)) * seite.rect.width,
        float(pos.get("y", 0)) * seite.rect.height,
        (float(pos.get("x", 0)) + float(pos.get("breite", 0.2))) * seite.rect.width,
        (float(pos.get("y", 0)) + float(pos.get("hoehe", 0.04))) * seite.rect.height,
    )


def _exakter_treffer(seite: fitz.Page, text: str, schaetzung: fitz.Rect) -> fitz.Rect | None:
    varianten = [text.strip(), re.sub(r"\s+", " ", text).strip()]
    treffer: list[fitz.Rect] = []
    for variante in dict.fromkeys(variante for variante in varianten if variante):
        try:
            treffer.extend(seite.search_for(variante, quads=False))
        except Exception:
            continue
    if not treffer:
        return None
    mitte_x = (schaetzung.x0 + schaetzung.x1) / 2
    mitte_y = (schaetzung.y0 + schaetzung.y1) / 2
    return min(
        treffer,
        key=lambda rect: ((rect.x0 + rect.x1) / 2 - mitte_x) ** 2 + ((rect.y0 + rect.y1) / 2 - mitte_y) ** 2,
    )


def _offensichtlich_falsch(feld: dict[str, Any], seite: fitz.Page) -> bool:
    quelle = str(feld.get("erkennungsquelle") or "")
    if quelle in {"manuell", "manuell-korrigiert", "pdf-formularfeld"}:
        return False
    label = str(feld.get("bezeichnung") or "").strip()
    sauber = _norm(label)
    pos = feld.get("position") or {}
    breite = float(pos.get("breite", 0) or 0)
    hoehe = float(pos.get("hoehe", 0) or 0)
    if breite < 0.035 or hoehe < 0.009:
        return True
    if len(label) > 68 or len(sauber.split()) > 9:
        return True
    dimension = _dimensionen(label)
    satzfragmente = {"wird", "werden", "vertraglichen", "beschaftigungsverhaltnis", "identischen", "gemass", "erklart"}
    if not dimension["actor"] and not dimension["art"] and satzfragmente & set(sauber.split()):
        return True
    if not feld.get("beispiel") and quelle in {"pdf-layout", "ki", "ki-und-pdf-layout"}:
        rect = _rechteck_aus_position(feld, seite)
        text = " ".join(wort[4] for wort in seite.get_text("words") if fitz.Rect(wort[:4]).intersects(rect)).strip()
        if len(text) > 42:
            return True
    return False


def _ueberlappung(a: dict[str, Any], b: dict[str, Any]) -> float:
    pa, pb = a.get("position") or {}, b.get("position") or {}
    ax0, ay0 = float(pa.get("x", 0)), float(pa.get("y", 0))
    ax1, ay1 = ax0 + float(pa.get("breite", 0)), ay0 + float(pa.get("hoehe", 0))
    bx0, by0 = float(pb.get("x", 0)), float(pb.get("y", 0))
    bx1, by1 = bx0 + float(pb.get("breite", 0)), by0 + float(pb.get("hoehe", 0))
    schnitt = max(0, min(ax1, bx1) - max(ax0, bx0)) * max(0, min(ay1, by1) - max(ay0, by0))
    union = max(1e-8, (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - schnitt)
    return schnitt / union


def schema_positionen_schaerfen(schema: dict[str, Any] | None, dateipfad: Path) -> tuple[dict[str, Any], bool]:
    daten = copy.deepcopy(schema or {})
    felder = list(daten.get("felder", []) or [])
    if not dateipfad.exists() or dateipfad.suffix.lower() != ".pdf":
        return daten, False
    try:
        dokument = fitz.open(dateipfad)
    except Exception:
        return daten, False

    geaendert = False
    bereinigt: list[dict[str, Any]] = []
    try:
        for original in felder:
            feld = copy.deepcopy(original)
            seitenzahl = max(1, int(feld.get("seite") or 1))
            if seitenzahl > len(dokument):
                geaendert = True
                continue
            seite = dokument[seitenzahl - 1]
            schaetzung = _rechteck_aus_position(feld, seite)
            beispiel = str(feld.get("beispiel") or "").strip()
            treffer = _exakter_treffer(seite, beispiel, schaetzung) if beispiel else None

            if treffer is not None:
                alte_breite = float((feld.get("position") or {}).get("breite", 0) or 0)
                feld["position"] = _position(
                    fitz.Rect(max(0, treffer.x0 - 1), max(0, treffer.y0 - 1), min(seite.rect.width, treffer.x1 + 2), min(seite.rect.height, treffer.y1 + 2)),
                    seite,
                    mindestbreite=min(0.42, max(alte_breite, treffer.width / seite.rect.width)),
                )
                feld["positionsquelle"] = "beispieltext-exakt"
                feld["ursprungsbeispiel"] = beispiel
                geaendert = True
            elif beispiel and feld.get("geprueft") and not feld.get("standardwert"):
                # Frühere Versionen speicherten den gewünschten Wert fälschlich als
                # Suchtext. Er wird in das getrennte Standardwert-Feld migriert.
                feld["standardwert"] = beispiel
                feld["vorschauwert"] = beispiel
                feld["beispiel"] = str(feld.get("ursprungsbeispiel") or "")
                geaendert = True

            if _offensichtlich_falsch(feld, seite):
                geaendert = True
                continue
            bereinigt.append(feld)
    finally:
        dokument.close()

    eindeutig: list[dict[str, Any]] = []
    for feld in bereinigt:
        duplikat_index = next(
            (
                index
                for index, vorhanden in enumerate(eindeutig)
                if int(vorhanden.get("seite") or 1) == int(feld.get("seite") or 1)
                and _ueberlappung(vorhanden, feld) >= 0.62
            ),
            None,
        )
        if duplikat_index is None:
            eindeutig.append(feld)
            continue
        alt = eindeutig[duplikat_index]
        alt_score = (2 if alt.get("positionsquelle") == "beispieltext-exakt" else 0) + (1 if alt.get("beispiel") else 0)
        neu_score = (2 if feld.get("positionsquelle") == "beispieltext-exakt" else 0) + (1 if feld.get("beispiel") else 0)
        if neu_score > alt_score:
            eindeutig[duplikat_index] = feld
        geaendert = True

    daten["felder"] = eindeutig
    daten["positionspruefung"] = "pdf-verifiziert"
    return daten, geaendert


_URSPRUNG_LOKALE_KORREKTUR = _chat_jobs._lokale_korrektur
_URSPRUNG_LOKALE_ANALYSE = _analysis_flow._lokale_analyse


def _lokale_analyse_praezise(dateipfad: Path, dateiname: str):
    schema, diagnostik = _URSPRUNG_LOKALE_ANALYSE(dateipfad, dateiname)
    schema, geaendert = schema_positionen_schaerfen(schema, dateipfad)
    diagnostik = dict(diagnostik or {})
    diagnostik["positionspruefung"] = "pdf-verifiziert" if geaendert else "unveraendert"
    diagnostik["felder"] = len(schema.get("felder", []) or [])
    return schema, diagnostik


_chat_jobs._bestes_feld = _striktes_feld
_chat_jobs._lokale_korrektur = _lokale_korrektur_praezise
_analysis_flow._lokale_analyse = _lokale_analyse_praezise


def _alte_detailroute(route: Any) -> bool:
    return getattr(route, "path", None) == "/vorlagen/{vorlage_id}" and "GET" in (getattr(route, "methods", set()) or set())


app.router.routes[:] = [route for route in app.router.routes if not _alte_detailroute(route)]


@app.get("/vorlagen/{vorlage_id}", response_class=HTMLResponse)
def vorlage_editor_praezise(vorlage_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = aktuelles_mitglied(request, db)
    if not mitglied:
        return weiterleitung_anmeldung(request)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    schema, initialisiert = _workflow_v2._pflichtfelder_initial_optional(eintrag.schema)
    schema, geschaerft = schema_positionen_schaerfen(schema, Path(eintrag.speicherort))
    if initialisiert or geschaerft:
        eintrag.schema = schema
        eintrag.erkannte_felder = len(schema.get("felder", []) or [])
        db.commit()
    dialoge = db.scalars(
        select(Vorlagendialog)
        .where(Vorlagendialog.vorlage_id == eintrag.id)
        .order_by(Vorlagendialog.erstellt_am)
    ).all()
    kontext = grundkontext(request, db, "vorlagen")
    kontext.update({"eintrag": eintrag, "dialoge": dialoge})
    return vorlagen.TemplateResponse("vorlage_detail.html", kontext)


__all__ = ["_striktes_feld", "_lokale_korrektur_praezise", "schema_positionen_schaerfen"]
