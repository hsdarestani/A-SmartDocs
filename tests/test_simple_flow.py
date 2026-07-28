from pathlib import Path


def test_chat_anfrage_hat_timeout_und_entsperrt_oberflaeche():
    skript = Path("app/static/simple-flow.js").read_text(encoding="utf-8")
    assert "AbortController" in skript
    assert "30000" in skript
    assert "Die Änderung dauert zu lange" in skript
    assert "form.classList.remove('verarbeitet')" in skript
    assert "textfeld.disabled = false" in skript


def test_vorlageneditor_zeigt_nur_einfache_hauptaktionen():
    vorlage = Path("app/templates/vorlage_detail.html").read_text(encoding="utf-8")
    assert "Mit A+ bearbeiten" in vorlage
    assert ">Manuell<" in vorlage
    assert "Vorlage fertigstellen" in vorlage
    assert "Weitere Einstellungen" in vorlage
    assert "Automatische Qualitätskontrolle" not in vorlage
    assert "Positionen im Original bestimmen" not in vorlage


def test_upload_ist_auf_einen_schritt_reduziert():
    vorlage = Path("app/templates/vorlage_neu.html").read_text(encoding="utf-8")
    assert "Dokument hochladen" in vorlage
    assert "Datei hier ablegen" in vorlage
    assert "Vorlage erstellen" in vorlage
    assert "Schritt 01" not in vorlage
    assert "Dokumentstruktur lesen" not in vorlage


def test_dokumenterstellung_ist_ein_schrittweiser_ablauf():
    vorlage = Path("app/templates/vorlage_verwenden.html").read_text(encoding="utf-8")
    skript = Path("app/static/simple-flow.js").read_text(encoding="utf-8")
    assert "formularZurueck" in vorlage
    assert "formularWeiter" in vorlage
    assert "PDF erstellen" in vorlage
    assert "formularSchrittAnzeige" in vorlage
    assert "ungueltig.reportValidity" in skript
    assert "abschnitt.hidden" in skript
