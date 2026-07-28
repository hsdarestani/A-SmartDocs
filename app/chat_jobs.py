from __future__ import annotations

import copy
import re
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import BackgroundTasks, Depends, HTTPException, Request

from .ai import schema_korrigieren
from .database import Sitzung, datenbank_sitzung
from .main import KorrekturEingabe, app, muss_angemeldet_sein, vorlage_fuer_mitglied
from .models import Dokumentvorlage, Nutzungsereignis, Vorlagendialog
from .quality import schema_mit_qualitaet


_AUFTRAGSSCHLUESSEL = "_chat_auftrag"


def _jetzt() -> datetime:
    return datetime.now(timezone.utc)


def _iso_lesen(wert: Any) -> datetime | None:
    if not wert:
        return None
    try:
        datum = datetime.fromisoformat(str(wert))
    except ValueError:
        return None
    if datum.tzinfo is None:
        datum = datum.replace(tzinfo=timezone.utc)
    return datum.astimezone(timezone.utc)


def _schema_ohne_auftrag(schema: dict[str, Any] | None) -> dict[str, Any]:
    daten = copy.deepcopy(schema or {})
    daten.pop(_AUFTRAGSSCHLUESSEL, None)
    return daten


def _auftrag(schema: dict[str, Any] | None) -> dict[str, Any]:
    wert = (schema or {}).get(_AUFTRAGSSCHLUESSEL, {})
    return dict(wert) if isinstance(wert, dict) else {}


def _mit_auftrag(schema: dict[str, Any] | None, auftrag: dict[str, Any]) -> dict[str, Any]:
    daten = copy.deepcopy(schema or {})
    daten[_AUFTRAGSSCHLUESSEL] = auftrag
    return daten


