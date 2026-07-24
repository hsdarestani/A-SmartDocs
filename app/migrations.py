from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


ERGAENZUNGEN: dict[str, list[tuple[str, str]]] = {
    "organisationen": [
        ("strasse", "VARCHAR(180) DEFAULT ''"),
        ("plz", "VARCHAR(20) DEFAULT ''"),
        ("ort", "VARCHAR(100) DEFAULT ''"),
        ("telefon", "VARCHAR(50) DEFAULT ''"),
    ],
    "mitglieder": [
        ("passwort_hash", "VARCHAR(255) DEFAULT ''"),
        ("ist_superadmin", "BOOLEAN DEFAULT FALSE"),
        ("email_bestaetigt", "BOOLEAN DEFAULT TRUE"),
        ("erstellt_am", "TIMESTAMP WITH TIME ZONE"),
    ],
    "tarife": [
        ("beschreibung", "TEXT DEFAULT ''"),
        ("jahrespreis", "NUMERIC(10,2)"),
        ("merkmale", "JSON"),
    ],
    "abonnements": [
        ("abrechnungszeitraum", "VARCHAR(20) DEFAULT 'monatlich'"),
        ("testphase_bis", "TIMESTAMP WITH TIME ZONE"),
        ("gekuendigt_zum", "TIMESTAMP WITH TIME ZONE"),
    ],
    "dokumentvorlagen": [
        ("erstellt_von_id", "INTEGER"),
        ("inhaltstyp", "VARCHAR(100) DEFAULT 'application/pdf'"),
        ("originalgroesse", "INTEGER DEFAULT 0"),
        ("aktualisiert_am", "TIMESTAMP WITH TIME ZONE"),
    ],
}


def schema_aktualisieren(engine: Engine) -> None:
    pruefer = inspect(engine)
    vorhandene_tabellen = set(pruefer.get_table_names())
    with engine.begin() as verbindung:
        for tabelle, spalten in ERGAENZUNGEN.items():
            if tabelle not in vorhandene_tabellen:
                continue
            vorhanden = {spalte["name"] for spalte in inspect(engine).get_columns(tabelle)}
            for name, definition in spalten:
                if name in vorhanden:
                    continue
                verbindung.execute(text(f'ALTER TABLE "{tabelle}" ADD COLUMN "{name}" {definition}'))
