from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

from fastapi import Request
from sqlalchemy import select

from app.auth import _schreibzugriff_erlaubt, passwort_hashen
from app.database import Sitzung
from app.models import Arbeitsdokument, Kontorolle, Mitglied, Nutzungsereignis, Organisation
from app.store_compliance import _mitglied_loeschen


def test_store_rechtsseiten_sind_oeffentlich(client):
    for pfad, text in (
        ("/datenschutz-app", "Datenschutzhinweise für A+ SmartDocs"),
        ("/nutzungsbedingungen", "Nutzungsbedingungen"),
        ("/support", "Hilfe zu A+ SmartDocs"),
        ("/konto-loeschen", "Konto und Daten löschen"),
    ):
        antwort = client.get(pfad)
        assert antwort.status_code == 200
        assert text in antwort.text


def test_externe_kontoloeschanfrage_funktioniert_ohne_login(client):
    email = f"delete-{uuid.uuid4().hex}@example.invalid"
    antwort = client.post(
        "/konto-loeschen/anfragen",
        data={"email": email, "bestaetigung": "ja"},
    )
    assert antwort.status_code == 200
    assert "Löschanfrage eingegangen" in antwort.text
    with Sitzung() as db:
        ereignis = db.scalar(
            select(Nutzungsereignis)
            .where(Nutzungsereignis.art == "konto_loeschanfrage_extern")
            .order_by(Nutzungsereignis.id.desc())
        )
        assert ereignis is not None
        assert ereignis.einzelheiten.get("email") == email
        db.delete(ereignis)
        db.commit()


def test_jede_rolle_darf_eigenes_konto_loeschen():
    request = Request({"type": "http", "method": "POST", "path": "/einstellungen/konto-loeschen", "headers": []})
    for rolle in (Kontorolle.LESEN, Kontorolle.NUTZUNG, Kontorolle.BEARBEITUNG, Kontorolle.VERWALTUNG, Kontorolle.INHABER):
        mitglied = SimpleNamespace(ist_superadmin=False, rolle=rolle)
        assert _schreibzugriff_erlaubt(request, mitglied) is True


def test_alleiniger_inhaber_loescht_organisation_und_arbeitsdatei(tmp_path: Path):
    email = f"owner-{uuid.uuid4().hex}@example.invalid"
    datei = tmp_path / "privat.pdf"
    datei.write_bytes(b"%PDF-1.4\n%%EOF\n")
    organisation_id = None
    mitglied_id = None
    arbeitsdokument_id = None
    try:
        with Sitzung() as db:
            organisation = Organisation(name=f"Delete Test {uuid.uuid4().hex[:8]}", branche="Test")
            db.add(organisation)
            db.flush()
            mitglied = Mitglied(
                organisation_id=organisation.id,
                name="Delete Owner",
                email=email,
                passwort_hash=passwort_hashen("Delete-Test-2026!"),
                rolle=Kontorolle.INHABER,
                aktiv=True,
            )
            db.add(mitglied)
            db.flush()
            arbeitsdokument = Arbeitsdokument(
                organisation_id=organisation.id,
                erstellt_von_id=mitglied.id,
                name="Privat",
                dateiname="privat.pdf",
                speicherort=str(datei),
                inhaltstyp="application/pdf",
                originalgroesse=datei.stat().st_size,
                seiten=1,
                status="bearbeitung",
                zustand={},
            )
            db.add(arbeitsdokument)
            db.commit()
            organisation_id = organisation.id
            mitglied_id = mitglied.id
            arbeitsdokument_id = arbeitsdokument.id
            typ = _mitglied_loeschen(db, mitglied)
            assert typ == "organisation"

        with Sitzung() as db:
            assert db.get(Organisation, organisation_id) is None
            assert db.get(Mitglied, mitglied_id) is None
            assert db.get(Arbeitsdokument, arbeitsdokument_id) is None
        assert not datei.exists()
    finally:
        if organisation_id:
            with Sitzung() as db:
                organisation = db.get(Organisation, organisation_id)
                if organisation:
                    db.delete(organisation)
                    db.commit()
        datei.unlink(missing_ok=True)


def test_mobile_store_builddateien_sind_vorhanden():
    android = Path(".github/workflows/mobile-android.yml").read_text(encoding="utf-8")
    ios = Path(".github/workflows/mobile-ios.yml").read_text(encoding="utf-8")
    capacitor = Path("mobile/capacitor.config.ts").read_text(encoding="utf-8")
    native = Path("mobile/scripts/configure-native.mjs").read_text(encoding="utf-8")
    assert "de.aplussolution.smartdocs" in capacitor
    assert "targetSdkVersion = 36" in native
    assert "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON_BASE64" in android
    assert "IOS_PROVISIONING_PROFILE_BASE64" in ios
    assert "ASC_PRIVATE_KEY_BASE64" in ios
