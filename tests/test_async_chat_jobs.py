from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select

from app import chat_jobs
from app.database import Sitzung
from app.main import cfg
from app.models import Dokumentvorlage, Mitglied, Vorlagendialog


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
    speicher = io.BytesIO()
    zeichner = canvas.Canvas(speicher, pagesize=A4)
    zeichner.drawString(60, 760, "Arbeitgeber Firmenname")
    zeichner.drawString(60, 730, "Musterfirma GmbH")
    zeichner.save()
    return speicher.getvalue()


def _vorlage_anlegen() -> tuple[int, Path]:
    with Sitzung() as db:
        mitglied = db.scalar(select(Mitglied).where(Mitglied.email == DEMO_EMAIL))
        assert mitglied is not None
        pfad = cfg.upload_pfad / f"chat-job-{uuid.uuid4().hex}.pdf"
        pfad.write_bytes(_pdf())
        schema = {
            "dokumentart": "Arbeitsvereinbarung",
            "zusammenfassung": "Test für asynchrone Änderungen.",
            "pflichtfelder_initialisiert": True,
            "testausfuellung_geprueft": True,
            "testausfuellung_hash": "alt",
            "felder": [
                {
                    "schluessel": "arbeitgeber_firmenname",
                    "bezeichnung": "Arbeitgeber Firmenname",
                    "typ": "text",
                    "pflichtfeld": False,
                    "beispiel": "Musterfirma GmbH",
                    "seite": 1,
                    "position": {"x": 0.1, "y": 0.12, "breite": 0.4, "hoehe": 0.04},
                    "alten_inhalt_entfernen": True,
                    "vorschlag_status": "vorgeschlagen",
                }
            ],
        }
        vorlage = Dokumentvorlage(
            organisation_id=mitglied.organisation_id,
            erstellt_von_id=mitglied.id,
            name=f"Chat-Test {uuid.uuid4().hex[:8]}",
            dateiname=pfad.name,
            speicherort=str(pfad),
            inhaltstyp="application/pdf",
            originalgroesse=pfad.stat().st_size,
            status="Bestätigung erforderlich",
            seiten=1,
            erkannte_felder=1,
            schema=schema,
            zusammenfassung=schema["zusammenfassung"],
            aktualisiert_am=datetime.now(timezone.utc),
        )
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


def test_eindeutige_zuweisung_wird_lokal_ohne_ki_ausgefuehrt(client, monkeypatch):
    _anmelden(client)
    vorlage_id, pfad = _vorlage_anlegen()

    def ki_darf_nicht_laufen(*_args, **_kwargs):
        raise AssertionError("Eine eindeutige Wertzuweisung darf keinen KI-Aufruf benötigen.")

    monkeypatch.setattr(chat_jobs, "schema_korrigieren", ki_darf_nicht_laufen)
    try:
        start = client.post(
            "/api/vorlagen/korrigieren-async",
            json={"vorlage_id": vorlage_id, "nachricht": "firmname is A+ Solution GmbH"},
        )
        assert start.status_code == 202
        assert start.json()["status"] == "laeuft"

        status = client.get(start.json()["status_url"])
        assert status.status_code == 200
        assert status.json()["fertig"] is True
        assert "A+ Solution GmbH" in status.json()["antwort"]

        with Sitzung() as db:
            vorlage = db.get(Dokumentvorlage, vorlage_id)
            assert vorlage is not None
            feld = vorlage.schema["felder"][0]
            # Der Originalwert bleibt als Suchtext für die präzise PDF-Bereinigung erhalten.
            assert feld["beispiel"] == "Musterfirma GmbH"
            assert feld["standardwert"] == "A+ Solution GmbH"
            assert feld["vorschauwert"] == "A+ Solution GmbH"
            assert feld["alten_inhalt_entfernen"] is True
            assert feld["vorschlag_status"] == "bestaetigt"
            assert vorlage.schema["testausfuellung_geprueft"] is False
            assert vorlage.schema["_chat_auftrag"]["status"] == "fertig"
            dialoge = db.scalars(
                select(Vorlagendialog).where(Vorlagendialog.vorlage_id == vorlage_id).order_by(Vorlagendialog.id)
            ).all()
            assert any(dialog.rolle == "nutzer" and "firmname" in dialog.nachricht for dialog in dialoge)
            assert any(dialog.rolle == "assistent" and "A+ Solution GmbH" in dialog.nachricht for dialog in dialoge)
    finally:
        _aufräumen(vorlage_id, pfad)


def test_ki_fehler_laesst_schema_unveraendert_und_beendet_auftrag(client, monkeypatch):
    _anmelden(client)
    vorlage_id, pfad = _vorlage_anlegen()
    monkeypatch.setattr(chat_jobs, "schema_korrigieren", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(chat_jobs.time, "sleep", lambda _sekunden: None)
    try:
        start = client.post(
            "/api/vorlagen/korrigieren-async",
            json={"vorlage_id": vorlage_id, "nachricht": "Ordne die Felder sinnvoller an."},
        )
        assert start.status_code == 202
        status = client.get(start.json()["status_url"])
        assert status.status_code == 200
        assert status.json()["fehler"] is True
        assert "bisherigen Änderungen bleiben erhalten" in status.json()["antwort"]

        with Sitzung() as db:
            vorlage = db.get(Dokumentvorlage, vorlage_id)
            assert vorlage is not None
            assert vorlage.schema["felder"][0]["beispiel"] == "Musterfirma GmbH"
            assert vorlage.schema["_chat_auftrag"]["status"] == "fehler"
    finally:
        _aufräumen(vorlage_id, pfad)
