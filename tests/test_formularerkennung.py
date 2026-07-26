from __future__ import annotations

import io
import uuid
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.database import Sitzung
from app.local_analysis import formular_lokal_analysieren, schema_kombinieren
from app.models import Dokumentvorlage


DEMO_EMAIL = "demo@smartdocs.de"
DEMO_PASSWORT = "Aplus-Kunde-7Qm!26"


def _personalbogen_bytes() -> bytes:
    speicher = io.BytesIO()
    c = canvas.Canvas(speicher, pagesize=A4)
    breite, hoehe = A4
    c.setFont("Helvetica-Bold", 18)
    c.drawString(48, hoehe - 48, "Personalfragebogen")
    c.setFont("Helvetica", 8)

    felder = [
        (48, hoehe - 100, 250, "Vorname"),
        (310, hoehe - 100, 510, "Nachname"),
        (48, hoehe - 145, 250, "Straße und Hausnummer"),
        (310, hoehe - 145, 510, "Geburtsdatum"),
        (48, hoehe - 190, 250, "E-Mail-Adresse"),
        (310, hoehe - 190, 510, "Telefonnummer"),
        (48, hoehe - 255, 250, "IBAN"),
        (310, hoehe - 255, 510, "Name des Kreditinstituts"),
        (48, hoehe - 320, 250, "Steueridentifikationsnummer"),
        (310, hoehe - 320, 510, "Steuerklasse/Faktor"),
        (48, hoehe - 385, 250, "Krankenkasse"),
        (310, hoehe - 385, 510, "Sozial-/Rentenversicherungsnummer"),
        (48, 92, 250, "Ort, Datum"),
        (310, 92, 510, "Unterschrift Mitarbeiter"),
    ]
    for x0, y, x1, label in felder:
        c.drawString(x0, y + 7, label)
        c.line(x0, y, x1, y)

    c.drawString(48, hoehe - 75, "Herr    Frau    Divers    Unbestimmt")
    c.drawString(48, hoehe - 360, "gesetzlich    privat")
    c.save()
    return speicher.getvalue()


def _anmelden(client) -> None:
    antwort = client.post(
        "/anmelden",
        data={"email": DEMO_EMAIL, "passwort": DEMO_PASSWORT, "weiter": "/arbeitsbereich"},
        follow_redirects=False,
    )
    assert antwort.status_code == 303


def test_lokale_analyse_erkennt_personalformular_statt_vier_generischer_felder(tmp_path: Path):
    pfad = tmp_path / "personalfragebogen.pdf"
    pfad.write_bytes(_personalbogen_bytes())

    schema, diagnostik = formular_lokal_analysieren(pfad, pfad.name)
    bezeichnungen = {feld["bezeichnung"] for feld in schema["felder"]}

    assert diagnostik["felder"] >= 12
    assert "Vorname" in bezeichnungen
    assert "Nachname" in bezeichnungen
    assert "IBAN" in bezeichnungen
    assert "Steueridentifikationsnummer" in bezeichnungen
    assert "Unterschrift Mitarbeiter" in bezeichnungen
    assert any(feld["typ"] == "unterschrift" for feld in schema["felder"])
    assert any(feld["typ"] == "datum" for feld in schema["felder"])
    assert any(feld["typ"] == "auswahl" for feld in schema["felder"])
    assert schema["analysequelle"] == "pdf-struktur"


def test_generischer_ki_vorschlag_wird_bei_konkretem_formular_verworfen(tmp_path: Path):
    pfad = tmp_path / "personalfragebogen.pdf"
    pfad.write_bytes(_personalbogen_bytes())
    lokal, _ = formular_lokal_analysieren(pfad, pfad.name)
    generisch = {
        "dokumentart": "Geschäftsdokument",
        "zusammenfassung": "Allgemeines Schema",
        "felder": [
            {"schluessel": "kundenname", "bezeichnung": "Kundenname", "typ": "text", "seite": 1},
            {"schluessel": "datum", "bezeichnung": "Datum", "typ": "datum", "seite": 1},
            {"schluessel": "beschreibung", "bezeichnung": "Beschreibung", "typ": "mehrzeilig", "seite": 1},
            {"schluessel": "unterschrift", "bezeichnung": "Unterschrift", "typ": "unterschrift", "seite": 1},
        ],
        "rueckfragen": [],
    }

    kombiniert = schema_kombinieren(generisch, lokal)
    schluessel = {feld["schluessel"] for feld in kombiniert["felder"]}

    assert len(kombiniert["felder"]) >= 12
    assert "kundenname" not in schluessel
    assert kombiniert["analysequelle"] == "pdf-struktur-priorisiert"


def test_upload_ohne_ki_liefert_konkrete_personalfelder(client):
    _anmelden(client)
    name = f"Personalformular {uuid.uuid4().hex[:8]}"
    antwort = client.post(
        "/api/vorlagen/analysieren",
        data={"name": name},
        files={"datei": ("personalfragebogen.pdf", _personalbogen_bytes(), "application/pdf")},
    )
    assert antwort.status_code == 200
    daten = antwort.json()
    vorlage_id = int(daten["vorlage_id"])

    try:
        assert daten["lokale_diagnostik"]["felder"] >= 12
        status = client.get(daten["status_url"])
        assert status.status_code == 200
        statusdaten = status.json()
        assert statusdaten["fertig"] is True
        bezeichnungen = {feld["bezeichnung"] for feld in statusdaten["schema"]["felder"]}
        assert {"Vorname", "Nachname", "IBAN", "Unterschrift Mitarbeiter"}.issubset(bezeichnungen)
        assert "Kundenname" not in bezeichnungen
    finally:
        with Sitzung() as db:
            eintrag = db.get(Dokumentvorlage, vorlage_id)
            if eintrag:
                pfad = Path(eintrag.speicherort)
                db.delete(eintrag)
                db.commit()
                pfad.unlink(missing_ok=True)
