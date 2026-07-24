from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DOMAIN"] = "localhost"
os.environ["DATABASE_URL"] = "sqlite:////tmp/a-smartdocs-pruefung.sqlite3"
os.environ["DATENPFAD"] = "/tmp/a-smartdocs-pruefung-daten"
os.environ["APP_SECRET"] = "nur-fuer-automatische-pruefung"

Path("/tmp/a-smartdocs-pruefung.sqlite3").unlink(missing_ok=True)
shutil.rmtree("/tmp/a-smartdocs-pruefung-daten", ignore_errors=True)

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import Sitzung
from app.main import app
from app.models import Organisation


def anmelden(client: TestClient, email: str, passwort: str, weiter: str) -> None:
    antwort = client.post("/anmelden", data={"email": email, "passwort": passwort, "weiter": weiter}, follow_redirects=False)
    assert antwort.status_code == 303
    assert antwort.headers["location"] == weiter


def pruefen() -> None:
    with TestClient(app) as client:
        for pfad in ["/", "/preise", "/anmelden", "/registrieren", "/freischaltung-ausstehend"]:
            antwort = client.get(pfad)
            assert antwort.status_code == 200, (pfad, antwort.status_code)
            assert "A+ SmartDocs" in antwort.text or "SmartDocs" in antwort.text

        anmelden(client, "demo@smartdocs.de", "Aplus-Kunde-7Qm!26", "/arbeitsbereich")
        for pfad in ["/arbeitsbereich", "/vorlagen", "/vorlagen/1", "/vorlagen/1/verwenden", "/dokumente", "/team", "/einstellungen", "/abrechnung"]:
            antwort = client.get(pfad)
            assert antwort.status_code == 200, (pfad, antwort.status_code)

        antwort = client.post(
            "/vorlagen/1/verwenden",
            data={"dokumenttitel": "Automatischer Prüfbericht", "kundenname": "Prüfkunde GmbH", "leistungsdatum": "2026-07-24", "leistungen": "Automatisch geprüfte Dokumentausgabe", "ansprechpartner": "Anna Prüfung"},
            follow_redirects=False,
        )
        assert antwort.status_code == 303 and antwort.headers["location"] == "/dokumente"
        assert "Automatischer Prüfbericht" in client.get("/dokumente").text
        client.post("/abmelden")

        # Neues Kundenkonto bleibt bis zur Offline-Zahlungsbestätigung gesperrt.
        registrierung = client.post(
            "/registrieren",
            data={"unternehmen": "Freischaltung Test GmbH", "name": "Tina Test", "email": "tina@example.de", "passwort": "Sicheres-Passwort-42!", "tarif_id": 1, "datenschutz": "ja"},
            follow_redirects=False,
        )
        assert registrierung.status_code == 303
        assert registrierung.headers["location"] == "/freischaltung-ausstehend"
        gesperrt = client.post("/anmelden", data={"email": "tina@example.de", "passwort": "Sicheres-Passwort-42!", "weiter": "/arbeitsbereich"}, follow_redirects=False)
        assert gesperrt.status_code == 303
        assert gesperrt.headers["location"] == "/freischaltung-ausstehend"

        anmelden(client, "admin@aplus-solution.de", "Aplus-Admin-9Vr!26", "/verwaltung")
        verwaltung = client.get("/verwaltung")
        assert verwaltung.status_code == 200
        assert "Freischaltung Test GmbH" in verwaltung.text
        assert "Aktivieren" in verwaltung.text
        with Sitzung() as db:
            organisation = db.scalar(select(Organisation).where(Organisation.name == "Freischaltung Test GmbH"))
            assert organisation is not None
            organisation_id = organisation.id
        freigabe = client.post(f"/verwaltung/konto/{organisation_id}/aktivieren", data={"zeitraum": "monatlich", "zahlungshinweis": "Prüfzahlung"}, follow_redirects=False)
        assert freigabe.status_code == 303 and freigabe.headers["location"] == "/verwaltung"
        client.post("/abmelden")

        anmelden(client, "tina@example.de", "Sicheres-Passwort-42!", "/arbeitsbereich")
        assert client.get("/arbeitsbereich").status_code == 200

    print("A+ SmartDocs: automatische Produktprüfung einschließlich manueller Zahlungsfreigabe erfolgreich")


if __name__ == "__main__":
    pruefen()
