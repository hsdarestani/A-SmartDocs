from __future__ import annotations

import io
from pathlib import Path

import fitz
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.database import Sitzung
from app.live_document_engine import pdf_index
from app.models import Arbeitsdokument


DEMO_EMAIL = "demo@smartdocs.de"
DEMO_PASSWORT = "Aplus-Kunde-7Qm!26"


def _anmelden(client) -> None:
    antwort = client.post(
        "/anmelden",
        data={"email": DEMO_EMAIL, "passwort": DEMO_PASSWORT, "weiter": "/arbeitsbereich"},
        follow_redirects=False,
    )
    assert antwort.status_code == 303


def _pdf_bytes() -> bytes:
    stream = io.BytesIO()
    c = canvas.Canvas(stream, pagesize=A4)
    c.setFont("Helvetica", 11)
    c.drawString(70, 735, "Vereinbarung zur Wiederaufnahme eines beendeten Arbeitsverhältnisses")
    c.drawString(70, 690, "A+ Solution GmbH, Carl-Sonnenschein-Str. 57, 65936 Frankfurt am Main")
    c.drawString(70, 655, "Perla Demirova, An der Zingelswiese 5, 65933 FFM")
    c.drawString(70, 610, "Beginn: 13.06.2026")
    c.save()
    return stream.getvalue()


def _upload(client) -> int:
    antwort = client.post(
        "/api/workspace/upload",
        files={"datei": ("wiederaufnahme.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert daten["weiter"].startswith("/workspace/")
    return int(daten["arbeitsdokument_id"])


def _anker(entwurf_id: int, fragment: str):
    with Sitzung() as db:
        entwurf = db.get(Arbeitsdokument, entwurf_id)
        assert entwurf is not None
        index = pdf_index(Path(entwurf.speicherort))
    for seite in index["seiten"]:
        for anker in seite["anker"]:
            if fragment in anker["text"]:
                return anker
    raise AssertionError(f"Anker {fragment!r} fehlt")


def test_startseite_ist_nur_upload_chat_export_statt_dashboard(client):
    _anmelden(client)
    antwort = client.get("/arbeitsbereich")
    assert antwort.status_code == 200
    text = antwort.text
    assert "PDF rein." in text
    assert "PDF hier ablegen" in text
    assert "Upload" in text and "Chat" in text and "PDF" in text
    assert "Monatliche Nutzung" not in text
    assert "Teammitglieder" not in text
    assert "Vorlage einrichten" not in text


def test_upload_oeffnet_sofort_editor_ohne_bestaetigungsstufen(client):
    _anmelden(client)
    entwurf_id = _upload(client)
    antwort = client.get(f"/workspace/{entwurf_id}")
    assert antwort.status_code == 200
    text = antwort.text
    assert "Was soll geändert werden?" in text
    assert "PDF herunterladen" in text
    assert "Text anklicken" in text
    assert "Testausfüllung" not in text
    assert "Vorlage fertigstellen" not in text
    assert "Bestätige alle plausiblen" not in text


def test_klickbearbeitung_ist_direkt_und_export_entfernt_alten_text(client):
    _anmelden(client)
    entwurf_id = _upload(client)
    anker = _anker(entwurf_id, "Perla Demirova")

    antwort = client.post(
        f"/api/workspace/{entwurf_id}/edit",
        json={"nachricht": "Maria Keller, Mainzer Landstraße 12, 60329 Frankfurt", "anker_id": anker["id"]},
    )
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert daten["erfolg"] is True
    assert daten["modus"] == "auswahl"
    assert daten["dauer_ms"] < 1500
    assert daten["seiten"] == [1]

    vorschau = client.get(f"/workspace/{entwurf_id}/seiten/1.png?rev={daten['revision']}")
    assert vorschau.status_code == 200
    assert vorschau.headers["content-type"].startswith("image/png")
    assert len(vorschau.content) > 1000

    export = client.post(f"/api/workspace/{entwurf_id}/export")
    assert export.status_code == 200, export.text
    download = client.get(export.json()["download_url"])
    assert download.status_code == 200
    dokument = fitz.open(stream=download.content, filetype="pdf")
    try:
        text = "\n".join(seite.get_text("text") for seite in dokument)
    finally:
        dokument.close()
    assert "Perla Demirova" not in text
    assert "Maria Keller" in text


def test_einfache_chat_anweisung_braucht_keine_ki(client):
    _anmelden(client)
    entwurf_id = _upload(client)
    antwort = client.post(
        f"/api/workspace/{entwurf_id}/edit",
        json={"nachricht": "13.06.2026 → 01.08.2026"},
    )
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert daten["erfolg"] is True
    assert daten["modus"] == "lokal"
    assert daten["dauer_ms"] < 1500

    export = client.post(f"/api/workspace/{entwurf_id}/export")
    assert export.status_code == 200
    pdf = client.get(export.json()["download_url"])
    dokument = fitz.open(stream=pdf.content, filetype="pdf")
    try:
        text = "\n".join(seite.get_text("text") for seite in dokument)
    finally:
        dokument.close()
    assert "13.06.2026" not in text
    assert "01.08.2026" in text


def test_semantische_adresse_nutzt_hint_aber_nicht_hint_position(client):
    _anmelden(client)
    entwurf_id = _upload(client)
    with Sitzung() as db:
        entwurf = db.get(Arbeitsdokument, entwurf_id)
        assert entwurf is not None
        zustand = dict(entwurf.zustand or {})
        zustand["hinweise"] = [
            {
                "schluessel": "arbeitnehmer_anschrift",
                "bezeichnung": "Arbeitnehmer Anschrift",
                "beispiel": "Perla Demirova, An der Zingelswiese 5, 65933 FFM",
                "seite": 1,
                "position": {"x": 0.01, "y": 0.01, "breite": 0.01, "hoehe": 0.01},
            }
        ]
        entwurf.zustand = zustand
        db.commit()

    antwort = client.post(
        f"/api/workspace/{entwurf_id}/edit",
        json={"nachricht": "employee address is Maria Keller, Mainzer Landstraße 12, 60329 Frankfurt"},
    )
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert daten["erfolg"] is True
    assert daten["modus"] == "lokal"
    assert daten["edits"][0]["alter_text"].startswith("Perla Demirova")


def test_undo_und_verlauf_bleiben_sekundaere_funktionen(client):
    _anmelden(client)
    entwurf_id = _upload(client)
    antwort = client.post(f"/api/workspace/{entwurf_id}/edit", json={"nachricht": "13.06.2026 → 01.08.2026"})
    assert antwort.status_code == 200 and antwort.json()["erfolg"] is True
    undo = client.post(f"/api/workspace/{entwurf_id}/undo")
    assert undo.status_code == 200
    export = client.post(f"/api/workspace/{entwurf_id}/export")
    assert export.status_code == 200
    verlauf = client.get("/verlauf")
    assert verlauf.status_code == 200
    assert "Direkte PDF-Ausgaben" in verlauf.text
    assert "wiederaufnahme" in verlauf.text.lower()
