# A+ SmartDocs

A+ SmartDocs ist eine mandantenfähige Plattform zur intelligenten Erkennung, Konfiguration und automatischen Erstellung wiederverwendbarer Dokumentvorlagen.

## Aktueller Stand

Der erste Produktkern umfasst:

- eine vollständig deutschsprachige Produktoberfläche,
- eine moderne Start- und Arbeitsoberfläche,
- den Ablauf „Dokument hochladen → Felder erkennen → im Dialog bestätigen → Vorlage speichern“,
- eine Verwaltungsansicht für Umsatz, Abonnements, Nutzung und individuelle Kontolimits,
- eine technische Grundlage für Organisationen und Unterkonten,
- einen Container-Betrieb auf dem Hetzner-Server,
- eine automatische Bereitstellung über GitHub Actions.

## Bereitstellung

Die Anwendung wird über Docker Compose betrieben. Caddy übernimmt HTTPS und leitet `smartdocs.aplus-solution.de` an die Anwendung weiter.

Die benötigten GitHub-Geheimnisse sind:

- `HOST`
- `PASS`
- `OPENAIAPI`

## Lokaler Start

```bash
cp .env.example .env
docker compose up --build
```

Danach ist die Anwendung unter `http://localhost` erreichbar.
