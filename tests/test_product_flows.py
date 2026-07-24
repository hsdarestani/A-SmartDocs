from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import func, select

from app.auth import passwort_hashen
from app.database import Sitzung
from app.main import cfg
from app.models import (
    Abonnement,
    Dokumentausgabe,
    Dokumentvorlage,
    Einladung,
    Kontorolle,
    Mitglied,
    Organisation,
    Rechnung,
    Tarif,
)


KUNDENPASSWORT = "Sicheres-Passwort-42!"
ADMIN_EMAIL = "admin@aplus-solution.de"
ADMIN_PASSWORT = "Aplus-Admin-9Vr!26"
DEMO_EMAIL = "demo@smartdocs.de"
DEMO_PASSWORT = "Aplus-Kunde-7Qm!26"


def eindeutige_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.de"


def tarif_id(name: str) -> int:
    with Sitzung() as db:
        tarif = db.scalar(select(Tarif).where(Tarif.name == name))
        assert tarif is not None
        return tarif.id


def anmelden(client: TestClient, email: str, passwort: str, weiter: str = "/arbeitsbereich"):
    return client.post(
        "/anmelden",
        data={"email": email, "passwort": passwort, "weiter": weiter},
        follow_redirects=False,
    )


def admin_anmelden(client: TestClient) -> None:
    antwort = anmelden(client, ADMIN_EMAIL, ADMIN_PASSWORT, "/verwaltung")
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/verwaltung"


def registrieren(client: TestClient, email: str, unternehmen: str, tarifname: str = "Start") -> int:
    antwort = client.post(
        "/registrieren",
        data={
            "unternehmen": unternehmen,
            "name": "Test Inhaber",
            "email": email,
            "passwort": KUNDENPASSWORT,
            "tarif_id": tarif_id(tarifname),
            "datenschutz": "ja",
        },
        follow_redirects=False,
    )
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/freischaltung-ausstehend"
    with Sitzung() as db:
        mitglied = db.scalar(select(Mitglied).where(Mitglied.email == email))
        assert mitglied is not None
        return mitglied.organisation_id


def aktivieren(client: TestClient, organisation_id: int, zeitraum: str = "monatlich") -> None:
    client.post("/abmelden")
    admin_anmelden(client)
    antwort = client.post(
        f"/verwaltung/konto/{organisation_id}/aktivieren",
        data={"zeitraum": zeitraum, "zahlungshinweis": "Automatischer Test: Offline-Zahlung bestätigt"},
        follow_redirects=False,
    )
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/verwaltung"
    client.post("/abmelden")


def aktives_konto(client: TestClient, tarifname: str = "Start", prefix: str = "kunde") -> tuple[str, int]:
    email = eindeutige_email(prefix)
    organisation_id = registrieren(client, email, f"{prefix.title()} GmbH", tarifname)
    aktivieren(client, organisation_id)
    return email, organisation_id


def pdf_bytes(text: str = "A+ SmartDocs Testdokument") -> bytes:
    speicher = io.BytesIO()
    zeichner = canvas.Canvas(speicher, pagesize=A4)
    zeichner.drawString(50, 780, text)
    zeichner.save()
    return speicher.getvalue()


def bereite_vorlage(organisation_id: int, erstellt_von_id: int, name: str = "Testvorlage") -> int:
    pfad = cfg.upload_pfad / f"pytest-{uuid.uuid4().hex}.pdf"
    pfad.write_bytes(pdf_bytes(name))
    schema = {
        "dokumentart": "Prüfdokument",
        "zusammenfassung": "Vorlage für automatisierte Produkttests.",
        "felder": [
            {
                "schluessel": "kundenname",
                "bezeichnung": "Kundenname",
                "typ": "text",
                "pflichtfeld": True,
                "seite": 1,
                "position": {"x": 0.1, "y": 0.2, "breite": 0.4, "hoehe": 0.04},
                "schriftgroesse": 10,
            },
            {
                "schluessel": "datum",
                "bezeichnung": "Datum",
                "typ": "datum",
                "pflichtfeld": True,
                "seite": 1,
                "position": {"x": 0.55, "y": 0.2, "breite": 0.25, "hoehe": 0.04},
                "schriftgroesse": 10,
            },
        ],
        "rueckfragen": [],
    }
    with Sitzung() as db:
        vorlage = Dokumentvorlage(
            organisation_id=organisation_id,
            erstellt_von_id=erstellt_von_id,
            name=name,
            dateiname=pfad.name,
            speicherort=str(pfad),
            inhaltstyp="application/pdf",
            originalgroesse=pfad.stat().st_size,
            status="bereit",
            seiten=1,
            erkannte_felder=2,
            schema=schema,
            zusammenfassung=schema["zusammenfassung"],
            aktualisiert_am=datetime.now(timezone.utc),
        )
        db.add(vorlage)
        db.commit()
        db.refresh(vorlage)
        return vorlage.id


