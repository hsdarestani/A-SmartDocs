from pathlib import Path

import fitz

from app.field_accuracy import _lokale_korrektur_praezise, _striktes_feld, schema_positionen_schaerfen


def _schema():
    return {
        "felder": [
            {
                "schluessel": "arbeitnehmer_name",
                "bezeichnung": "Arbeitnehmer Name",
                "hinweis": "Name des Arbeitnehmers",
                "typ": "text",
                "beispiel": "Perla Demirova",
                "seite": 1,
                "position": {"x": 0.2, "y": 0.2, "breite": 0.25, "hoehe": 0.04},
                "erkennungsquelle": "ki-und-pdf-layout",
            },
            {
                "schluessel": "arbeitnehmer_anschrift",
                "bezeichnung": "Arbeitnehmer Anschrift",
                "hinweis": "Adresse des Arbeitnehmers",
                "typ": "text",
                "beispiel": "An der Zingelswiese 5",
                "seite": 1,
                "position": {"x": 0.2, "y": 0.3, "breite": 0.35, "hoehe": 0.04},
                "erkennungsquelle": "ki-und-pdf-layout",
            },
        ]
    }


def test_employee_address_darf_nicht_auf_name_fallen():
    felder = _schema()["felder"]
    treffer = _striktes_feld(felder, "employee address")
    assert treffer is not None
    assert treffer[1]["schluessel"] == "arbeitnehmer_anschrift"


def test_wert_bleibt_getrennt_vom_originalen_suchtext():
    schema, antwort = _lokale_korrektur_praezise(_schema(), "employee address is vfvuinr")
    name, adresse = schema["felder"]
    assert name["beispiel"] == "Perla Demirova"
    assert not name.get("standardwert")
    assert adresse["beispiel"] == "An der Zingelswiese 5"
    assert adresse["standardwert"] == "vfvuinr"
    assert adresse["vorschauwert"] == "vfvuinr"
    assert "Arbeitnehmer Anschrift" in antwort


def test_fruehere_fehlzuordnung_wird_beim_korrigieren_entfernt():
    schema = _schema()
    schema["felder"][0]["beispiel"] = "vfvuinr"
    schema["felder"][0]["geprueft"] = True
    korrigiert, _ = _lokale_korrektur_praezise(schema, "employee address is vfvuinr")
    assert korrigiert["felder"][0]["beispiel"] == ""
    assert korrigiert["felder"][1]["standardwert"] == "vfvuinr"


def test_uneindeutige_zuordnung_aendert_keinen_wert():
    schema, antwort = _lokale_korrektur_praezise(_schema(), "employee is vfvuinr")
    assert all(not feld.get("standardwert") for feld in schema["felder"])
    assert "keinem Feld eindeutig" in antwort


def test_beispieltext_korrigiert_die_position_und_entfernt_unplausible_felder(tmp_path: Path):
    pdf = tmp_path / "vertrag.pdf"
    dokument = fitz.open()
    seite = dokument.new_page(width=600, height=800)
    seite.insert_text((180, 220), "Perla Demirova", fontsize=11)
    seite.insert_text((70, 500), "Das Arbeitsverhältnis wird zu den identischen vertraglichen Bedingungen fortgeführt.", fontsize=10)
    dokument.save(pdf)
    dokument.close()

    schema = {
        "felder": [
            {
                "schluessel": "arbeitnehmer_name",
                "bezeichnung": "Arbeitnehmer Name",
                "typ": "text",
                "beispiel": "Perla Demirova",
                "seite": 1,
                "position": {"x": 0.02, "y": 0.02, "breite": 0.2, "hoehe": 0.04},
                "erkennungsquelle": "ki",
            },
            {
                "schluessel": "satzfragment",
                "bezeichnung": "Arbeitsverhältnis wird zu den identischen vertraglichen Bedingungen",
                "typ": "text",
                "beispiel": "",
                "seite": 1,
                "position": {"x": 0.1, "y": 0.59, "breite": 0.7, "hoehe": 0.04},
                "erkennungsquelle": "pdf-layout",
            },
        ]
    }

    geschaerft, geaendert = schema_positionen_schaerfen(schema, pdf)
    assert geaendert is True
    assert len(geschaerft["felder"]) == 1
    feld = geschaerft["felder"][0]
    assert feld["positionsquelle"] == "beispieltext-exakt"
    assert 0.25 < feld["position"]["x"] < 0.4
    assert 0.23 < feld["position"]["y"] < 0.32


def test_live_vorschau_und_standardwerte_sind_eingebunden():
    basis = Path("app/templates/base.html").read_text(encoding="utf-8")
    verwenden = Path("app/templates/vorlage_verwenden.html").read_text(encoding="utf-8")
    skript = Path("app/static/field-live-preview.js").read_text(encoding="utf-8")
    assert "field-live-preview.js" in basis
    assert "field-live-preview.css" in basis
    assert "feld.standardwert" in verwenden
    assert "workflow-feldwert" in skript
    assert "smartdocs:schema-updated" in skript
