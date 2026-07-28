from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import fitz
from sqlalchemy import select

from app.database import Sitzung
from app.main import cfg
from app.models import Dokumentvorlage, Mitglied
from app.pdf_engine import dokument_erzeugen
from app.workflow_v2 import _pflichtfelder_initial_optional


DEMO_EMAIL = "demo@smartdocs.de"
DEMO_PASSWORT = "Aplus-Kunde-7Qm!26"


def _anmelden(client) -> None:
    antwort = client.post(
        "/anmelden",
        data={"email": DEMO_EMAIL, "passwort": DEMO_PASSWORT, "weiter": "/arbeitsbereich"},
        follow_redirects=False,
    )
    assert antwort.status_code == 303


def _pdf_mit_text(pfad: Path, text: str = "ALTWERT", farbe=(0.92, 0.95, 0.98)) -> None:
    dokument = fitz.open()
    seite = dokument.new_page(width=595, height=842)
    seite.draw_rect(fitz.Rect(70, 90, 360, 145), color=farbe, fill=farbe)
    seite.insert_text((88, 122), text, fontsize=12, color=(0.05, 0.12, 0.18))
    dokument.save(pfad)
    dokument.close()


def _vorlage_anlegen(pflichtfeld: bool = True) -> tuple[int, Path]:
    pfad = cfg.upload_pfad / f"workflow-{uuid.uuid4().hex}.pdf"
    _pdf_mit_text(pfad)
    with Sitzung() as db:
        inhaber = db.scalar(select(Mitglied).where(Mitglied.email == DEMO_EMAIL))
        assert inhaber is not None
        schema = {
            "dokumentart": "Workflow-Test",
            "zusammenfassung": "Test für Chat- und manuellen Modus",
            "felder": [
                {
                    "schluessel": "name",
                    "bezeichnung": "Name",
                    "typ": "text",
                    "pflichtfeld": pflichtfeld,
                    "beispiel": "ALTWERT",
                    "seite": 1,
                    "position": {"x": 0.14, "y": 0.105, "breite": 0.35, "hoehe": 0.045},
                    "schriftgroesse": 12,
                    "alten_inhalt_entfernen": True,
                }
            ],
        }
        eintrag = Dokumentvorlage(
            organisation_id=inhaber.organisation_id,
            erstellt_von_id=inhaber.id,
            name=f"Workflow {uuid.uuid4().hex[:8]}",
            dateiname=pfad.name,
            speicherort=str(pfad),
            inhaltstyp="application/pdf",
            originalgroesse=pfad.stat().st_size,
            status="bereit",
            seiten=1,
            erkannte_felder=1,
            schema=schema,
            zusammenfassung=schema["zusammenfassung"],
            aktualisiert_am=datetime.now(timezone.utc),
        )
        db.add(eintrag)
        db.commit()
        return eintrag.id, pfad


def _aufräumen(vorlage_id: int, *dateien: Path) -> None:
    with Sitzung() as db:
        eintrag = db.get(Dokumentvorlage, vorlage_id)
        if eintrag:
            db.delete(eintrag)
            db.commit()
    for datei in dateien:
        datei.unlink(missing_ok=True)


def test_drag_and_drop_wird_in_dateieingabe_und_analyse_verwendet():
    upload_js = Path("app/static/workflow-upload-fix.js").read_text()
    analyse_js = Path("app/static/analysis-flow.js").read_text()
    assert "new DataTransfer()" in upload_js
    assert "window.smartDocsAusgewaehlteDatei = datei" in upload_js
    assert "window.smartDocsAusgewaehlteDatei || dateiEingabe.files?.[0]" in analyse_js


def test_initiale_feldvorschlaege_sind_nicht_verpflichtend():
    schema, geaendert = _pflichtfelder_initial_optional(
        {"felder": [{"schluessel": "a", "pflichtfeld": True}, {"schluessel": "b", "pflichtfeld": True}]}
    )
    assert geaendert is True
    assert all(feld["pflichtfeld"] is False for feld in schema["felder"])
    assert schema["pflichtfelder_initialisiert"] is True


