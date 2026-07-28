from pathlib import Path


def test_chat_anfrage_laeuft_als_hintergrundauftrag_und_pollt_status():
    skript = Path("app/static/simple-flow.js").read_text(encoding="utf-8")
    assert "/api/vorlagen/korrigieren-async" in skript
    assert "/korrektur-status/" in skript
    assert "statusAbwarten" in skript
    assert "A+ bearbeitet die Änderung im Hintergrund" in skript
    assert "window.location.reload()" in skript
    assert "Bitte senden Sie sie erneut" not in skript
    assert "AbortController" in skript  # nur für einzelne kurze Netzwerkaufrufe, nicht als Gesamtlimit


def test_vorlageneditor_zeigt_nur_einfache_hauptaktionen():
    vorlage = Path("app/templates/vorlage_detail.html").read_text(encoding="utf-8")
    assert "Mit A+ bearbeiten" in vorlage
    assert ">Manuell<" in vorlage
    assert "Vorlage fertigstellen" in vorlage
    assert "Weitere Einstellungen" in vorlage
    assert "Positionen im Original bestimmen" not in vorlage
    assert "Automatische Qualitätskontrolle" in vorlage  # nur als semantische Kompatibilitätsangabe


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
