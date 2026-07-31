from pathlib import Path

import fitz
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.live_document_engine import (
    edit_aus_anker,
    edit_speichern,
    lokale_anweisung,
    pdf_exportieren,
    pdf_index,
    text_nach_bearbeitung,
    ziel_aufloesen,
)


def _vertrag(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 11)
    c.drawString(80, 700, "Zwischen")
    c.drawString(160, 680, "A+ Solution GmbH, Carl-Sonnenschein-Str. 57, 65936 Frankfurt am Main")
    c.drawString(80, 650, "Und")
    c.drawString(160, 630, "Perla Demirova, An der Zingelswiese 5, 65933 FFM")
    c.drawString(80, 590, "wird folgender Vertrag geschlossen")
    c.save()


def _anker(index, fragment: str):
    for seite in index["seiten"]:
        for anker in seite["anker"]:
            if fragment in anker["text"]:
                return anker
    raise AssertionError(f"Anker {fragment!r} fehlt")


def test_klickedit_verwendet_pdf_bbox_und_entfernt_alten_text(tmp_path: Path):
    pdf = tmp_path / "vertrag.pdf"
    _vertrag(pdf)
    index = pdf_index(pdf)
    anker = _anker(index, "Perla Demirova")
    edit = edit_aus_anker(anker, "Maria Keller", quelle="auswahl")
    zustand = edit_speichern({"revision": 0, "edits": []}, edit)

    text = text_nach_bearbeitung(pdf, zustand)
    assert "Perla Demirova" not in text
    assert "Maria Keller" in text
    assert edit["bbox"] == anker["bbox"]


def test_export_enthaelt_nur_den_neuen_text(tmp_path: Path):
    pdf = tmp_path / "vertrag.pdf"
    ziel = tmp_path / "fertig.pdf"
    _vertrag(pdf)
    index = pdf_index(pdf)
    anker = _anker(index, "A+ Solution GmbH")
    zustand = edit_speichern({}, edit_aus_anker(anker, "Musterfirma GmbH"))
    pdf_exportieren(pdf, zustand, ziel)

    dokument = fitz.open(ziel)
    try:
        text = "\n".join(seite.get_text("text") for seite in dokument)
    finally:
        dokument.close()
    assert "A+ Solution GmbH" not in text
    assert "Musterfirma GmbH" in text


def test_semantisches_feld_nutzt_nur_beispieltext_nicht_geschaetzte_position(tmp_path: Path):
    pdf = tmp_path / "vertrag.pdf"
    _vertrag(pdf)
    index = pdf_index(pdf)
    zustand = {
        "hinweise": [
            {
                "schluessel": "arbeitnehmer_anschrift",
                "bezeichnung": "Arbeitnehmer Anschrift",
                "beispiel": "Perla Demirova, An der Zingelswiese 5, 65933 FFM",
                "seite": 1,
                "position": {"x": 0.01, "y": 0.01, "breite": 0.01, "hoehe": 0.01},
            }
        ]
    }
    anker = ziel_aufloesen(index, zustand, "employee address")
    assert anker is not None
    assert "An der Zingelswiese 5" in anker["text"]
    assert anker["position"]["x"] > 0.1
    assert anker["position"]["y"] > 0.1


def test_haeufige_chatbefehle_laufen_lokal():
    assert lokale_anweisung("Perla Demirova → Maria Keller") == {
        "aktion": "ersetzen", "ziel": "Perla Demirova", "wert": "Maria Keller"
    }
    assert lokale_anweisung("employee address is Mainzer Landstraße 12") == {
        "aktion": "ersetzen", "ziel": "employee address", "wert": "Mainzer Landstraße 12"
    }
    assert lokale_anweisung("ersetze 13.06.2026 durch 01.08.2026") == {
        "aktion": "ersetzen", "ziel": "13.06.2026", "wert": "01.08.2026"
    }