def inhaber_id(organisation_id: int) -> int:
    with Sitzung() as db:
        mitglied = db.scalar(
            select(Mitglied).where(
                Mitglied.organisation_id == organisation_id,
                Mitglied.rolle == Kontorolle.INHABER,
            )
        )
        assert mitglied is not None
        return mitglied.id


def test_oeffentliche_seiten_marke_und_deutsche_texte(client: TestClient):
    for pfad in ["/", "/preise", "/anmelden", "/registrieren", "/freischaltung-ausstehend"]:
        antwort = client.get(pfad)
        assert antwort.status_code == 200
        assert "SmartDocs" in antwort.text
    start = client.get("/").text
    assert "A+ Solution" in start
    assert "Kostenlos" in start or "kostenlos" in start


def test_registrierungsvalidierung_und_wartestatus(client: TestClient):
    ungueltig = client.post(
        "/registrieren",
        data={
            "unternehmen": "Fehler GmbH",
            "name": "Fehler Nutzer",
            "email": "keine-email",
            "passwort": KUNDENPASSWORT,
            "tarif_id": tarif_id("Start"),
            "datenschutz": "ja",
        },
        follow_redirects=False,
    )
    assert ungueltig.status_code == 303
    assert ungueltig.headers["location"].startswith("/registrieren")

    ohne_datenschutz_email = eindeutige_email("ohne-datenschutz")
    ohne_datenschutz = client.post(
        "/registrieren",
        data={
            "unternehmen": "Ohne Datenschutz GmbH",
            "name": "Test Nutzer",
            "email": ohne_datenschutz_email,
            "passwort": KUNDENPASSWORT,
            "tarif_id": tarif_id("Start"),
        },
        follow_redirects=False,
    )
    assert ohne_datenschutz.status_code == 303
    with Sitzung() as db:
        assert db.scalar(select(Mitglied).where(Mitglied.email == ohne_datenschutz_email)) is None

    kurze_email = eindeutige_email("kurz")
    kurze = client.post(
        "/registrieren",
        data={
            "unternehmen": "Kurzes Passwort GmbH",
            "name": "Test Nutzer",
            "email": kurze_email,
            "passwort": "123",
            "tarif_id": tarif_id("Start"),
            "datenschutz": "ja",
        },
        follow_redirects=False,
    )
    assert kurze.status_code == 303
    with Sitzung() as db:
        assert db.scalar(select(Mitglied).where(Mitglied.email == kurze_email)) is None

    email = eindeutige_email("wartend")
    organisation_id = registrieren(client, email, "Wartende Zahlung GmbH")
    with Sitzung() as db:
        organisation = db.get(Organisation, organisation_id)
        mitglied = db.scalar(select(Mitglied).where(Mitglied.email == email))
        abo = db.scalar(select(Abonnement).where(Abonnement.organisation_id == organisation_id))
        rechnung = db.scalar(select(Rechnung).where(Rechnung.organisation_id == organisation_id))
        assert organisation is not None and not organisation.aktiv
        assert mitglied is not None and not mitglied.aktiv
        assert abo is not None and abo.status == "wartet_auf_zahlung"
        assert rechnung is not None and rechnung.status == "zahlung_ausstehend"


