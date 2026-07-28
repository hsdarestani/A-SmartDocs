from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select

from app.database import Sitzung
from app.main import cfg
from app.models import Dokumentvorlage, Mitglied

DEMO_EMAIL = "demo@smartdocs.de"
DEMO_PASSWORT = "Aplus-Kunde-7Qm!26"


def _anmelden(client) -> None:
    antwort = client.post("/anmelden", data={"email": DEMO_EMAIL, "passwort": DEMO_PASSWORT, "weiter": "/arbeitsbereich"}, follow_redirects=False)
    assert antwort.status_code == 303


def _pdf_bytes() -> bytes:
    speicher = io.BytesIO()
    zeichner = canvas.Canvas(speicher, pagesize=A4)
    zeichner.drawString(60, 760, "Editor-Einstieg")
    zeichner.drawString(60, 710, "Kundenname")
    zeichner.line(60, 690, 260, 690)
    zeichner.save()
    return speicher.getvalue()


def _isolierte_vorlage() -> tuple[int, Path]:
    with Sitzung() as db:
        mitglied = db.scalar(select(Mitglied).where(Mitglied.email == DEMO_EMAIL))
        assert mitglied is not None
        pfad = cfg.upload_pfad / f"editor-entry-{uuid.uuid4().hex}.pdf"
        pfad.write_bytes(_pdf_bytes())
        schema = {"dokumentart": "Editor-Test", "zusammenfassung": "Isolierte Vorlage", "felder": [{"schluessel": "kundenname", "bezeichnung": "Kundenname", "typ": "text", "pflichtfeld": False, "seite": 1, "position": {"x": 0.1, "y": 0.18, "breite": 0.35, "hoehe": 0.04}, "erkennungsquelle": "manuell", "geprueft": True, "vorschlag_status": "bestaetigt"}]}
        vorlage = Dokumentvorlage(organisation_id=mitglied.organisation_id, erstellt_von_id=mitglied.id, name=f"Editor-Einstieg {uuid.uuid4().hex[:8]}", dateiname=pfad.name, speicherort=str(pfad), inhaltstyp="application/pdf", originalgroesse=pfad.stat().st_size, status="bereit", seiten=1, erkannte_felder=1, schema=schema, zusammenfassung=schema["zusammenfassung"], aktualisiert_am=datetime.now(timezone.utc))
        db.add(vorlage)
        db.commit()
        db.refresh(vorlage)
        return vorlage.id, pfad


def _aufräumen(vorlage_id: int, pfad: Path) -> None:
    with Sitzung() as db:
        vorlage = db.get(Dokumentvorlage, vorlage_id)
        if vorlage:
            db.delete(vorlage)
            db.commit()
    pfad.unlink(missing_ok=True)


def test_ausfuellseite_hat_nur_einen_klaren_editorzugang(client):
    _anmelden(client)
    vorlage_id, pfad = _isolierte_vorlage()
    try:
        antwort = client.get(f"/vorlagen/{vorlage_id}/verwenden")
        assert antwort.status_code == 200
        assert "Vorlage bearbeiten" in antwort.text
        assert f'href="/vorlagen/{vorlage_id}?modus=chat"' in antwort.text
        assert "Mit Assistent bearbeiten" not in antwort.text
        assert "Manuell bearbeiten" not in antwort.text
    finally:
        _aufräumen(vorlage_id, pfad)


def test_editor_laesst_sich_mit_modusparameter_oeffnen(client):
    _anmelden(client)
    vorlage_id, pfad = _isolierte_vorlage()
    try:
        chat = client.get(f"/vorlagen/{vorlage_id}?modus=chat")
        manuell = client.get(f"/vorlagen/{vorlage_id}?modus=manuell")
        skript = client.get("/statisch/editor-entry-mode.js")
        assert chat.status_code == 200
        assert manuell.status_code == 200
        assert 'data-workflow-modus="chat"' in chat.text
        assert 'data-workflow-modus="manuell"' in manuell.text
        assert "Mit A+ bearbeiten" in chat.text
        assert "Manuell" in manuell.text
        assert skript.status_code == 200
        assert "URLSearchParams" in skript.text
        assert "workflowFeldWerkzeug" in skript.text
        assert "workflowChatText" in skript.text
    finally:
        _aufräumen(vorlage_id, pfad)
