# A+ SmartDocs

A+ SmartDocs ist eine mandantenfähige Plattform zur intelligenten Erkennung, Korrektur, Wiederverwendung und Ausgabe beliebiger Geschäftsdokumente.

## Vorführfassung

Der aktuelle Stand bildet den vollständigen Weg vom öffentlichen Produktauftritt über Registrierung und Firmenkonto bis zur wiederverwendbaren Dokumentvorlage und erzeugten PDF-Ausgabe ab. Zusätzlich steht eine getrennte A+ Verwaltungszentrale zur Verfügung.

## Enthaltene Produktbereiche

- öffentliche deutschsprachige Produkt- und Preisseiten,
- Registrierung, Anmeldung, Sitzungsschutz und Passwort-Wiederherstellung,
- Firmenkonten mit Inhaber, Verwaltung, Bearbeitung, Nutzung und Leserechten,
- Einladungen und Unterkonten,
- KI-gestützte Erkennung variabler Inhalte und ihrer Positionen,
- dialoggestützte Korrektur und visueller Feldeditor,
- dynamische Formulare aus erkannten Dokumentfeldern,
- PDF-Ausgabe auf Grundlage der hochgeladenen Originalvorlage,
- Dokumentarchiv mit geschütztem Herunterladen,
- Tarif-, Verbrauchs- und Rechnungsansicht,
- A+ Verwaltungszentrale für Umsatz, Abonnements, Tarife und individuelle Kontogrenzen,
- Kundensicht aus der Verwaltungszentrale,
- WordPress-Erweiterung mit Kurzcode und WooCommerce-Kontobereich,
- Docker-, PostgreSQL-, Caddy- und Hetzner-Bereitstellung.

## Betrieb

```bash
cp .env.example .env
docker compose up --build
```

Danach ist die Anwendung über die in `DOMAIN` hinterlegte Adresse erreichbar.

## Automatische Prüfung

```bash
python scripts/pruefung.py
```

Die Prüfung kontrolliert öffentliche Seiten, Anmeldung, Kundenbereich, PDF-Erstellung und Verwaltungszugang mit einer temporären SQLite-Datenbank.

## WordPress

Der Ordner `wordpress-plugin/a-plus-smartdocs` enthält die installierbare WordPress-Anbindung. Der Kurzcode lautet:

```text
[a_plus_smartdocs_portal]
```

## Sicherheitshinweise vor dem öffentlichen Produktivbetrieb

Für einen echten Verkauf müssen zusätzlich ein Zahlungsanbieter, ein E-Mail-Versanddienst, rechtsgeprüfte Datenschutztexte, regelmäßige Sicherungen und ein externer Sicherheitscheck konfiguriert werden. Die Kernanwendung trennt bereits Organisationen, Sitzungen, Vorlagen und Dokumentausgaben voneinander.
