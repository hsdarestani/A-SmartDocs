from __future__ import annotations

from sqlalchemy import select

from app.database import Sitzung
from app.models import Dokumentvorlage, Mitglied


DEMO_EMAIL = "demo@smartdocs.de"
DEMO_PASSWORT = "Aplus-Kunde-7Qm!26"


def _anmelden(client) -> None:
    antwort = client.post(
        "/anmelden",
        data={"email": DEMO_EMAIL, "passwort": DEMO_PASSWORT, "weiter": "/arbeitsbereich"},
        follow_redirects=False,
    )
    assert antwort.status_code == 303


def _demo_vorlage() -> int:
    with Sitzung() as db:
        mitglied = db.scalar(select(Mitglied).where(Mitglied.email == DEMO_EMAIL))
        assert mitglied is not None
        vorlage = db.scalar(
            select(Dokumentvorlage)
            .where(Dokumentvorlage.organisation_id == mitglied.organisation_id)
            .order_by(Dokumentvorlage.id)
        )
        assert vorlage is not None
        return vorlage.id


def test_ausfuellseite_zeigt_beide_editorzugaenge(client):
    _anmelden(client)
    vorlage_id = _demo_vorlage()

    antwort = client.get(f"/vorlagen/{vorlage_id}/verwenden")

    assert antwort.status_code == 200
    assert "Mit Assistent bearbeiten" in antwort.text
    assert "Manuell bearbeiten" in antwort.text
    assert f'href="/vorlagen/{vorlage_id}?modus=chat"' in antwort.text
    assert f'href="/vorlagen/{vorlage_id}?modus=manuell"' in antwort.text
    assert "Vorlageneditor öffnen" in antwort.text


def test_editor_laesst_sich_mit_modusparameter_oeffnen(client):
    _anmelden(client)
    vorlage_id = _demo_vorlage()

    chat = client.get(f"/vorlagen/{vorlage_id}?modus=chat")
    manuell = client.get(f"/vorlagen/{vorlage_id}?modus=manuell")
    skript = client.get("/statisch/editor-entry-mode.js")

    assert chat.status_code == 200
    assert manuell.status_code == 200
    assert 'data-workflow-modus="chat"' in chat.text
    assert 'data-workflow-modus="manuell"' in manuell.text
    assert "editor-entry-mode.js" in chat.text
    assert skript.status_code == 200
    assert "URLSearchParams" in skript.text
    assert "workflowFeldWerkzeug" in skript.text
    assert "workflowChatText" in skript.text
