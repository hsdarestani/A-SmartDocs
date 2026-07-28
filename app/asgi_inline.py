from __future__ import annotations

# Zuerst werden alle bisherigen Anwendungs- und Qualitätsrouten registriert.
from .asgi import app

# Die Produktrouten ersetzen ältere Formular- und Löschrouten. Die Vorschaurouten
# werden bewusst danach geladen, damit eingebettete Dateien niemals als Download
# ausgeliefert werden.
from . import product_routes as _product_routes  # noqa: E402,F401
from . import preview_routes as _preview_routes  # noqa: E402,F401

# Der neue Chat-/Manuell-Workflow wird zuletzt geladen. Er ersetzt die alte
# Detailseite, stellt seitenstabile PNG-Vorschauen bereit und installiert den
# präziseren PDF-Renderer.
from . import workflow_v2 as _workflow_v2  # noqa: E402,F401

# Chatkorrekturen werden als persistente Hintergrundaufträge gestartet. Dadurch
# bleibt keine Browseranfrage an der externen KI-Verbindung hängen.
from . import chat_jobs as _chat_jobs  # noqa: E402,F401

# Feldnamen, Rollenbegriffe und Positionen werden zuletzt gegen das Original-PDF
# geprüft. Dadurch darf eine Adresse nie mehr auf ein Namensfeld fallen.
from . import field_accuracy as _field_accuracy  # noqa: E402,F401


__all__ = ["app"]
