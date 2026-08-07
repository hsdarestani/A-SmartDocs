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

# Wort- und Phrasenauswahl schützt feste Satzteile vor versehentlichem Löschen.
from . import partial_line_editing as _partial_line_editing  # noqa: E402,F401
from . import partial_line_compat as _partial_line_compat  # noqa: E402,F401
from . import partial_line_renderer as _partial_line_renderer  # noqa: E402,F401

# Ganz zuletzt wird die tatsächliche PDF-Schriftressource erkannt und für Ersatztext,
# freie Einfügungen sowie die optionale Dokumentschrift verwendet.
from . import font_engine as _font_engine  # noqa: E402,F401

# Öffentliche Datenschutz-, Support- und Kontolöschrouten sind Teil der Store-
# Konformität und werden auf Web, Android und iOS identisch angeboten.
from . import store_compliance as _store_compliance  # noqa: E402,F401


__all__ = ["app"]
