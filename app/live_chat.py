from __future__ import annotations

import json
from typing import Any

from .config import einstellungen


PLAN_ANWEISUNG = """
Du steuerst einen Live-PDF-Editor. Du bekommst den extrahierten Text eines Dokuments, optionale Feldhinweise und genau eine Benutzeranweisung.

Deine einzige Aufgabe ist zu bestimmen, welcher bereits sichtbare Text ersetzt oder entfernt werden soll. Erfinde keine Positionen und schreibe das Dokument nicht um.

Antworte ausschließlich als JSON:
{
  "edits": [
    {
      "ziel": "kurze verständliche Bezeichnung",
      "alter_text": "EXAKT im Dokument vorkommender Text, buchstabengetreu",
      "neuer_text": "gewünschter neuer Text",
      "seite": 1
    }
  ],
  "antwort": "ein sehr kurzer deutscher Bestätigungssatz"
}

Regeln:
- alter_text muss exakt aus dem Dokumenttext kopiert sein. Niemals eine Feldbezeichnung als alter_text verwenden, wenn der Benutzer den Feldwert ändern will.
- Bei "employee address" / "Arbeitnehmer Anschrift" ist der aktuelle sichtbare Adresswert zu ersetzen, nicht der Name und nicht die Bezeichnung.
- Bei "employee name" / "Arbeitnehmer Name" ist ausschließlich der aktuelle Personenname zu ersetzen.
- Wenn die Anweisung mehrere konkrete Änderungen enthält, dürfen mehrere edits zurückkommen.
- Wenn keine sichere Zuordnung möglich ist, gib edits=[] zurück und bitte in antwort darum, den Text im Dokument anzuklicken.
- Keine Erklärungen außerhalb des JSON.
""".strip()


def _json(text: str) -> dict[str, Any]:
    sauber = text.strip()
    if sauber.startswith("```"):
        sauber = sauber.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    daten = json.loads(sauber)
    return daten if isinstance(daten, dict) else {"edits": [], "antwort": "Bitte klicken Sie den gewünschten Text im Dokument an."}


def ki_bearbeitungsplan(dokumenttext: str, hinweise: list[dict[str, Any]], nachricht: str) -> tuple[dict[str, Any], dict[str, int]]:
    cfg = einstellungen()
    if not cfg.openai_api_key:
        return {"edits": [], "antwort": "Bitte klicken Sie den gewünschten Text im Dokument an."}, {"eingabe": 0, "ausgabe": 0}

    from openai import OpenAI

    kompakte_hinweise = [
        {
            "bezeichnung": str(hinweis.get("bezeichnung") or ""),
            "beispiel": str(hinweis.get("beispiel") or ""),
            "seite": int(hinweis.get("seite") or 1),
        }
        for hinweis in hinweise[:80]
        if hinweis.get("bezeichnung") or hinweis.get("beispiel")
    ]
    text = dokumenttext[:18000]
    client = OpenAI(api_key=cfg.openai_api_key, timeout=8.0, max_retries=0)
    antwort = client.responses.create(
        model=cfg.openai_model,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            f"{PLAN_ANWEISUNG}\n\n"
                            f"Feldhinweise:\n{json.dumps(kompakte_hinweise, ensure_ascii=False)}\n\n"
                            f"Dokumenttext:\n{text}\n\n"
                            f"Benutzeranweisung:\n{nachricht}"
                        ),
                    }
                ],
            }
        ],
    )
    plan = _json(antwort.output_text)
    nutzung = getattr(antwort, "usage", None)
    return plan, {
        "eingabe": int(getattr(nutzung, "input_tokens", 0) or 0),
        "ausgabe": int(getattr(nutzung, "output_tokens", 0) or 0),
    }


__all__ = ["ki_bearbeitungsplan"]
