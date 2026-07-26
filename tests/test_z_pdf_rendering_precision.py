from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from pathlib import Path

import fitz
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select

from app.database import Sitzung
from app.main import cfg
from app.models import Dokumentausgabe, Dokumentvorlage, Mitglied
from app.pdf_engine import dokument_erzeugen


DEMO_EMAIL = "demo@smartdocs.de"
DEMO_PASSWORT = "Aplus-Kunde-7Qm!26"


def _farbiges_pdf(ziel: Path, beispiel: str = "ALTER MUSTERWERT") -> fitz.Rect:
    breite, hoehe = A4
    x = 104
    y_unten = 592
    feld_breite = 230
    feld_hoehe = 44
    zeichner = canvas.Canvas(str(ziel), pagesize=A4)
    zeichner.setFillColor(HexColor("#C7E3EF"))
    zeichner.rect(x, y_unten, feld_breite, feld_hoehe, fill=1, stroke=0)
    zeichner.setFillColor(HexColor("#071C2E"))
    zeichner.setFont("Helvetica", 11)
    zeichner.drawString(x + 8, y_unten + 16, beispiel)
    zeichner.save()
    return fitz.Rect(x, hoehe - (y_unten + feld_hoehe), x + feld_breite, hoehe - y_unten)


def _signatur_png() -> bytes:
    bild = Image.new("RGB", (420, 150), "white")
    zeichner = ImageDraw.Draw(bild)
    zeichner.line([(25, 105), (90, 45), (150, 112), (235, 42), (300, 102), (390, 62)], fill=(8, 28, 46), width=7)
    speicher = io.BytesIO()
    bild.save(speicher, format="PNG")
    return speicher.getvalue()


def _pixel(pix: fitz.Pixmap, x: int, y: int) -> tuple[int, int, int]:
    index = (y * pix.width + x) * pix.n
    return tuple(pix.samples[index:index + 3])


def test_beispieltext_bestimmt_echte_position_und_hintergrund_bleibt_farbig(tmp_path: Path):
    original = tmp_path / "farbige-vorlage.pdf"
    erwarteter_bereich = _farbiges_pdf(original)
    ziel = tmp_path / "ausgabe.pdf"
    schema = {
        "felder": [
            {
                "schluessel": "kunde",
                "bezeichnung": "Kunde",
                "typ": "text",
                "pflichtfeld": True,
                "beispiel": "ALTER MUSTERWERT",
                "seite": 1,
                "position": {"x": 0.68, "y": 0.72, "breite": 0.22, "hoehe": 0.04},
                "schriftgroesse": 11,
                "hintergrundmodus": "automatisch",
            }
        ]
    }

    seiten = dokument_erzeugen(original, "application/pdf", schema, {"kunde": "NEUER KUNDE"}, ziel, "Prüfung", "Farbige Vorlage")
    assert seiten == 1

    with fitz.open(original) as alt, fitz.open(ziel) as neu:
        alter_treffer = alt[0].search_for("ALTER MUSTERWERT")
        neuer_treffer = neu[0].search_for("NEUER KUNDE")
        assert len(alter_treffer) == 1
        assert len(neuer_treffer) == 1
        assert not neu[0].search_for("ALTER MUSTERWERT")
        assert abs(neuer_treffer[0].x0 - alter_treffer[0].x0) < 4
        assert abs(neuer_treffer[0].y0 - alter_treffer[0].y0) < 6

        matrix = fitz.Matrix(2, 2)
        alt_pix = alt[0].get_pixmap(matrix=matrix, alpha=False)
        neu_pix = neu[0].get_pixmap(matrix=matrix, alpha=False)
        punkt_x = int((erwarteter_bereich.x1 - 8) * 2)
        punkt_y = int((erwarteter_bereich.y1 - 8) * 2)
        alt_farbe = _pixel(alt_pix, punkt_x, punkt_y)
        neu_farbe = _pixel(neu_pix, punkt_x, punkt_y)
        assert max(neu_farbe) < 245, "Der variable Bereich darf nicht mit einem weißen Rechteck überdeckt werden."
        assert max(abs(a - b) for a, b in zip(alt_farbe, neu_farbe)) < 35


