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
from app.quality import schema_mit_qualitaet


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
    zeichner.setFont("Helvetica-Bold", 13)
    zeichner.drawString(60, 780, "Qualitätsprüfung")
    zeichner.setFont("Helvetica", 9)
    zeichner.drawString(60, 730, "Vorname")
    zeichner.line(60, 710, 270, 710)
    zeichner.drawString(330, 730, "Unterschrift")
    zeichner.line(330, 670, 520, 670)
    zeichner.save()
    return speicher.getvalue()


def _vorlage_anlegen() -> int:
    with Sitzung() as db:
        mitglied = db.scalar(select(Mitglied).where(Mitglied.email == DEMO_EMAIL))
        assert mitglied is not None
        pfad = cfg.upload_pfad / f"quality-{uuid.uuid4().hex}.pdf"
        pfad.write_bytes(_pdf())
        schema = schema_mit_qualitaet(
            {
                "dokumentart": "Qualitätsformular",
                "zusammenfassung": "Prüfung von sicheren und unsicheren Feldern.",
                "felder": [
                    {
                        "schluessel": "vorname",
                        "bezeichnung": "Vorname",
                        "typ": "text",
                        "pflichtfeld": False,
                        "seite": 1,
                        "position": {"x": 0.1, "y": 0.15, "breite": 0.35, "hoehe": 0.04},
                        "schriftgroesse": 9,
                        "erkennungsquelle": "pdf-formularfeld",
                        "hintergrundmodus": "transparent",
                    },
                    {
                        "schluessel": "unterschrift",
                        "bezeichnung": "Unterschrift Mitarbeiter",
                        "typ": "unterschrift",
                        "pflichtfeld": False,
                        "seite": 1,
                        "position": {"x": 0.55, "y": 0.2, "breite": 0.3, "hoehe": 0.08},
                        "schriftgroesse": 9,
                        "erkennungsquelle": "pdf-textkandidat",
                        "hintergrundmodus": "transparent",
                    },
                ],
            }
        )
        eintrag = Dokumentvorlage(
            organisation_id=mitglied.organisation_id,
            erstellt_von_id=mitglied.id,
            name="Qualitätsprüfung",
            dateiname=pfad.name,
            speicherort=str(pfad),
            inhaltstyp="application/pdf",
            originalgroesse=pfad.stat().st_size,
            status="Bestätigung erforderlich",
            seiten=1,
            erkannte_felder=2,
            schema=schema,
            zusammenfassung=schema["zusammenfassung"],
            aktualisiert_am=datetime.now(timezone.utc),
        )
        db.add(eintrag)
        db.commit()
        db.refresh(eintrag)
        return eintrag.id


def _vorlage_loeschen(vorlage_id: int) -> None:
    with Sitzung() as db:
        eintrag = db.get(Dokumentvorlage, vorlage_id)
        if not eintrag:
            return
        Path(eintrag.speicherort).unlink(missing_ok=True)
        for pfad in cfg.ausgabe_pfad.glob(f"testausfuellung-*-{vorlage_id}-*.pdf"):
            pfad.unlink(missing_ok=True)
        (cfg.ausgabe_pfad / f"test-signatur-{vorlage_id}.png").unlink(missing_ok=True)
        db.delete(eintrag)
        db.commit()


def test_konfidenz_unterscheidet_belastbare_und_unsichere_quellen():
    schema = schema_mit_qualitaet(
        {
            "felder": [
                {"schluessel": "a", "bezeichnung": "Vorname", "typ": "text", "erkennungsquelle": "pdf-formularfeld", "position": {"x": .1, "y": .1, "breite": .3, "hoehe": .04}},
                {"schluessel": "b", "bezeichnung": "Feld", "typ": "text", "erkennungsquelle": "pdf-textkandidat", "position": {"x": .1, "y": .2, "breite": .3, "hoehe": .04}},
            ]
        }
    )
    assert schema["felder"][0]["konfidenzstufe"] == "sicher"
    assert schema["felder"][1]["konfidenzstufe"] == "unsicher"
    assert schema["qualitaet"]["offene_felder"] == 1


def test_editor_zeigt_qualitaetskontrolle_und_vergleich(client):
    _anmelden(client)
    vorlage_id = _vorlage_anlegen()
    try:
        seite = client.get(f"/vorlagen/{vorlage_id}")
        assert seite.status_code == 200
        assert "Automatische Qualitätskontrolle" in seite.text
        assert "Testausfüllung prüfen" in seite.text
        assert "vergleichOriginal" in seite.text
        assert "quality-control.js" in seite.text
    finally:
        _vorlage_loeschen(vorlage_id)


def test_freigabe_erfordert_aktuelle_testausfuellung_und_feldpruefung(client):
    _anmelden(client)
    vorlage_id = _vorlage_anlegen()
    try:
        zu_frueh = client.post(f"/api/vorlagen/{vorlage_id}/bestaetigen")
        assert zu_frueh.status_code == 409
        assert "ungeprüft" in zu_frueh.json()["detail"]

        preview = client.post(f"/api/vorlagen/{vorlage_id}/testausfuellung")
        assert preview.status_code == 200
        daten = preview.json()
        assert daten["test_url"].startswith(f"/vorlagen/{vorlage_id}/testausfuellung.pdf")

        datei = client.get(f"/vorlagen/{vorlage_id}/testausfuellung.pdf")
        assert datei.status_code == 200
        assert datei.content.startswith(b"%PDF")
        assert len(datei.content) > 1000

        ohne_checkbox = client.post(
            f"/api/vorlagen/{vorlage_id}/pruefung-bestaetigen",
            json={"alle_pruefpflichtigen": True, "testausfuellung_geprueft": False, "schluessel": []},
        )
        assert ohne_checkbox.status_code == 409

        pruefung = client.post(
            f"/api/vorlagen/{vorlage_id}/pruefung-bestaetigen",
            json={"alle_pruefpflichtigen": True, "testausfuellung_geprueft": True, "schluessel": []},
        )
        assert pruefung.status_code == 200
        assert pruefung.json()["qualitaet"]["offene_felder"] == 0
        assert pruefung.json()["schema"]["testausfuellung_geprueft"] is True

        freigabe = client.post(f"/api/vorlagen/{vorlage_id}/bestaetigen")
        assert freigabe.status_code == 200
        assert freigabe.json()["status"] == "bereit"
    finally:
        _vorlage_loeschen(vorlage_id)


def test_positionsaenderung_macht_testausfuellung_wieder_ungueltig(client):
    _anmelden(client)
    vorlage_id = _vorlage_anlegen()
    try:
        assert client.post(f"/api/vorlagen/{vorlage_id}/testausfuellung").status_code == 200
        assert client.post(
            f"/api/vorlagen/{vorlage_id}/pruefung-bestaetigen",
            json={"alle_pruefpflichtigen": True, "testausfuellung_geprueft": True, "schluessel": []},
        ).status_code == 200

        with Sitzung() as db:
            eintrag = db.get(Dokumentvorlage, vorlage_id)
            schema = dict(eintrag.schema)
        schema["felder"][0]["position"]["x"] = 0.2
        gespeichert = client.put(f"/api/vorlagen/{vorlage_id}/schema", json={"schema": schema})
        assert gespeichert.status_code == 200
        assert gespeichert.json()["schema"]["testausfuellung_geprueft"] is False

        freigabe = client.post(f"/api/vorlagen/{vorlage_id}/bestaetigen")
        assert freigabe.status_code == 409
        assert "Testausfüllung" in freigabe.json()["detail"]
    finally:
        _vorlage_loeschen(vorlage_id)
