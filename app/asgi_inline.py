from __future__ import annotations

# Zuerst werden alle bisherigen Anwendungs- und Qualitätsrouten registriert.
from .asgi import app

# Die Produktrouten ersetzen ältere Formular- und Löschrouten. Die Vorschaurouten
# werden bewusst danach geladen, damit eingebettete Dateien niemals als Download
# ausgeliefert werden.
from . import product_routes as _product_routes  # noqa: E402,F401
from . import preview_routes as _preview_routes  # noqa: E402,F401

# Der bisherige Vorlageneditor bleibt für den spezialisierten Vorlagenbereich erhalten.
from . import workflow_v2 as _workflow_v2  # noqa: E402,F401
from . import chat_jobs as _chat_jobs  # noqa: E402,F401
from . import field_accuracy as _field_accuracy  # noqa: E402,F401

# Der direkte Upload → Chat → Export Arbeitsfluss wird bewusst zuletzt geladen.
# Er ersetzt ausschließlich den bisherigen KPI-Startbereich; Vorlagen, Team,
# Abrechnung und Historie bleiben als spezialisierte Bereiche erreichbar.
from . import live_workspace as _live_workspace  # noqa: E402,F401

# Freie Einfügungen sind eigenständige Objekte: verschieben und löschen muss
# unabhängig vom Chat- und Textersetzungsweg möglich sein.
from . import workspace_object_ops as _workspace_object_ops  # noqa: E402,F401

# Zuletzt wird die Auswahl von ganzen PDF-Spans auf Wörter und zusammenhängende
# Phrasen umgestellt. Dadurch löscht eine Änderung niemals mehr automatisch die
# komplette Textzeile.
from . import partial_line_editing as _partial_line_editing  # noqa: E402,F401


__all__ = ["app"]
