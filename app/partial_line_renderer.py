from __future__ import annotations

from typing import Any

import fitz

from . import live_document_engine as _engine
from . import workspace_interaction_v2 as _interaction


def seite_mit_praezisen_teilbereichen_bearbeiten(seite: fitz.Page, edits: list[dict[str, Any]]) -> None:
    """Redigiert nur die ausgewählten Wort-BBoxen und schützt Nachbartext."""
    operationen: list[tuple[dict[str, Any], fitz.Rect]] = []
    checkbox_edits: list[dict[str, Any]] = []
    hat_loeschung = False

    for edit in edits:
        if edit.get("quelle") == "checkbox":
            checkbox_edits.append(edit)
            continue
        rect = fitz.Rect(*(edit.get("bbox") or [0, 0, 0, 0]))
        if rect.is_empty or rect.width <= 0 or rect.height <= 0:
            continue
        entfernen = bool(edit.get("entfernen", bool(str(edit.get("alter_text") or "").strip())))
        if entfernen:
            # Horizontale Zugabe bewusst sehr klein: bei Wortankern darf weder das
            # vorherige noch das nächste Wort der Zeile berührt werden.
            x_rand = min(0.55, max(0.22, rect.height * 0.035))
            y_rand = min(1.0, max(0.55, rect.height * 0.07))
            loeschrect = fitz.Rect(
                max(0, rect.x0 - x_rand),
                max(0, rect.y0 - y_rand),
                min(seite.rect.width, rect.x1 + x_rand),
                min(seite.rect.height, rect.y1 + y_rand),
            )
            hintergrund = _engine._hintergrundfarbe(seite, loeschrect)
            seite.add_redact_annot(loeschrect, fill=hintergrund, cross_out=False)
            hat_loeschung = True
        operationen.append((edit, rect))

    if hat_loeschung:
        try:
            seite.apply_redactions(images=0, graphics=0, text=0)
        except TypeError:
            seite.apply_redactions(images=0)

    for edit, _rect in operationen:
        _engine._ersatz_einfuegen(seite, edit)
    for edit in checkbox_edits:
        _interaction._checkbox_einzeichnen(seite, edit)


_engine._seite_bearbeiten = seite_mit_praezisen_teilbereichen_bearbeiten


__all__ = ["seite_mit_praezisen_teilbereichen_bearbeiten"]
