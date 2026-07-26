from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select

from app.database import Sitzung
from app.main import app, cfg
from app.models import Dokumentausgabe, Dokumentvorlage, Mitglied


DEMO_EMAIL = "demo@smartdocs.de"
DEMO_PASSWORT = "Aplus-Kunde-7Qm!26"


def _pdf_bytes(text: str) -> bytes:
    speicher = io.BytesIO()
    zeichner = canvas.Canvas(speicher, pagesize=A4)
    zeichner.drawString(60, 760, text)
    zeichner.save()
    return speicher.getvalue()


def _anmelden(client) -> None:
    antwort = client.post(
        "/anmelden",
        data={"email": DEMO_EMAIL, "passwort": DEMO_PASSWORT, "weiter": "/arbeitsbereich"},
        follow_redirects=False,
    )
    assert antwort.status_code == 303


def _vorlage_mit_falschem_mime_anlegen() -> tuple[int, Path]:
    pfad = cfg.upload_pfad / f"pytest-inline-{uuid.uuid4().hex}.pdf"
    pfad.write_bytes(_pdf_bytes("Inline-Vorschau"))
    with Sitzung() as db:
        mitglied = db.scalar(select(Mitglied).where(Mitglied.email == DEMO_EMAIL))
        assert mitglied is not None
        schema = {
            "dokumentart": "Testformular",
            "zusammenfassung": "Prüft eingebettete PDF-Vorschauen.",
            "felder": [
                {
                    "schluessel": "name",
                    "bezeichnung": "Name",
                    "typ": "text",
                    "pflichtfeld": False,
                    "beispiel": "Inline-Vorschau",
                    "seite": 1,
                    "position": {"x": 0.1, "y": 0.1, "breite": 0.35, "hoehe": 0.04},
                    "schriftgroesse": 10,
                    "erkennungsquelle": "manuell",
                }
            ],
        }
        vorlage = Dokumentvorlage(
            organisation_id=mitglied.organisation_id,
            erstellt_von_id=mitglied.id,
            name=f"Inline-Test {uuid.uuid4().hex[:8]}",
            dateiname="inline-test.pdf",
            speicherort=str(pfad),
            # Absichtlich falsch, damit die Route den Typ aus der Endung ableiten muss.
            inhaltstyp="application/octet-stream",
            originalgroesse=pfad.stat().st_size,
            status="bereit",
            seiten=1,
            erkannte_felder=1,
            schema=schema,
            zusammenfassung="Inline-Test",
            aktualisiert_am=datetime.now(timezone.utc),
        )
        db.add(vorlage)
        db.commit()
        return vorlage.id, pfad


def _aufräumen(vorlage_id: int, pfad: Path) -> None:
    with Sitzung() as db:
        vorlage = db.get(Dokumentvorlage, vorlage_id)
        if vorlage:
            for dokument in list(vorlage.dokumente):
                Path(dokument.speicherort).unlink(missing_ok=True)
            db.delete(vorlage)
            db.commit()
    pfad.unlink(missing_ok=True)
    for datei in cfg.ausgabe_pfad.glob(f"testausfuellung-*-{vorlage_id}-*.pdf"):
        datei.unlink(missing_ok=True)
    (cfg.ausgabe_pfad / f"test-signatur-{vorlage_id}.png").unlink(missing_ok=True)


def test_seitenaufruf_loest_keinen_download_aus_und_original_bleibt_inline(client):
    _anmelden(client)
    vorlage_id, pfad = _vorlage_mit_falschem_mime_anlegen()
    try:
        detail = client.get(f"/vorlagen/{vorlage_id}")
        verwenden = client.get(f"/vorlagen/{vorlage_id}/verwenden")
        for seite in (detail, verwenden):
            assert seite.status_code == 200
            assert seite.headers["content-type"].startswith("text/html")
            assert "content-disposition" not in seite.headers

        vorschau = client.get(f"/vorlagen/{vorlage_id}/datei")
        assert vorschau.status_code == 200
        assert vorschau.headers["content-type"].startswith("application/pdf")
        assert vorschau.headers.get("content-disposition", "").lower() == "inline"
        assert "attachment" not in vorschau.headers.get("content-disposition", "").lower()
        assert vorschau.headers.get("x-content-type-options") == "nosniff"
    finally:
        _aufräumen(vorlage_id, pfad)


def test_testausfuellung_wird_im_vergleich_inline_geoeffnet(client):
    _anmelden(client)
    vorlage_id, pfad = _vorlage_mit_falschem_mime_anlegen()
    try:
        erzeugt = client.post(f"/api/vorlagen/{vorlage_id}/testausfuellung")
        assert erzeugt.status_code == 200, erzeugt.text
        test_url = erzeugt.json()["test_url"]
        vorschau = client.get(test_url)
        assert vorschau.status_code == 200
        assert vorschau.headers["content-type"].startswith("application/pdf")
        assert vorschau.headers.get("content-disposition", "").lower() == "inline"
        assert "attachment" not in vorschau.headers.get("content-disposition", "").lower()
    finally:
        _aufräumen(vorlage_id, pfad)


def test_nur_eine_get_route_pro_vorschau_registriert_ist():
    for pfad in ("/vorlagen/{vorlage_id}/datei", "/vorlagen/{vorlage_id}/testausfuellung.pdf"):
        routen = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) == pfad
            and "GET" in (getattr(route, "methods", set()) or set())
        ]
        assert len(routen) == 1