def test_manuelle_zahlung_aktiviert_konto_erst_durch_admin(client: TestClient):
    email = eindeutige_email("freigabe")
    organisation_id = registrieren(client, email, "Freigabe GmbH", "Unternehmen")

    gesperrt = anmelden(client, email, KUNDENPASSWORT)
    assert gesperrt.status_code == 303
    assert gesperrt.headers["location"] == "/freischaltung-ausstehend"

    aktivieren(client, organisation_id)
    with Sitzung() as db:
        organisation = db.get(Organisation, organisation_id)
        mitglied = db.scalar(select(Mitglied).where(Mitglied.email == email))
        abo = db.scalar(select(Abonnement).where(Abonnement.organisation_id == organisation_id))
        rechnung = db.scalar(
            select(Rechnung).where(Rechnung.organisation_id == organisation_id).order_by(Rechnung.id.desc())
        )
        assert organisation is not None and organisation.aktiv
        assert mitglied is not None and mitglied.aktiv
        assert abo is not None and abo.status == "aktiv" and abo.aktiviert_am is not None
        assert rechnung is not None and rechnung.status == "bezahlt"

    erfolgreich = anmelden(client, email, KUNDENPASSWORT)
    assert erfolgreich.status_code == 303
    assert erfolgreich.headers["location"] == "/arbeitsbereich"
    assert client.get("/arbeitsbereich").status_code == 200


def test_tarifwechsel_bleibt_bis_zahlungsfreigabe_offen(client: TestClient):
    email, organisation_id = aktives_konto(client, "Start", "tarifwechsel")
    antwort = anmelden(client, email, KUNDENPASSWORT)
    assert antwort.status_code == 303
    professionell = tarif_id("Professionell")

    anfrage = client.post(
        "/abrechnung/tarif-wechseln",
        data={"tarif_id": professionell, "zeitraum": "jaehrlich"},
        follow_redirects=False,
    )
    assert anfrage.status_code == 303
    with Sitzung() as db:
        abo = db.scalar(select(Abonnement).where(Abonnement.organisation_id == organisation_id))
        assert abo is not None
        assert abo.tarif.name == "Start"
        assert abo.angefragter_tarif_id == professionell
        assert abo.angefragter_zeitraum == "jaehrlich"
        offen = db.scalar(
            select(Rechnung).where(
                Rechnung.organisation_id == organisation_id,
                Rechnung.status == "zahlung_ausstehend",
            )
        )
        assert offen is not None
    abrechnung = client.get("/abrechnung")
    assert "Offene Tarifanfrage" in abrechnung.text
    assert "MANUELLE ZAHLUNG" in abrechnung.text
    assert "VISA" not in abrechnung.text
    assert "OFFLINE PAYMENT" not in abrechnung.text

    aktivieren(client, organisation_id)
    with Sitzung() as db:
        abo = db.scalar(select(Abonnement).where(Abonnement.organisation_id == organisation_id))
        assert abo is not None
        assert abo.tarif.name == "Professionell"
        assert abo.abrechnungszeitraum == "jaehrlich"
        assert abo.angefragter_tarif_id is None
        assert abo.angefragter_zeitraum is None
        offene_anzahl = db.scalar(
            select(func.count(Rechnung.id)).where(
                Rechnung.organisation_id == organisation_id,
                Rechnung.status == "zahlung_ausstehend",
            )
        )
        assert offene_anzahl == 0


def test_sperren_und_erneut_freischalten(client: TestClient):
    email, organisation_id = aktives_konto(client, "Start", "sperrung")
    admin_anmelden(client)
    sperren = client.post(f"/verwaltung/konto/{organisation_id}/sperren", follow_redirects=False)
    assert sperren.status_code == 303
    client.post("/abmelden")

    blockiert = anmelden(client, email, KUNDENPASSWORT)
    assert blockiert.status_code == 303
    assert blockiert.headers["location"] == "/anmelden"

    aktivieren(client, organisation_id)
    wieder_da = anmelden(client, email, KUNDENPASSWORT)
    assert wieder_da.status_code == 303
    assert wieder_da.headers["location"] == "/arbeitsbereich"


