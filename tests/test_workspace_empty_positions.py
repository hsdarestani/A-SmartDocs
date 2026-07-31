from __future__ import annotations

import io

import fitz
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


DEMO_EMAIL = "demo@smartdocs.de"
DEMO_PASSWORT = "Aplus-Kunde-7Qm!26"


def _anmelden(client) -> None:
    antwort = client.post(
        "/anmelden",
        data={"email": DEMO_EMAIL, "passwort": DEMO_PASSWORT, "weiter": "/arbeitsbereich"},
        follow_redirects=False,
    )
    assert antwort.status_code == 303


def _pdf_mit_leerem_feld() -> bytes:
    stream = io.BytesIO()
    c = canvas.Canvas(stream, pagesize=A4)
    c.setFont("Helvetica", 11)
    c.drawString(70, 735, "Personalfragebogen")
    c.drawString(70, 690, "Vorname")
    c.line(70, 665, 280, 665)
    c.drawString(320, 690, "Nachname")
    c.line(320, 665, 520, 665)
    c.drawString(70, 610, "Adresse")
    c.line(70, 585, 520, 585)
    c.save()
    return stream.getvalue()


def _upload(client) -> int:
    antwort = client.post(
        "/api/workspace/upload",
        files={"datei": ("leerfelder.pdf", _pdf_mit_leerem_feld(), "application/pdf")},
    )
    assert antwort.status_code == 200, antwort.text
    return int(antwort.json()["arbeitsdokument_id"])


def test_freie_position_kann_ohne_vorhandenen_text_beschrieben_werden(client):
    _anmelden(client)
    entwurf_id = _upload(client)
    antwort = client.post(
        f"/api/workspace/{entwurf_id}/edit",
        json={"nachricht": "Hossein", "seite": 1, "x": 0.13, "y": 0.19},
    )
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert daten["erfolg"] is True
    assert daten["modus"] == "freie-position"
    assert daten["seiten"] == [1]
    assert daten["edits"][0]["alter_text"] == ""

    export = client.post(f"/api/workspace/{entwurf_id}/export")
    assert export.status_code == 200, export.text
    pdf = client.get(export.json()["download_url"])
    assert pdf.status_code == 200
    dokument = fitz.open(stream=pdf.content, filetype="pdf")
    try:
        text = "\n".join(seite.get_text("text") for seite in dokument)
    finally:
        dokument.close()
    assert "Hossein" in text
    assert "Vorname" in text
    assert "Nachname" in text
    assert "Adresse" in text


def test_freie_position_wird_auch_in_der_live_vorschau_gerendert(client):
    _anmelden(client)
    entwurf_id = _upload(client)
    edit = client.post(
        f"/api/workspace/{entwurf_id}/edit",
        json={"nachricht": "Darestani", "seite": 1, "x": 0.56, "y": 0.19},
    )
    assert edit.status_code == 200
    preview = client.get(f"/workspace/{entwurf_id}/seiten/1.png?rev={edit.json()['revision']}")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/png")
    assert len(preview.content) > 1000


def test_editor_bindet_scroll_und_leerstellen_fixes_ein(client):
    _anmelden(client)
    entwurf_id = _upload(client)
    seite = client.get(f"/workspace/{entwurf_id}")
    assert seite.status_code == 200
    assert "freie Stelle anklicken" in seite.text
    assert "live-interaction-fix.css" in seite.text
    assert "live-scroll-fix.js" in seite.text
    assert "live-empty-position.js" in seite.text

    scroll_js = client.get("/statisch/live-scroll-fix.js")
    assert scroll_js.status_code == 200
    assert "scrollTop" in scroll_js.text
    assert "requestAnimationFrame" in scroll_js.text

    css = client.get("/statisch/live-interaction-fix.css")
    assert css.status_code == 200
    assert "min-height:0" in css.text
    assert "pointer-events:auto" in css.text