def test_unterschrift_wird_als_transparentes_bild_eingebettet(tmp_path: Path):
    original = tmp_path / "unterschrift-vorlage.pdf"
    zeichner = canvas.Canvas(str(original), pagesize=A4)
    zeichner.drawString(80, 150, "Unterschrift")
    zeichner.line(180, 145, 470, 145)
    zeichner.save()

    signatur = tmp_path / "signatur.png"
    signatur.write_bytes(_signatur_png())
    ziel = tmp_path / "unterschrift-ausgabe.pdf"
    schema = {
        "felder": [
            {
                "schluessel": "signatur",
                "bezeichnung": "Unterschrift",
                "typ": "unterschrift",
                "pflichtfeld": True,
                "beispiel": "",
                "seite": 1,
                "position": {"x": 0.30, "y": 0.76, "breite": 0.48, "hoehe": 0.10},
            }
        ]
    }

    dokument_erzeugen(original, "application/pdf", schema, {"signatur": str(signatur)}, ziel, "Signatur", "Unterschrift")

    with fitz.open(ziel) as dokument:
        assert dokument[0].get_images(full=True), "Die Unterschrift muss als Bildobjekt im PDF vorhanden sein."
        text = "".join(seite.get_text() for seite in dokument)
        assert "UploadFile" not in text
        assert "filename=" not in text


def test_multipart_unterschrift_wird_von_der_webroute_als_datei_verarbeitet(client: TestClient):
    anmeldung = client.post(
        "/anmelden",
        data={"email": DEMO_EMAIL, "passwort": DEMO_PASSWORT, "weiter": "/arbeitsbereich"},
        follow_redirects=False,
    )
    assert anmeldung.status_code == 303

    with Sitzung() as db:
        mitglied = db.scalar(select(Mitglied).where(Mitglied.email == DEMO_EMAIL))
        assert mitglied is not None
        original = cfg.upload_pfad / f"signatur-route-{uuid.uuid4().hex}.pdf"
        zeichner = canvas.Canvas(str(original), pagesize=A4)
        zeichner.drawString(70, 130, "Unterschrift des Mitarbeiters")
        zeichner.line(260, 125, 520, 125)
        zeichner.save()
        schema = {
            "dokumentart": "Signaturprüfung",
            "zusammenfassung": "Prüft den echten Datei-Upload.",
            "felder": [
                {
                    "schluessel": "signatur",
                    "bezeichnung": "Unterschrift",
                    "typ": "unterschrift",
                    "pflichtfeld": True,
                    "beispiel": "",
                    "seite": 1,
                    "position": {"x": 0.43, "y": 0.77, "breite": 0.40, "hoehe": 0.09},
                }
            ],
        }
        vorlage = Dokumentvorlage(
            organisation_id=mitglied.organisation_id,
            erstellt_von_id=mitglied.id,
            name="Multipart Signaturprüfung",
            dateiname=original.name,
            speicherort=str(original),
            inhaltstyp="application/pdf",
            originalgroesse=original.stat().st_size,
            status="bereit",
            seiten=1,
            erkannte_felder=1,
            schema=schema,
            zusammenfassung=schema["zusammenfassung"],
            aktualisiert_am=datetime.now(timezone.utc),
        )
        db.add(vorlage)
        db.commit()
        db.refresh(vorlage)
        vorlage_id = vorlage.id

    antwort = client.post(
        f"/vorlagen/{vorlage_id}/verwenden",
        data={"dokumenttitel": "Echte Signaturprüfung"},
        files={"signatur": ("unterschrift.png", _signatur_png(), "image/png")},
        follow_redirects=False,
    )
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/dokumente"

    with Sitzung() as db:
        ausgabe = db.scalar(
            select(Dokumentausgabe)
            .where(Dokumentausgabe.vorlage_id == vorlage_id)
            .order_by(Dokumentausgabe.id.desc())
        )
        assert ausgabe is not None
        assert ausgabe.eingaben["signatur"] == "[Datei]"
        ausgabepfad = Path(ausgabe.speicherort)
        assert ausgabepfad.exists()

    with fitz.open(ausgabepfad) as dokument:
        assert dokument[0].get_images(full=True)
        text = "".join(seite.get_text() for seite in dokument)
        assert "UploadFile" not in text
        assert "filename=" not in text


def test_produktseiten_laden_korrigierte_komponenten(client: TestClient):
    client.post(
        "/anmelden",
        data={"email": DEMO_EMAIL, "passwort": DEMO_PASSWORT, "weiter": "/arbeitsbereich"},
        follow_redirects=False,
    )
    vorlagen = client.get("/vorlagen")
    dokumente = client.get("/dokumente")
    assert vorlagen.status_code == 200
    assert dokumente.status_code == 200
    assert "product-fixes.css" in vorlagen.text
    assert "produkt-werkzeugleiste" in vorlagen.text
    assert "vorlagenraster" in vorlagen.text
    assert "archiv-panel" in dokumente.text
