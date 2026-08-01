from __future__ import annotations

from pathlib import Path

import fitz

from app.live_document_engine import edit_aus_anker, pdf_exportieren
from app.partial_line_editing import ankergruppe_nach_ids, pdf_index_auf_wortebene


def _pdf_mit_satz(pfad: Path) -> None:
    dokument = fitz.open()
    seite = dokument.new_page(width=600, height=800)
    seite.insert_text(
        fitz.Point(72, 120),
        "Der Arbeitnehmer Perla Demirova wohnt in Frankfurt.",
        fontname="helv",
        fontsize=12,
        color=(0, 0, 0),
    )
    seite.insert_text(
        fitz.Point(72, 155),
        "Der Vertrag beginnt am 13.06.2026 und bleibt gültig.",
        fontname="helv",
        fontsize=11,
        color=(0, 0, 0),
    )
    dokument.save(pfad)
    dokument.close()


def _anker(index: dict, text: str) -> dict:
    return next(
        anker
        for seite in index["seiten"]
        for anker in seite["anker"]
        if anker["text"] == text
    )


def test_mehrwortwert_innerhalb_einer_zeile_wird_allein_ersetzt(tmp_path: Path):
    original = tmp_path / "original.pdf"
    ausgabe = tmp_path / "ausgabe.pdf"
    _pdf_mit_satz(original)

    index = pdf_index_auf_wortebene(original)
    perla = _anker(index, "Perla")
    demirova = _anker(index, "Demirova")
    gruppe = ankergruppe_nach_ids(index, f"{perla['id']}|{demirova['id']}")

    assert gruppe is not None
    assert gruppe["text"] == "Perla Demirova"
    assert gruppe["bbox"][0] > _anker(index, "Arbeitnehmer")["bbox"][2]
    assert gruppe["bbox"][2] < _anker(index, "wohnt")["bbox"][0]

    edit = edit_aus_anker(gruppe, "Maria Keller", quelle="auswahl", ziel=gruppe["text"])
    edit["entfernen"] = True
    pdf_exportieren(original, {"edits": [edit]}, ausgabe)

    dokument = fitz.open(ausgabe)
    try:
        text = " ".join(dokument[0].get_text("text").split())
    finally:
        dokument.close()

    assert "Perla Demirova" not in text
    assert "Maria Keller" in text
    assert "Der Arbeitnehmer" in text
    assert "wohnt in Frankfurt." in text


def test_einzelnes_wort_loescht_nicht_die_gesamte_zeile(tmp_path: Path):
    original = tmp_path / "datum-original.pdf"
    ausgabe = tmp_path / "datum-ausgabe.pdf"
    _pdf_mit_satz(original)

    index = pdf_index_auf_wortebene(original)
    datum = _anker(index, "13.06.2026")
    gruppe = ankergruppe_nach_ids(index, datum["id"])
    assert gruppe is not None

    edit = edit_aus_anker(gruppe, "01.08.2026", quelle="auswahl", ziel="13.06.2026")
    edit["entfernen"] = True
    pdf_exportieren(original, {"edits": [edit]}, ausgabe)

    dokument = fitz.open(ausgabe)
    try:
        text = " ".join(dokument[0].get_text("text").split())
    finally:
        dokument.close()

    assert "13.06.2026" not in text
    assert "01.08.2026" in text
    assert "Der Vertrag beginnt am" in text
    assert "und bleibt gültig." in text


def test_ui_verschickt_eine_zusammenhaengende_wortgruppe():
    template = Path("app/templates/workspace_editor.html").read_text(encoding="utf-8")
    skript = Path("app/static/live-workspace.js").read_text(encoding="utf-8")

    assert "data-line-id" in template
    assert "data-word-order" in template
    assert "rangeBetween" in skript
    assert "selectedAnchorIds.join('|')" in skript
    assert "über mehrere Wörter ziehen" in template
