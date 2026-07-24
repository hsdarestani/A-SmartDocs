from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import einstellungen


ANALYSE_ANWEISUNG = """
Du analysierst Geschäftsdokumente für A+ SmartDocs. Erkenne, welche Inhalte einer hochgeladenen Vorlage bei späterer Wiederverwendung variabel sein sollen. Berücksichtige Textfelder, Daten, Beträge, Anschriften, Tabellen, Auswahlfelder, Kontrollkästchen, Unterschriften, Bilder und wiederholbare Bereiche.

Antworte ausschließlich als gültiges JSON mit dieser Struktur:
{
  "dokumentart": "kurze deutsche Bezeichnung",
  "zusammenfassung": "höchstens zwei deutsche Sätze",
  "felder": [
    {
      "schluessel": "maschinenlesbarer_schluessel",
      "bezeichnung": "deutsche Feldbezeichnung",
      "typ": "text|mehrzeilig|datum|zahl|betrag|auswahl|kontrollfeld|unterschrift|bild|bilderliste|tabelle",
      "pflichtfeld": true,
      "beispiel": "erkannter Beispielinhalt oder leer",
      "seite": 1,
      "hinweis": "kurze Erklärung",
      "optionen": [],
      "position": {"x": 0.10, "y": 0.20, "breite": 0.35, "hoehe": 0.035},
      "schriftgroesse": 10
    }
  ],
  "rueckfragen": ["nur Fragen, die für eine sichere Vorlagenerstellung nötig sind"]
}

Positionswerte sind normalisierte Werte von 0 bis 1, gemessen vom linken oberen Seitenrand. Schätze die sichtbare Position so genau wie möglich, damit später neuer Inhalt über den bisherigen Beispielinhalt gelegt werden kann. Sei vorsichtig: Markiere nicht jeden Text als variabel. Firmenlogo, Überschriften, rechtliche Standardtexte und Layoutbestandteile sind in der Regel fest. Alle sichtbaren Texte deiner Antwort müssen deutsch sein.
""".strip()


KORREKTUR_ANWEISUNG = """
Du bist der deutschsprachige Vorlagenassistent von A+ SmartDocs. Du erhältst ein bestehendes Vorlagenschema und eine Änderungsanweisung des Benutzers. Aktualisiere das Schema exakt nach der Anweisung. Bewahre nicht betroffene Felder und deren Positionen. Antworte ausschließlich als gültiges JSON in derselben Struktur. Alle Bezeichnungen, Hinweise, Zusammenfassungen und Rückfragen müssen deutsch sein.
""".strip()


def _client():
    from openai import OpenAI

    cfg = einstellungen()
    if not cfg.openai_api_key:
        raise RuntimeError("Für die Dokumentanalyse ist noch kein KI-Schlüssel hinterlegt.")
    return OpenAI(api_key=cfg.openai_api_key)


def _json_aus_text(text: str) -> dict[str, Any]:
    bereinigt = text.strip()
    if bereinigt.startswith("```"):
        bereinigt = bereinigt.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(bereinigt)


def dokument_analysieren(dateipfad: Path, dateiname: str) -> tuple[dict[str, Any], dict[str, int]]:
    client = _client()
    hochgeladen = client.files.create(file=(dateiname, dateipfad.read_bytes()), purpose="user_data")
    try:
        antwort = client.responses.create(
            model=einstellungen().openai_model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": ANALYSE_ANWEISUNG},
                        {"type": "input_file", "file_id": hochgeladen.id},
                    ],
                }
            ],
        )
        schema = _json_aus_text(antwort.output_text)
        nutzung = getattr(antwort, "usage", None)
        werte = {
            "eingabe": int(getattr(nutzung, "input_tokens", 0) or 0),
            "ausgabe": int(getattr(nutzung, "output_tokens", 0) or 0),
        }
        return schema, werte
    finally:
        try:
            client.files.delete(hochgeladen.id)
        except Exception:
            pass


def schema_korrigieren(schema: dict[str, Any], nachricht: str) -> tuple[dict[str, Any], dict[str, int]]:
    client = _client()
    antwort = client.responses.create(
        model=einstellungen().openai_model,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"{KORREKTUR_ANWEISUNG}\n\nBisheriges Schema:\n{json.dumps(schema, ensure_ascii=False)}\n\nÄnderungswunsch:\n{nachricht}",
                    }
                ],
            }
        ],
    )
    neues_schema = _json_aus_text(antwort.output_text)
    nutzung = getattr(antwort, "usage", None)
    werte = {
        "eingabe": int(getattr(nutzung, "input_tokens", 0) or 0),
        "ausgabe": int(getattr(nutzung, "output_tokens", 0) or 0),
    }
    return neues_schema, werte
