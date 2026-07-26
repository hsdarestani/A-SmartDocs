from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from pathlib import Path

import fitz
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select

from app.auth import passwort_hashen
from app.database import Sitzung
from app.form_analysis import formular_lokal_analysieren
from app.main import cfg
from app.models import Dokumentausgabe, Dokumentvorlage, Kontorolle, Mitglied, Organisation


DEMO_EMAIL = "demo@smartdocs.de"
DEMO_PASSWORT = "Aplus-Kunde-7Qm!26"


def _anmelden(client, email: str = DEMO_EMAIL, passwort: str = DEMO_PASSWORT) -> None:
    antwort = client.post(
        "/anmelden",
        data={"email": email, "passwort": passwort, "weiter": "/arbeitsbereich"},
        follow_redirects=False,
    )
    assert antwort.status_code == 303


def _pdf_bytes(text: str = "A+ SmartDocs") -> bytes:
    speicher = io.BytesIO()
    zeichner = canvas.Canvas(speicher, pagesize=A4)
    zeichner.drawString(50, 780, text)
    zeichner.save()
    return speicher.getvalue()


def _demo_konto() -> tuple[int, int]:
    with Sitzung() as db:
        mitglied = db.scalar(select(Mitglied).where(Mitglied.email == DEMO_EMAIL))
        assert mitglied is not None
        return mitglied.organisation_id, mitglied.id


def _vorlage_anlegen(schema: dict | None = None, mit_dokument: bool = False) -> tuple[int, int | None, Path, Path | None]:
    organisation_id, mitglied_id = _demo_konto()
    quellpfad = cfg.upload_pfad / f"pytest-use-{uuid.uuid4().hex}.pdf"
    quellpfad.write_bytes(_pdf_bytes("Testvorlage"))
    schema = schema or {
        "dokumentart": "Test",
        "zusammenfassung": "Testvorlage",
        "felder": [
            {
                "schluessel": "kundenname",
                "bezeichnung": "Kundenname",
                "typ": "text",
                "pflichtfeld": False,
                "seite": 1,
                "position": {"x": 0.1, "y": 0.2, "breite": 0.4, "hoehe": 0.04},
                "schriftgroesse": 10,
                "erkennungsquelle": "manuell",
            }
        ],
    }
    ausgabepfad: Path | None = None
    with Sitzung() as db:
        vorlage = Dokumentvorlage(
            organisation_id=organisation_id,
            erstellt_von_id=mitglied_id,
            name=f"Testvorlage {uuid.uuid4().hex[:8]}",
            dateiname=quellpfad.name,
            speicherort=str(quellpfad),
            inhaltstyp="application/pdf",
            originalgroesse=quellpfad.stat().st_size,
            status="bereit",
            seiten=1,
            erkannte_felder=len(schema.get("felder", [])),
            schema=schema,
            zusammenfassung="Automatisierter Test",
            aktualisiert_am=datetime.now(timezone.utc),
        )
        db.add(vorlage)
        db.flush()
        dokument_id = None
        if mit_dokument:
            ausgabepfad = cfg.ausgabe_pfad / f"pytest-output-{uuid.uuid4().hex}.pdf"
            ausgabepfad.write_bytes(_pdf_bytes("Ausgabe"))
            dokument = Dokumentausgabe(
                organisation_id=organisation_id,
                vorlage_id=vorlage.id,
                erstellt_von_id=mitglied_id,
                titel="Testausgabe",
                dateiname="Testausgabe.pdf",
                speicherort=str(ausgabepfad),
                eingaben={},
                status="fertig",
                seiten=1,
                dateigroesse=ausgabepfad.stat().st_size,
            )
            db.add(dokument)
            db.flush()
            dokument_id = dokument.id
        db.commit()
        return vorlage.id, dokument_id, quellpfad, ausgabepfad


def _aufräumen(vorlage_id: int, dateien: list[Path | None]) -> None:
    with Sitzung() as db:
        vorlage = db.get(Dokumentvorlage, vorlage_id)
        if vorlage:
            db.delete(vorlage)
            db.commit()
    for datei in dateien:
        if datei:
            datei.unlink(missing_ok=True)


def test_originalvorlage_wird_inline_im_iframe_ausgeliefert(client):
    _anmelden(client)
    vorlage_id, _, quellpfad, _ = _vorlage_anlegen()
    try:
        antwort = client.get(f"/vorlagen/{vorlage_id}/datei")
        assert antwort.status_code == 200
        assert antwort.headers.get("content-disposition", "").lower().startswith("inline")
        assert antwort.headers.get("content-type", "").startswith("application/pdf")
    finally:
        _aufräumen(vorlage_id, [quellpfad])


