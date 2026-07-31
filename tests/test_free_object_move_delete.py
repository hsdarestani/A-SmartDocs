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


def _pdf() -> bytes:
    stream = io.BytesIO()
    c = canvas.Canvas(stream, pagesize=A4)
    c.setFont("Helvetica", 11)
    c.drawString(70, 735, "Personalfragebogen")
    c.drawString(70, 690, "Vorname")
    c.line(70, 665, 280, 665)
    c.drawString(320, 690, "Nachname")
    c.line(320, 665, 520, 665)
    c.save()
    return stream.getvalue()


def _upload(client) -> int:
    antwort = client.post(
        "/api/workspace/upload",
        files={"datei": ("move-delete.pdf", _pdf(), "application/pdf")},
    )
    assert antwort.status_code == 200, antwort.text
    return int(antwort.json()["arbeitsdokument_id"])


def _export_pdf(client, entwurf_id: int) -> fitz.Document:
    export = client.post(f"/api/workspace/{entwurf_id}/export")
    assert export.status_code == 200, export.text
    datei = client.get(export.json()["download_url"])
    assert datei.status_code == 200
    return fitz.open(stream=datei.content, filetype="pdf")


def test_freier_text_wird_mit_gleicher_id_verschoben(client):
    _anmelden(client)
    entwurf_id = _upload(client)
    erstellt = client.post(
        f"/api/workspace/{entwurf_id}/edit",
        json={"nachricht": "Hossein", "seite": 1, "x": 0.14, "y": 0.22},
    )
    assert erstellt.status_code == 200, erstellt.text
    edit = erstellt.json()["edits"][0]
    edit_id = edit["id"]
    alte_bbox = edit["bbox"]

    verschoben = client.post(
        f"/api/workspace/{entwurf_id}/free-object",
        json={"aktion": "verschieben", "edit_id": edit_id, "seite": 1, "x": 0.61, "y": 0.52},
    )
    assert verschoben.status_code == 200, verschoben.text
    daten = verschoben.json()
    assert daten["aktion"] == "verschieben"
    assert daten["edit"]["id"] == edit_id
    assert daten["edit"]["bbox"] != alte_bbox
    assert daten["edit"]["bbox"][0] > 300
    assert daten["edit"]["bbox"][1] > 400

    dokument = _export_pdf(client, entwurf_id)
    try:
        treffer = dokument[0].search_for("Hossein")
        assert len(treffer) == 1
        assert treffer[0].x0 > 300
        assert treffer[0].y0 > 400
    finally:
        dokument.close()


def test_freier_text_kann_geloescht_werden(client):
    _anmelden(client)
    entwurf_id = _upload(client)
    erstellt = client.post(
        f"/api/workspace/{entwurf_id}/edit",
        json={"nachricht": "NurZumLoeschen", "seite": 1, "x": 0.25, "y": 0.32},
    )
    assert erstellt.status_code == 200, erstellt.text
    edit_id = erstellt.json()["edits"][0]["id"]

    geloescht = client.post(
        f"/api/workspace/{entwurf_id}/free-object",
        json={"aktion": "loeschen", "edit_id": edit_id},
    )
    assert geloescht.status_code == 200, geloescht.text
    assert geloescht.json()["deleted_id"] == edit_id
    assert geloescht.json()["aktion"] == "loeschen"

    dokument = _export_pdf(client, entwurf_id)
    try:
        text = "\n".join(seite.get_text("text") for seite in dokument)
        assert "NurZumLoeschen" not in text
        assert "Personalfragebogen" in text
    finally:
        dokument.close()


def test_editor_zeigt_drag_und_loeschen_fuer_freie_felder(client):
    _anmelden(client)
    entwurf_id = _upload(client)
    seite = client.get(f"/workspace/{entwurf_id}")
    assert seite.status_code == 200
    assert "live-empty-position.js') }}?v=20260731-4" not in seite.text  # Jinja ist gerendert.
    assert "live-empty-position.js?v=20260731-4" in seite.text
    assert "live-interaction-fix.css?v=20260731-4" in seite.text

    js = client.get("/statisch/live-empty-position.js")
    assert js.status_code == 200
    assert "verschieben" in js.text
    assert "live-free-delete" in js.text
    assert "pointermove" in js.text
    assert "Delete" in js.text

    css = client.get("/statisch/live-interaction-fix.css")
    assert css.status_code == 200
    assert "cursor:grab" in css.text
    assert ".live-free-value.dragging" in css.text
