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


__all__ = ["app"]