def test_verwendungsseite_entfernt_leere_selects_und_gruppiert_lange_formulare(client):
    schema = {
        "dokumentart": "Personalfragebogen",
        "zusammenfassung": "Technische AcroForm-Namen",
        "felder": [
            {
                "schluessel": "option_1",
                "bezeichnung": "Option Field 1",
                "typ": "auswahl",
                "optionen": [],
                "seite": 1,
                "position": {"x": 0.1, "y": 0.1, "breite": 0.03, "hoehe": 0.03},
                "hinweis": "Interactive PDF form field",
            },
            {
                "schluessel": "geburtsdatum",
                "bezeichnung": "ENTER DATE OF BIRTH HERE",
                "typ": "text",
                "optionen": [],
                "seite": 1,
                "position": {"x": 0.1, "y": 0.2, "breite": 0.35, "hoehe": 0.04},
                "hinweis": "Interactive PDF form field",
            },
        ],
    }
    _anmelden(client)
    vorlage_id, _, quellpfad, _ = _vorlage_anlegen(schema=schema)
    try:
        antwort = client.get(f"/vorlagen/{vorlage_id}/verwenden")
        assert antwort.status_code == 200
        assert "formular-abschnitt" in antwort.text
        assert "Original in neuem Tab öffnen" in antwort.text
        assert 'type="checkbox" name="option_1"' in antwort.text
        assert '<select name="option_1"' not in antwort.text
        assert 'type="date" name="geburtsdatum"' in antwort.text
        assert "Interactive PDF form field" not in antwort.text
        assert "use-page-fixes.css" in antwort.text
    finally:
        _aufräumen(vorlage_id, [quellpfad])


def test_sichtbare_beschriftung_ersetzt_technischen_widgetnamen(tmp_path: Path):
    pfad = tmp_path / "widget-label.pdf"
    dokument = fitz.open()
    seite = dokument.new_page(width=595, height=842)
    widget = fitz.Widget()
    widget.field_name = "Text Field 1"
    widget.field_label = "ENTER DATE OF BIRTH HERE"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = fitz.Rect(50, 60, 250, 82)
    seite.add_widget(widget)
    seite.insert_text((50, 95), "Geburtsdatum", fontsize=8)
    dokument.save(pfad)
    dokument.close()

    schema, diagnostik = formular_lokal_analysieren(pfad, pfad.name)
    assert diagnostik["felder"] >= 1
    feld = next(feld for feld in schema["felder"] if feld["schluessel"].startswith("text_field_1"))
    assert feld["bezeichnung"] == "Geburtsdatum"
    assert feld["typ"] == "datum"


def test_inhaber_loescht_dokument_und_physische_datei(client):
    _anmelden(client)
    vorlage_id, dokument_id, quellpfad, ausgabepfad = _vorlage_anlegen(mit_dokument=True)
    assert dokument_id is not None and ausgabepfad is not None
    antwort = client.post(f"/dokumente/{dokument_id}/loeschen", follow_redirects=False)
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/dokumente"
    with Sitzung() as db:
        assert db.get(Dokumentausgabe, dokument_id) is None
        assert db.get(Dokumentvorlage, vorlage_id) is not None
    assert not ausgabepfad.exists()
    _aufräumen(vorlage_id, [quellpfad])


def test_inhaber_loescht_vorlage_ausgaben_und_vorschaudateien(client):
    _anmelden(client)
    vorlage_id, dokument_id, quellpfad, ausgabepfad = _vorlage_anlegen(mit_dokument=True)
    organisation_id, _ = _demo_konto()
    preview = cfg.ausgabe_pfad / f"testausfuellung-{organisation_id}-{vorlage_id}-pytest.pdf"
    signatur = cfg.ausgabe_pfad / f"test-signatur-{vorlage_id}.png"
    preview.write_bytes(_pdf_bytes("Preview"))
    signatur.write_bytes(b"png")

    antwort = client.post(f"/vorlagen/{vorlage_id}/loeschen", follow_redirects=False)
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/vorlagen"
    with Sitzung() as db:
        assert db.get(Dokumentvorlage, vorlage_id) is None
        assert dokument_id is not None and db.get(Dokumentausgabe, dokument_id) is None
    for datei in (quellpfad, ausgabepfad, preview, signatur):
        assert datei is not None and not datei.exists()


def test_bearbeiter_kann_weder_dokument_noch_vorlage_loeschen(client):
    vorlage_id, dokument_id, quellpfad, ausgabepfad = _vorlage_anlegen(mit_dokument=True)
    assert dokument_id is not None
    organisation_id, _ = _demo_konto()
    email = f"bearbeitung-{uuid.uuid4().hex[:10]}@example.de"
    passwort = "Bearbeitung-Test-42!"
    with Sitzung() as db:
        konto = Mitglied(
            organisation_id=organisation_id,
            name="Test Bearbeitung",
            email=email,
            passwort_hash=passwort_hashen(passwort),
            rolle=Kontorolle.BEARBEITUNG,
            email_bestaetigt=True,
            aktiv=True,
        )
        db.add(konto)
        db.commit()
        konto_id = konto.id

    try:
        _anmelden(client, email, passwort)
        dokument_antwort = client.post(f"/dokumente/{dokument_id}/loeschen", follow_redirects=False)
        vorlage_antwort = client.post(f"/vorlagen/{vorlage_id}/loeschen", follow_redirects=False)
        assert dokument_antwort.status_code == 403
        assert vorlage_antwort.status_code == 403
        with Sitzung() as db:
            assert db.get(Dokumentausgabe, dokument_id) is not None
            assert db.get(Dokumentvorlage, vorlage_id) is not None
    finally:
        with Sitzung() as db:
            konto = db.get(Mitglied, konto_id)
            if konto:
                db.delete(konto)
                db.commit()
        _aufräumen(vorlage_id, [quellpfad, ausgabepfad])