def test_editor_startet_im_chatmodus_und_nutzt_seitenfeste_bilder(client):
    _anmelden(client)
    vorlage_id, pfad = _vorlage_anlegen()
    try:
        antwort = client.get(f"/vorlagen/{vorlage_id}")
        assert antwort.status_code == 200
        assert 'data-workflow-modus="chat"' in antwort.text
        assert 'data-workflow-modus="manuell"' in antwort.text
        assert f'/vorlagen/{vorlage_id}/seiten/1.png' in antwort.text
        assert '<iframe src="/vorlagen/' not in antwort.text
        assert "workflowChatForm" in antwort.text
        with Sitzung() as db:
            eintrag = db.get(Dokumentvorlage, vorlage_id)
            assert eintrag is not None
            assert eintrag.schema["felder"][0]["pflichtfeld"] is False
    finally:
        _aufräumen(vorlage_id, pfad)


def test_seitenvorschau_ist_png_und_keine_downloadantwort(client):
    _anmelden(client)
    vorlage_id, pfad = _vorlage_anlegen(False)
    try:
        antwort = client.get(f"/vorlagen/{vorlage_id}/seiten/1.png")
        assert antwort.status_code == 200
        assert antwort.headers["content-type"].startswith("image/png")
        assert "attachment" not in antwort.headers.get("content-disposition", "").lower()
        assert antwort.content.startswith(b"\x89PNG")
    finally:
        _aufräumen(vorlage_id, pfad)


def test_ausfuellseite_zeigt_position_des_aktiven_feldes(client):
    _anmelden(client)
    vorlage_id, pfad = _vorlage_anlegen(False)
    try:
        antwort = client.get(f"/vorlagen/{vorlage_id}/verwenden")
        assert antwort.status_code == 200
        assert "live-form-page" in antwort.text
        assert 'data-feld-schluessel="name"' in antwort.text
        assert 'data-seite="1"' in antwort.text
        assert "workflow-use-v2.js" in antwort.text
    finally:
        _aufräumen(vorlage_id, pfad)


def test_renderer_entfernt_nur_exakten_altwert_und_schreibt_neuen_text(tmp_path: Path):
    original = tmp_path / "original.pdf"
    ausgabe = tmp_path / "ausgabe.pdf"
    _pdf_mit_text(original, "ALTWERT")
    schema = {
        "felder": [
            {
                "schluessel": "name",
                "bezeichnung": "Name",
                "typ": "text",
                "pflichtfeld": False,
                "beispiel": "ALTWERT",
                "seite": 1,
                "position": {"x": 0.14, "y": 0.105, "breite": 0.35, "hoehe": 0.045},
                "schriftgroesse": 12,
                "alten_inhalt_entfernen": True,
            }
        ]
    }
    dokument_erzeugen(original, "application/pdf", schema, {"name": "NEUWERT"}, ausgabe, "Test", "Test")
    dokument = fitz.open(ausgabe)
    try:
        text = " ".join(seite.get_text() for seite in dokument)
        assert "NEUWERT" in text
        assert "ALTWERT" not in text
    finally:
        dokument.close()


def test_renderer_laesst_original_unberuehrt_wenn_bereinigung_deaktiviert(tmp_path: Path):
    original = tmp_path / "original-transparent.pdf"
    ausgabe = tmp_path / "ausgabe-transparent.pdf"
    _pdf_mit_text(original, "ALTWERT")
    schema = {
        "felder": [
            {
                "schluessel": "zusatz",
                "bezeichnung": "Zusatz",
                "typ": "text",
                "pflichtfeld": False,
                "beispiel": "",
                "seite": 1,
                "position": {"x": 0.14, "y": 0.16, "breite": 0.35, "hoehe": 0.04},
                "schriftgroesse": 10,
                "alten_inhalt_entfernen": False,
            }
        ]
    }
    dokument_erzeugen(original, "application/pdf", schema, {"zusatz": "ZUSATZ"}, ausgabe, "Test", "Test")
    dokument = fitz.open(ausgabe)
    try:
        text = " ".join(seite.get_text() for seite in dokument)
        assert "ALTWERT" in text
        assert "ZUSATZ" in text
    finally:
        dokument.close()
