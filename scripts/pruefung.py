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

from app.main import app


def pruefen() -> None:
    with TestClient(app) as client:
        for pfad in ["/", "/preise", "/anmelden", "/registrieren"]:
            antwort = client.get(pfad)
            assert antwort.status_code == 200, (pfad, antwort.status_code)
            assert "A+ SmartDocs" in antwort.text or "SmartDocs" in antwort.text

        antwort = client.post(
            "/anmelden",
            data={
                "email": "demo@smartdocs.de",
                "passwort": "Aplus-Kunde-7Qm!26",
                "weiter": "/arbeitsbereich",
            },
            follow_redirects=False,
        )
        assert antwort.status_code == 303
        assert antwort.headers["location"] == "/arbeitsbereich"

        for pfad in [
            "/arbeitsbereich",
            "/vorlagen",
            "/vorlagen/1",
            "/vorlagen/1/verwenden",
            "/dokumente",
            "/team",
            "/einstellungen",
            "/abrechnung",
        ]:
            antwort = client.get(pfad)
            assert antwort.status_code == 200, (pfad, antwort.status_code)

        antwort = client.post(
            "/vorlagen/1/verwenden",
            data={
                "dokumenttitel": "Automatischer Prüfbericht",
                "kundenname": "Prüfkunde GmbH",
                "leistungsdatum": "2026-07-24",
                "leistungen": "Automatisch geprüfte Dokumentausgabe",
                "ansprechpartner": "Anna Prüfung",
            },
            follow_redirects=False,
        )
        assert antwort.status_code == 303
        assert antwort.headers["location"] == "/dokumente"
        archiv = client.get("/dokumente")
        assert "Automatischer Prüfbericht" in archiv.text

        client.post("/abmelden")
        antwort = client.post(
            "/anmelden",
            data={
                "email": "admin@aplus-solution.de",
                "passwort": "Aplus-Admin-9Vr!26",
                "weiter": "/verwaltung",
            },
            follow_redirects=False,
        )
        assert antwort.status_code == 303
        verwaltung = client.get("/verwaltung")
        assert verwaltung.status_code == 200
        assert "Geschäftsentwicklung und Kontosteuerung" in verwaltung.text

    print("A+ SmartDocs: automatische Produktprüfung erfolgreich")


if __name__ == "__main__":
    pruefen()
