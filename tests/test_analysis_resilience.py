from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.routing import APIRoute
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select

from app.database import Sitzung
from app.main import cfg
from app.models import Dokumentvorlage, Mitglied


DEMO_EMAIL = "demo@smartdocs.de"
DEMO_PASSWORT = "Aplus-Kunde-7Qm!26"


def _anmelden(client) -> None:
    antwort = client.post(
        "/anmelden",
        data={"email": DEMO_EMAIL, "passwort": DEMO_PASSWORT, "weiter": "/arbeitsbereich"},
        follow_redirects=False,
    )
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/arbeitsbereich"


def _pdf_bytes(text: str = "Robuste Analyse") -> bytes:
    speicher = io.BytesIO()
    zeichner = canvas.Canvas(speicher, pagesize=A4)
    zeichner.drawString(72, 760, text)
    zeichner.save()
    return speicher.getvalue()


def _vorlage_loeschen(vorlage_id: int) -> None:
    with Sitzung() as db:
        eintrag = db.get(Dokumentvorlage, vorlage_id)
        if not eintrag:
            return
        pfad = Path(eintrag.speicherort)
        db.delete(eintrag)
        db.commit()
        pfad.unlink(missing_ok=True)


def test_nur_die_entkoppelte_analyseroute_ist_registriert(client):
    routen = [
        route
        for route in client.app.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/vorlagen/analysieren"
        and "POST" in route.methods
    ]
    assert len(routen) == 1
    assert routen[0].endpoint.__name__ == "vorlage_analysieren_robust"


def test_upload_liefert_202_und_statusabfrage_bleibt_verwendbar(client):
    _anmelden(client)
    name = f"Analyse {uuid.uuid4().hex[:8]}"
    antwort = client.post(
        "/api/vorlagen/analysieren",
        data={"name": name},
        files={"datei": ("analyse.pdf", _pdf_bytes(), "application/pdf")},
        follow_redirects=False,
    )
    assert antwort.status_code == 202
    daten = antwort.json()
    assert daten["vorlage_id"]
    assert daten["status_url"].endswith("/analyse-status")
    vorlage_id = int(daten["vorlage_id"])

    try:
        status = client.get(daten["status_url"])
        assert status.status_code == 200
        statusdaten = status.json()
        # Im Test ist kein externer KI-Schlüssel gesetzt. Deshalb muss die sichere,
        # bearbeitbare Grundstruktur den Lauf trotzdem erfolgreich abschließen.
        assert statusdaten["fertig"] is True
        assert statusdaten["fehler"] is False
        assert statusdaten["schema"]["felder"]
        assert statusdaten["weiter"] == f"/vorlagen/{vorlage_id}"
    finally:
        _vorlage_loeschen(vorlage_id)


def test_alter_offener_lauf_wird_als_unterbrochen_markiert_und_kann_neu_starten(client):
    _anmelden(client)
    with Sitzung() as db:
        mitglied = db.scalar(select(Mitglied).where(Mitglied.email == DEMO_EMAIL))
        assert mitglied is not None
        pfad = cfg.upload_pfad / f"unterbrochen-{uuid.uuid4().hex}.pdf"
        pfad.write_bytes(_pdf_bytes("Unterbrochener Lauf"))
        eintrag = Dokumentvorlage(
            organisation_id=mitglied.organisation_id,
            erstellt_von_id=mitglied.id,
            name="Unterbrochene Analyse",
            dateiname=pfad.name,
            speicherort=str(pfad),
            inhaltstyp="application/pdf",
            originalgroesse=pfad.stat().st_size,
            status="wird analysiert",
            seiten=1,
            schema={},
            aktualisiert_am=datetime.now(timezone.utc) - timedelta(minutes=6),
        )
        db.add(eintrag)
        db.commit()
        db.refresh(eintrag)
        vorlage_id = eintrag.id

    try:
        status = client.get(f"/api/vorlagen/{vorlage_id}/analyse-status")
        assert status.status_code == 200
        assert status.json()["fehler"] is True
        assert status.json()["status"] == "Analyse unterbrochen"

        erneut = client.post(f"/api/vorlagen/{vorlage_id}/analyse-neu-starten")
        assert erneut.status_code == 202
        danach = client.get(f"/api/vorlagen/{vorlage_id}/analyse-status").json()
        assert danach["fertig"] is True
        assert danach["schema"]["felder"]
    finally:
        _vorlage_loeschen(vorlage_id)


def test_browser_laed_robusten_analyseablauf_vor_dem_alten_appskript(client):
    _anmelden(client)
    seite = client.get("/vorlagen/neu")
    assert seite.status_code == 200
    assert "analysis-flow.css" in seite.text
    assert "analysis-flow.js" in seite.text
    assert seite.text.index("analysis-flow.js") < seite.text.index("app.js")
