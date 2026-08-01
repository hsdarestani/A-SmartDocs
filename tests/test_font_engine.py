from __future__ import annotations

from pathlib import Path

import fitz

from app import font_engine
from app import live_document_engine as engine


def _pdf_mit_schriften(pfad: Path) -> None:
    dokument = fitz.open()
    seite = dokument.new_page(width=595, height=842)
    seite.insert_text((72, 120), "Mustername bleibt im Satz.", fontname="tiro", fontsize=12)
    seite.insert_text((72, 160), "Zweite Zeile", fontname="cour", fontsize=10)
    dokument.save(pfad)
    dokument.close()


def _anker(index: dict, text: str) -> dict:
    for seiteninfo in index["seiten"]:
        for anker in seiteninfo["anker"]:
            if anker.get("klickbar", True) and anker.get("text") == text:
                return anker
    raise AssertionError(f"Anker {text!r} fehlt")


def _sichtbare_spans(pfad: Path) -> list[dict]:
    dokument = fitz.open(pfad)
    try:
        return [
            span
            for seite in dokument
            for block in seite.get_text("dict").get("blocks", [])
            if block.get("type") == 0
            for line in block.get("lines", [])
            for span in line.get("spans", [])
            if str(span.get("text") or "").strip()
        ]
    finally:
        dokument.close()


def test_index_erkennt_tatsaechliche_pdf_schrift(tmp_path: Path):
    pdf = tmp_path / "schrift.pdf"
    _pdf_mit_schriften(pdf)
    index = font_engine.pdf_index_mit_schrift(pdf)
    anker = _anker(index, "Mustername")
    assert "Times" in anker["fontname"]
    assert anker["font_ref"]
    assert anker["font_xref"] >= 0
    assert any("Times" in font["name"] for font in index["fonts"])


def test_ersatztext_verwendet_originalschrift_automatisch(tmp_path: Path):
    pdf = tmp_path / "original.pdf"
    ziel = tmp_path / "fertig.pdf"
    _pdf_mit_schriften(pdf)
    index = font_engine.pdf_index_mit_schrift(pdf)
    anker = _anker(index, "Mustername")
    edit = font_engine.edit_aus_anker_mit_schrift(anker, "Neuername", quelle="auswahl")
    edit["entfernen"] = True
    zustand = font_engine.edit_speichern_mit_schrift({"edits": [], "revision": 0}, edit)
    engine.pdf_exportieren(pdf, zustand, ziel)

    spans = _sichtbare_spans(ziel)
    ersatz = next(span for span in spans if "Neuername" in span["text"])
    assert "Times" in ersatz["font"]
    gesamter_text = " ".join(span["text"] for span in spans)
    assert "Mustername" not in gesamter_text
    assert "bleibt im Satz" in gesamter_text


def test_benutzerformat_wird_beim_naechsten_edit_uebernommen(tmp_path: Path):
    pdf = tmp_path / "auswahl.pdf"
    _pdf_mit_schriften(pdf)
    index = font_engine.pdf_index_mit_schrift(pdf)
    anker = _anker(index, "Mustername")
    edit = font_engine.edit_aus_anker_mit_schrift(anker, "Test", quelle="auswahl")
    zustand = {
        "revision": 0,
        "edits": [],
        "auswahl_schriften": {
            anker["id"]: {"font_key": "courier", "font_size": 14.5},
        },
    }
    gespeichert = font_engine.edit_speichern_mit_schrift(zustand, edit)
    neu = gespeichert["edits"][0]
    assert neu["font_key"] == "courier"
    assert neu["schriftgroesse"] == 14.5
    assert neu["font_size_user"] is True


def test_gesamtes_dokument_kann_auf_helvetica_umgestellt_werden(tmp_path: Path):
    pdf = tmp_path / "gemischt.pdf"
    ziel = tmp_path / "helvetica.pdf"
    _pdf_mit_schriften(pdf)
    zustand = {
        "revision": 1,
        "edits": [],
        "dokument_font": {"font_key": "helvetica", "stile_erhalten": True},
    }
    engine.pdf_exportieren(pdf, zustand, ziel)
    spans = _sichtbare_spans(ziel)
    assert spans
    assert all("Helvetica" in str(span.get("font") or "") for span in spans)
    text = " ".join(span["text"] for span in spans)
    assert "Mustername bleibt im Satz" in text
    assert "Zweite Zeile" in text


def test_editor_enthaelt_auswahl_und_dokumentschriftsteuerung():
    basis = Path("app/templates/workspace_editor.html").read_text(encoding="utf-8")
    skript = Path("app/static/font-controls.js").read_text(encoding="utf-8")
    assert "liveSelectionFont" in basis
    assert "liveSelectionFontSize" in basis
    assert "liveDocumentFont" in basis
    assert "Gesamtes Dokument" in basis
    assert "/selection-font" in skript
    assert "/document-font" in skript