def test_mandantentrennung_fuer_vorlagen_und_dateien(client: TestClient):
    email_a, org_a = aktives_konto(client, "Unternehmen", "mandant-a")
    email_b, _org_b = aktives_konto(client, "Unternehmen", "mandant-b")
    vorlage_id = bereite_vorlage(org_a, inhaber_id(org_a), "Nur Mandant A")

    anmelden(client, email_b, KUNDENPASSWORT)
    assert client.get(f"/vorlagen/{vorlage_id}").status_code == 404
    assert client.get(f"/vorlagen/{vorlage_id}/datei").status_code == 404

    client.post("/abmelden")
    anmelden(client, email_a, KUNDENPASSWORT)
    assert client.get(f"/vorlagen/{vorlage_id}").status_code == 200
    assert client.get(f"/vorlagen/{vorlage_id}/datei").status_code == 200


def test_upload_analyse_schema_bestaetigung_und_vorlagenlimit(client: TestClient):
    email, organisation_id = aktives_konto(client, "Start", "vorlagenlimit")

    admin_anmelden(client)
    grenzen = client.patch(
        f"/api/verwaltung/konten/{organisation_id}/grenzen",
        json={
            "individueller_preis": None,
            "dokumente": 10,
            "vorlagen": 1,
            "unterkonten": 1,
            "speicher_mb": 100,
        },
    )
    assert grenzen.status_code == 200
    client.post("/abmelden")
    anmelden(client, email, KUNDENPASSWORT)

    falscher_typ = client.post(
        "/api/vorlagen/analysieren",
        data={"name": "Unzulässig"},
        files={"datei": ("datei.zip", b"nicht erlaubt", "application/zip")},
    )
    assert falscher_typ.status_code == 415

    zu_gross = client.post(
        "/api/vorlagen/analysieren",
        data={"name": "Zu groß"},
        files={"datei": ("gross.pdf", b"x" * (2 * 1024 * 1024 + 100), "application/pdf")},
    )
    assert zu_gross.status_code == 413

    erste = client.post(
        "/api/vorlagen/analysieren",
        data={"name": "Erste erkannte Vorlage"},
        files={"datei": ("muster.pdf", pdf_bytes(), "application/pdf")},
    )
    assert erste.status_code == 200
    daten = erste.json()
    assert daten["status"] == "Bestätigung erforderlich"
    vorlage_id = daten["vorlage_id"]
    assert len(daten["schema"]["felder"]) >= 1

    korrektur = client.post(
        "/api/vorlagen/korrigieren",
        json={"vorlage_id": vorlage_id, "nachricht": "Kundenname soll ein Pflichtfeld bleiben."},
    )
    assert korrektur.status_code == 200

    neues_schema = korrektur.json()["schema"]
    speichern = client.put(f"/api/vorlagen/{vorlage_id}/schema", json={"schema": neues_schema})
    assert speichern.status_code == 200
    bestaetigen = client.post(f"/api/vorlagen/{vorlage_id}/bestaetigen")
    assert bestaetigen.status_code == 200
    assert bestaetigen.json()["status"] == "bereit"
    assert client.get(f"/vorlagen/{vorlage_id}/verwenden").status_code == 200

    zweite = client.post(
        "/api/vorlagen/analysieren",
        data={"name": "Zweite Vorlage"},
        files={"datei": ("muster-2.pdf", pdf_bytes("Zweite"), "application/pdf")},
    )
    assert zweite.status_code == 409


