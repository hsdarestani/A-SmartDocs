from __future__ import annotations

# Zuerst werden alle bisherigen Anwendungs- und Qualitätsrouten registriert.
from .asgi import app

# Die Produktrouten ersetzen ältere Formular- und Löschrouten. Die Vorschaurouten
# werden bewusst zuletzt geladen, damit eingebettete Dateien niemals als Download
# ausgeliefert werden.
from . import product_routes as _product_routes  # noqa: E402,F401
from . import preview_routes as _preview_routes  # noqa: E402,F401


__all__ = ["app"]