def _normalisieren(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(zeichen for zeichen in text if not unicodedata.combining(zeichen))
    text = text.replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


_SYNONYME = {
    "firmname": "firmenname",
    "company": "firmenname",
    "companyname": "firmenname",
    "unternehmen": "firmenname",
    "arbeitgeber": "arbeitgeber",
    "employer": "arbeitgeber",
    "address": "anschrift",
    "adresse": "anschrift",
    "street": "anschrift",
    "strasse": "anschrift",
    "employee": "arbeitnehmer",
    "worker": "arbeitnehmer",
    "name": "name",
    "date": "datum",
    "signature": "unterschrift",
    "signatur": "unterschrift",
}


def _tokens(text: str) -> set[str]:
    stop = {"der", "die", "das", "den", "dem", "des", "ein", "eine", "von", "fur", "für", "the", "of", "field", "feld"}
    ergebnis: set[str] = set()
    for token in _normalisieren(text).split():
        if token in stop:
            continue
        ergebnis.add(_SYNONYME.get(token, token))
    return ergebnis


def _bestes_feld(felder: list[dict[str, Any]], suchtext: str) -> tuple[int, dict[str, Any]] | None:
    gesucht = _tokens(suchtext)
    if not gesucht:
        return None
    bestes: tuple[float, int, dict[str, Any]] | None = None
    normaler_suchtext = _normalisieren(suchtext)
    for index, feld in enumerate(felder):
        beschreibung = f"{feld.get('bezeichnung', '')} {feld.get('schluessel', '')}"
        vorhanden = _tokens(beschreibung)
        gemeinsam = len(gesucht & vorhanden)
        score = gemeinsam / max(1, len(gesucht))
        normaler_feldtext = _normalisieren(beschreibung)
        if normaler_suchtext and normaler_suchtext in normaler_feldtext:
            score += 0.75
        if any(token in normaler_feldtext for token in gesucht):
            score += 0.25
        if bestes is None or score > bestes[0]:
            bestes = (score, index, feld)
    if not bestes or bestes[0] < 0.45:
        return None
    return bestes[1], bestes[2]


def _lokale_korrektur(schema: dict[str, Any], nachricht: str) -> tuple[dict[str, Any], str] | None:
    """Erledigt häufige, eindeutige Änderungen sofort und ohne KI-Rundreise."""
    daten = copy.deepcopy(schema)
    felder = list(daten.get("felder", []) or [])
    normal = _normalisieren(nachricht)

    zuweisung = re.match(r"^(.+?)\s+(?:ist|is|=|soll(?:te)?\s+sein)\s+(.+?)\s*[.!]?$", nachricht.strip(), re.IGNORECASE)
    if zuweisung:
        zieltext, wert = zuweisung.group(1).strip(), zuweisung.group(2).strip()
        treffer = _bestes_feld(felder, zieltext)
        if treffer and wert:
            index, feld = treffer
            feld = dict(feld)
            feld["beispiel"] = wert
            feld["alten_inhalt_entfernen"] = True
            feld["vorschlag_status"] = "bestaetigt"
            feld["geprueft"] = True
            feld["konfidenz"] = 1
            feld["konfidenzstufe"] = "sicher"
            felder[index] = feld
            daten["felder"] = felder
            return daten, f"„{feld.get('bezeichnung', 'Feld')}“ wurde auf „{wert}“ gesetzt."

    if any(wort in normal for wort in {"entferne", "losche", "nicht variabel"}):
        zieltext = re.sub(r"\b(entferne|lösche|losche|mach|ist|soll|nicht|variabel)\b", " ", nachricht, flags=re.IGNORECASE)
        treffer = _bestes_feld(felder, zieltext)
        if treffer:
            index, feld = treffer
            felder.pop(index)
            daten["felder"] = felder
            return daten, f"„{feld.get('bezeichnung', 'Feld')}“ bleibt fest und wurde entfernt."

    if "variabel" in normal:
        zieltext = re.sub(r"\b(ist|sind|soll|sollen|variabel|machen|mach)\b", " ", nachricht, flags=re.IGNORECASE)
        teile = [teil.strip() for teil in re.split(r"\s+und\s+|,", zieltext, flags=re.IGNORECASE) if teil.strip()]
        geaendert: list[str] = []
        for teil in teile:
            treffer = _bestes_feld(felder, teil)
            if not treffer:
                continue
            index, feld = treffer
            feld = dict(feld)
            feld["vorschlag_status"] = "bestaetigt"
            feld["geprueft"] = True
            feld["konfidenz"] = 1
            feld["konfidenzstufe"] = "sicher"
            felder[index] = feld
            geaendert.append(str(feld.get("bezeichnung") or "Feld"))
        if geaendert:
            daten["felder"] = felder
            return daten, f"Als variabel bestätigt: {', '.join(dict.fromkeys(geaendert))}."

    if "alles plausible" in normal or "plausiblen vorschlage" in normal:
        geaendert = 0
        for index, original in enumerate(felder):
            if str(original.get("konfidenzstufe") or "") == "unsicher":
                continue
            feld = dict(original)
            feld["vorschlag_status"] = "bestaetigt"
            feld["geprueft"] = True
            felder[index] = feld
            geaendert += 1
        daten["felder"] = felder
        return daten, f"{geaendert} plausible Felder wurden übernommen. Unsichere Felder bleiben zur Prüfung markiert."

    if "unsicher" in normal and any(wort in normal for wort in {"zeige", "prufe", "prüfe"}):
        return daten, "Unsichere Felder bleiben im Dokument markiert. Klicken Sie nur diese Felder zur Prüfung an."

    return None


def _korrektur_abschliessen(vorlage_id: int, auftrag_id: str, nachricht: str) -> None:
    with Sitzung() as db:
        eintrag = db.get(Dokumentvorlage, vorlage_id)
        if not eintrag:
            return
        aktueller_auftrag = _auftrag(eintrag.schema)
        if aktueller_auftrag.get("id") != auftrag_id:
            return
        grundschema = _schema_ohne_auftrag(eintrag.schema)
        organisation_id = eintrag.organisation_id

    nutzung: dict[str, int] = {"eingabe": 0, "ausgabe": 0}
    antwort = ""
    try:
        lokal = _lokale_korrektur(grundschema, nachricht)
        if lokal:
            neues_schema, antwort = lokal
            nutzung["lokal"] = 1
        else:
            letzter_fehler: Exception | None = None
            for versuch in range(2):
                try:
                    neues_schema, ki_nutzung = schema_korrigieren(grundschema, nachricht)
                    nutzung.update(ki_nutzung)
                    break
                except Exception as exc:  # pragma: no cover - externer Dienst
                    letzter_fehler = exc
                    if versuch == 0:
                        time.sleep(2)
            else:
                raise letzter_fehler or RuntimeError("Die KI-Korrektur konnte nicht abgeschlossen werden.")
            antwort = "Die Änderung wurde übernommen. Prüfen Sie kurz die aktualisierten Markierungen."

        neues_schema = schema_mit_qualitaet(neues_schema)
        neues_schema["pflichtfelder_initialisiert"] = bool(grundschema.get("pflichtfelder_initialisiert", True))
        neues_schema["testausfuellung_geprueft"] = False
        neues_schema["testausfuellung_hash"] = None
        auftrag = {
            "id": auftrag_id,
            "status": "fertig",
            "nachricht": nachricht,
            "antwort": antwort,
            "aktualisiert_am": _jetzt().isoformat(),
        }
        neues_schema = _mit_auftrag(neues_schema, auftrag)

        with Sitzung() as db:
            eintrag = db.get(Dokumentvorlage, vorlage_id)
            if not eintrag or _auftrag(eintrag.schema).get("id") != auftrag_id:
                return
            eintrag.schema = neues_schema
            eintrag.erkannte_felder = len(neues_schema.get("felder", []) or [])
            eintrag.zusammenfassung = str(neues_schema.get("zusammenfassung", eintrag.zusammenfassung))
            eintrag.aktualisiert_am = _jetzt()
            db.add(Vorlagendialog(vorlage_id=eintrag.id, rolle="assistent", nachricht=antwort))
            kosten = round(
                (int(nutzung.get("eingabe", 0)) * 0.0000004)
                + (int(nutzung.get("ausgabe", 0)) * 0.0000016),
                4,
            )
            db.add(
                Nutzungsereignis(
                    organisation_id=organisation_id,
                    art="vorlage_korrigiert",
                    menge=1,
                    kosten_euro=Decimal(str(kosten)),
                    einzelheiten={**nutzung, "auftrag_id": auftrag_id},
                )
            )
            db.commit()
    except Exception:
        antwort = (
            "Die automatische Bearbeitung war gerade nicht erreichbar. Ihre Vorlage und Ihre bisherigen "
            "Änderungen bleiben erhalten; Sie können währenddessen den manuellen Modus verwenden."
        )
        with Sitzung() as db:
            eintrag = db.get(Dokumentvorlage, vorlage_id)
            if not eintrag or _auftrag(eintrag.schema).get("id") != auftrag_id:
                return
            schema = _schema_ohne_auftrag(eintrag.schema)
            schema = _mit_auftrag(
                schema,
                {
                    "id": auftrag_id,
                    "status": "fehler",
                    "nachricht": nachricht,
                    "antwort": antwort,
                    "aktualisiert_am": _jetzt().isoformat(),
                },
            )
            eintrag.schema = schema
            eintrag.aktualisiert_am = _jetzt()
            db.add(Vorlagendialog(vorlage_id=eintrag.id, rolle="assistent", nachricht=antwort))
            db.commit()


@app.post("/api/vorlagen/korrigieren-async", status_code=202)
def korrektur_starten(
    eingabe: KorrekturEingabe,
    request: Request,
    background_tasks: BackgroundTasks,
    db=Depends(datenbank_sitzung),
):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = vorlage_fuer_mitglied(db, mitglied, eingabe.vorlage_id)
    if not eintrag.schema:
        raise HTTPException(status_code=409, detail="Für diese Vorlage liegt noch kein Feldschema vor.")

    vorhanden = _auftrag(eintrag.schema)
    begonnen = _iso_lesen(vorhanden.get("aktualisiert_am") or vorhanden.get("erstellt_am"))
    if vorhanden.get("status") == "laeuft" and begonnen and begonnen > _jetzt() - timedelta(minutes=3):
        auftrag_id = str(vorhanden.get("id"))
        return {
            "erfolg": True,
            "auftrag_id": auftrag_id,
            "status": "laeuft",
            "status_url": f"/api/vorlagen/{eintrag.id}/korrektur-status/{auftrag_id}",
            "hinweis": "Die laufende Änderung wird weiter verarbeitet.",
        }

    auftrag_id = uuid.uuid4().hex
    zeit = _jetzt().isoformat()
    schema = _mit_auftrag(
        eintrag.schema,
        {
            "id": auftrag_id,
            "status": "laeuft",
            "nachricht": eingabe.nachricht,
            "antwort": "",
            "erstellt_am": zeit,
            "aktualisiert_am": zeit,
        },
    )
    eintrag.schema = schema
    eintrag.aktualisiert_am = _jetzt()
    db.add(Vorlagendialog(vorlage_id=eintrag.id, rolle="nutzer", nachricht=eingabe.nachricht))
    db.commit()

    background_tasks.add_task(_korrektur_abschliessen, eintrag.id, auftrag_id, eingabe.nachricht)
    return {
        "erfolg": True,
        "auftrag_id": auftrag_id,
        "status": "laeuft",
        "status_url": f"/api/vorlagen/{eintrag.id}/korrektur-status/{auftrag_id}",
        "hinweis": "Die Änderung wird im Hintergrund verarbeitet.",
    }


@app.get("/api/vorlagen/{vorlage_id}/korrektur-status/{auftrag_id}")
def korrektur_status(
    vorlage_id: int,
    auftrag_id: str,
    request: Request,
    db=Depends(datenbank_sitzung),
):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = vorlage_fuer_mitglied(db, mitglied, vorlage_id)
    auftrag = _auftrag(eintrag.schema)
    if auftrag.get("id") != auftrag_id:
        raise HTTPException(status_code=404, detail="Dieser Änderungsauftrag wurde nicht gefunden.")

    status = str(auftrag.get("status") or "laeuft")
    gestartet = _iso_lesen(auftrag.get("erstellt_am") or auftrag.get("aktualisiert_am"))
    if status == "laeuft" and gestartet and gestartet < _jetzt() - timedelta(minutes=3):
        status = "fehler"
        antwort = "Die Bearbeitung wurde unterbrochen. Ihre bisherigen Änderungen bleiben vollständig erhalten."
        schema = _schema_ohne_auftrag(eintrag.schema)
        schema = _mit_auftrag(schema, {**auftrag, "status": status, "antwort": antwort, "aktualisiert_am": _jetzt().isoformat()})
        eintrag.schema = schema
        eintrag.aktualisiert_am = _jetzt()
        db.add(Vorlagendialog(vorlage_id=eintrag.id, rolle="assistent", nachricht=antwort))
        db.commit()
        auftrag = _auftrag(schema)

    return {
        "erfolg": True,
        "auftrag_id": auftrag_id,
        "status": status,
        "fertig": status == "fertig",
        "fehler": status == "fehler",
        "antwort": str(auftrag.get("antwort") or ""),
        "schema": _schema_ohne_auftrag(eintrag.schema) if status == "fertig" else None,
    }


__all__ = ["_lokale_korrektur", "_korrektur_abschliessen"]