def test_pflichtfelder_pdf_archiv_download_und_loeschen(client: TestClient):
    anmelden(client, DEMO_EMAIL, DEMO_PASSWORT)
    with Sitzung() as db:
        vorlage = db.scalar(
            select(Dokumentvorlage).where(
                Dokumentvorlage.name == "Leistungsnachweis – Demo",
                Dokumentvorlage.status == "bereit",
            )
        )
        assert vorlage is not None
        vorlage_id = vorlage.id
        vorher = db.scalar(select(func.count(Dokumentausgabe.id)).where(Dokumentausgabe.organisation_id == vorlage.organisation_id))

    unvollstaendig = client.post(
        f"/vorlagen/{vorlage_id}/verwenden",
        data={"dokumenttitel": "Unvollständiger Bericht", "kundenname": ""},
        follow_redirects=False,
    )
    assert unvollstaendig.status_code == 303
    assert unvollstaendig.headers["location"] == f"/vorlagen/{vorlage_id}/verwenden"
    with Sitzung() as db:
        nachher = db.scalar(select(func.count(Dokumentausgabe.id)).where(Dokumentausgabe.vorlage_id == vorlage_id))
        assert nachher == vorher

    vollstaendig = client.post(
        f"/vorlagen/{vorlage_id}/verwenden",
        data={
            "dokumenttitel": "Geprüfter Kundenbericht",
            "kundenname": "Prüfkunde GmbH",
            "leistungsdatum": "2026-07-24",
            "leistungen": "Vollständige automatisierte Leistung",
            "ansprechpartner": "Anna Prüfung",
        },
        follow_redirects=False,
    )
    assert vollstaendig.status_code == 303
    assert vollstaendig.headers["location"] == "/dokumente"
    archiv = client.get("/dokumente")
    assert "Geprüfter Kundenbericht" in archiv.text

    with Sitzung() as db:
        ausgabe = db.scalar(select(Dokumentausgabe).where(Dokumentausgabe.titel == "Geprüfter Kundenbericht"))
        assert ausgabe is not None
        ausgabe_id = ausgabe.id
        pfad = Path(ausgabe.speicherort)
        assert pfad.exists() and pfad.stat().st_size > 500

    download = client.get(f"/dokumente/{ausgabe_id}/herunterladen")
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF")

    loeschen = client.post(f"/dokumente/{ausgabe_id}/loeschen", follow_redirects=False)
    assert loeschen.status_code == 303
    with Sitzung() as db:
        assert db.get(Dokumentausgabe, ausgabe_id) is None
    assert not pfad.exists()


def test_teameinladung_annahme_und_limit(client: TestClient):
    inhaber_email, organisation_id = aktives_konto(client, "Start", "team")
    anmelden(client, inhaber_email, KUNDENPASSWORT)
    team_email = eindeutige_email("leser")
    einladen = client.post(
        "/team/einladen",
        data={"email": team_email, "rolle": Kontorolle.LESEN.value},
        follow_redirects=False,
    )
    assert einladen.status_code == 303
    with Sitzung() as db:
        einladung = db.scalar(select(Einladung).where(Einladung.email == team_email, Einladung.angenommen.is_(False)))
        assert einladung is not None
        token = einladung.token

    client.post("/abmelden")
    assert client.get(f"/einladung/{token}").status_code == 200
    annehmen = client.post(
        f"/einladung/{token}",
        data={"name": "Lesender Nutzer", "passwort": KUNDENPASSWORT},
        follow_redirects=False,
    )
    assert annehmen.status_code == 303
    assert annehmen.headers["location"] == "/arbeitsbereich"
    assert client.get("/arbeitsbereich").status_code == 200

    client.post("/abmelden")
    anmelden(client, inhaber_email, KUNDENPASSWORT)
    zweites_email = eindeutige_email("zu-viel")
    client.post(
        "/team/einladen",
        data={"email": zweites_email, "rolle": Kontorolle.NUTZUNG.value},
        follow_redirects=False,
    )
    with Sitzung() as db:
        assert db.scalar(select(Einladung).where(Einladung.email == zweites_email)) is None
        anzahl = db.scalar(select(func.count(Mitglied.id)).where(Mitglied.organisation_id == organisation_id))
        assert anzahl == 2


def test_rollenrechte_lesen_nutzung_und_bearbeitung(client: TestClient):
    inhaber_email, organisation_id = aktives_konto(client, "Unternehmen", "rollen")
    vorlage_id = bereite_vorlage(organisation_id, inhaber_id(organisation_id), "Rollentest")
    rollen = {
        Kontorolle.LESEN: eindeutige_email("rolle-lesen"),
        Kontorolle.NUTZUNG: eindeutige_email("rolle-nutzung"),
        Kontorolle.BEARBEITUNG: eindeutige_email("rolle-bearbeitung"),
    }
    with Sitzung() as db:
        for rolle, email in rollen.items():
            db.add(
                Mitglied(
                    organisation_id=organisation_id,
                    name=f"Rolle {rolle.value}",
                    email=email,
                    passwort_hash=passwort_hashen(KUNDENPASSWORT),
                    rolle=rolle,
                    aktiv=True,
                    email_bestaetigt=True,
                )
            )
        db.commit()

    anmelden(client, rollen[Kontorolle.LESEN], KUNDENPASSWORT)
    assert client.get(f"/vorlagen/{vorlage_id}").status_code == 200
    lesen_schreiben = client.post(
        f"/vorlagen/{vorlage_id}/verwenden",
        data={"dokumenttitel": "Nicht erlaubt", "kundenname": "A", "datum": "2026-07-24"},
    )
    assert lesen_schreiben.status_code == 403

    client.post("/abmelden")
    anmelden(client, rollen[Kontorolle.NUTZUNG], KUNDENPASSWORT)
    nutzen = client.post(
        f"/vorlagen/{vorlage_id}/verwenden",
        data={"dokumenttitel": "Vom Nutzer erstellt", "kundenname": "Nutzung GmbH", "datum": "2026-07-24"},
        follow_redirects=False,
    )
    assert nutzen.status_code == 303
    assert nutzen.headers["location"] == "/dokumente"
    schema_verboten = client.put(
        f"/api/vorlagen/{vorlage_id}/schema",
        json={"schema": {"felder": []}},
    )
    assert schema_verboten.status_code == 403

    client.post("/abmelden")
    anmelden(client, rollen[Kontorolle.BEARBEITUNG], KUNDENPASSWORT)
    with Sitzung() as db:
        vorlage = db.get(Dokumentvorlage, vorlage_id)
        assert vorlage is not None
        schema = vorlage.schema
    schema_erlaubt = client.put(f"/api/vorlagen/{vorlage_id}/schema", json={"schema": schema})
    assert schema_erlaubt.status_code == 200

    client.post("/abmelden")
    anmelden(client, inhaber_email, KUNDENPASSWORT)
    assert client.get("/team").status_code == 200


def test_admin_kann_individuelle_grenzen_setzen(client: TestClient):
    email, organisation_id = aktives_konto(client, "Start", "grenzen")
    anmelden(client, email, KUNDENPASSWORT)
    nicht_admin = client.patch(
        f"/api/verwaltung/konten/{organisation_id}/grenzen",
        json={"individueller_preis": 55, "dokumente": 77, "vorlagen": 8, "unterkonten": 3, "speicher_mb": 4096},
    )
    assert nicht_admin.status_code == 403

    client.post("/abmelden")
    admin_anmelden(client)
    admin = client.patch(
        f"/api/verwaltung/konten/{organisation_id}/grenzen",
        json={"individueller_preis": 55, "dokumente": 77, "vorlagen": 8, "unterkonten": 3, "speicher_mb": 4096},
    )
    assert admin.status_code == 200
    with Sitzung() as db:
        abo = db.scalar(select(Abonnement).where(Abonnement.organisation_id == organisation_id))
        assert abo is not None
        assert float(abo.individueller_preis) == 55
        assert abo.dokument_limit == 77
        assert abo.vorlagen_limit == 8
        assert abo.unterkonten_limit == 3
        assert abo.speicher_limit_mb == 4096


def test_passwort_vergessen_verraet_keine_konten(client: TestClient):
    existiert = client.post("/passwort-vergessen", data={"email": DEMO_EMAIL}, follow_redirects=False)
    nicht_existiert = client.post(
        "/passwort-vergessen",
        data={"email": eindeutige_email("unbekannt")},
        follow_redirects=False,
    )
    assert existiert.status_code == nicht_existiert.status_code == 303
    assert existiert.headers["location"] == nicht_existiert.headers["location"] == "/anmelden"
