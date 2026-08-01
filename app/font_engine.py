from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import live_document_engine as _engine
from . import live_workspace as _workspace
from . import partial_line_editing as _partial
from . import workspace_interaction_v2 as _interaction
from .database import datenbank_sitzung
from .main import app, muss_angemeldet_sein
from .models import Nutzungsereignis


_URSPRUNG_PDF_INDEX = _engine.pdf_index
_URSPRUNG_ANKER_NACH_ID = _engine.anker_nach_id
_URSPRUNG_ZIEL_AUFLOESEN = _engine.ziel_aufloesen
_URSPRUNG_ANKER_AUF_SEITE = _workspace._anker_auf_seite
_URSPRUNG_EDIT_AUS_ANKER = _engine.edit_aus_anker
_URSPRUNG_EDIT_SPEICHERN = _interaction.edit_speichern
_URSPRUNG_FREIE_POSITION = _interaction._edit_aus_freier_position


_BASE14 = {
    "helvetica": {"normal": "helv", "bold": "hebo", "italic": "heit", "bolditalic": "hebi"},
    "times": {"normal": "tiro", "bold": "tibo", "italic": "tiit", "bolditalic": "tibi"},
    "courier": {"normal": "cour", "bold": "cobo", "italic": "coit", "bolditalic": "cobi"},
}


class AuswahlSchriftEingabe(BaseModel):
    anker_id: str | None = None
    edit_id: str | None = None
    font_key: str = "auto"
    font_size: float | None = Field(default=None, ge=5.0, le=72.0)


class DokumentSchriftEingabe(BaseModel):
    font_key: str = "auto"
    stile_erhalten: bool = True


def _name_norm(text: Any) -> str:
    wert = str(text or "").strip().lstrip("/")
    wert = re.sub(r"^[A-Z]{6}\+", "", wert)
    return re.sub(r"[^a-z0-9]+", "", wert.lower())


def _anzeigename(text: Any) -> str:
    wert = str(text or "").strip().lstrip("/")
    return re.sub(r"^[A-Z]{6}\+", "", wert) or "Unbekannte Schrift"


def _stilmerkmale(fontname: Any, flags: Any = 0) -> dict[str, bool]:
    name = str(fontname or "").lower()
    try:
        flagzahl = int(flags or 0)
    except (TypeError, ValueError):
        flagzahl = 0
    return {
        "font_bold": bool(flagzahl & 16) or any(token in name for token in ("bold", "black", "heavy", "semibold", "demi")),
        "font_italic": bool(flagzahl & 2) or any(token in name for token in ("italic", "oblique", "kursiv")),
        "font_serif": bool(flagzahl & 4) or any(token in name for token in ("times", "serif", "georgia", "garamond", "minion")),
        "font_mono": bool(flagzahl & 8) or any(token in name for token in ("courier", "mono", "typewriter")),
    }


def _seitenfonts(seite: fitz.Page) -> list[dict[str, Any]]:
    ergebnis: list[dict[str, Any]] = []
    try:
        eintraege = list(seite.get_fonts(full=True) or [])
    except Exception:
        eintraege = []
    for eintrag in eintraege:
        if len(eintrag) < 5:
            continue
        try:
            xref = int(eintrag[0] or 0)
        except (TypeError, ValueError):
            xref = 0
        basis = str(eintrag[3] or "")
        referenz = str(eintrag[4] or "").lstrip("/")
        ergebnis.append(
            {
                "xref": xref,
                "basis": basis,
                "basis_norm": _name_norm(basis),
                "referenz": referenz,
                "typ": str(eintrag[2] or ""),
                "encoding": str(eintrag[5] or "") if len(eintrag) > 5 else "",
            }
        )
    return ergebnis


def _fontressource_finden(seite: fitz.Page, fontname: Any) -> dict[str, Any] | None:
    gesucht = _name_norm(fontname)
    if not gesucht:
        return None
    kandidaten = _seitenfonts(seite)
    exakt = [f for f in kandidaten if f["basis_norm"] == gesucht or _name_norm(f["referenz"]) == gesucht]
    if exakt:
        return exakt[0]
    enthalten = [f for f in kandidaten if gesucht in f["basis_norm"] or f["basis_norm"] in gesucht]
    enthalten.sort(key=lambda f: abs(len(f["basis_norm"]) - len(gesucht)))
    return enthalten[0] if enthalten else None


def _spans_mit_schrift(seite: fitz.Page) -> list[dict[str, Any]]:
    ressourcen = _seitenfonts(seite)
    spans: list[dict[str, Any]] = []
    for block in seite.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = str(span.get("text") or "")
                rect = fitz.Rect(span.get("bbox", (0, 0, 0, 0)))
                if not text.strip() or rect.is_empty:
                    continue
                fontname = str(span.get("font") or "")
                norm = _name_norm(fontname)
                treffer = next((f for f in ressourcen if f["basis_norm"] == norm), None)
                if not treffer:
                    treffer = next((f for f in ressourcen if norm and (norm in f["basis_norm"] or f["basis_norm"] in norm)), None)
                origin = span.get("origin") or (rect.x0, rect.y1 - 2)
                eintrag = {
                    "text": text,
                    "rect": rect,
                    "fontname": fontname,
                    "font_ref": str((treffer or {}).get("referenz") or ""),
                    "font_xref": int((treffer or {}).get("xref") or 0),
                    "font_flags": int(span.get("flags") or 0),
                    "schriftgroesse": float(span.get("size") or 10),
                    "farbe": int(span.get("color") or 0),
                    "origin": [float(origin[0]), float(origin[1])],
                }
                eintrag.update(_stilmerkmale(fontname, eintrag["font_flags"]))
                spans.append(eintrag)
    return spans


def _bestes_span(rect: fitz.Rect, spans: list[dict[str, Any]]) -> dict[str, Any] | None:
    bester = None
    score = -1.0
    for span in spans:
        schnitt = rect & span["rect"]
        flaeche = 0.0 if schnitt.is_empty else float(schnitt.get_area())
        if flaeche > score:
            score = flaeche
            bester = span
    return bester


def pdf_index_mit_schrift(dateipfad: Path, maximale_anker: int = 3000) -> dict[str, Any]:
    index = _URSPRUNG_PDF_INDEX(dateipfad, maximale_anker=maximale_anker)
    dokument = fitz.open(dateipfad)
    gefundene_fonts: dict[str, dict[str, Any]] = {}
    try:
        for seitenzahl, seite in enumerate(dokument, start=1):
            spans = _spans_mit_schrift(seite)
            seiteninfo = next((s for s in index.get("seiten", []) if int(s.get("seite") or 0) == seitenzahl), None)
            if not seiteninfo:
                continue
            for anker in seiteninfo.get("anker", []):
                rect = fitz.Rect(*(anker.get("bbox") or [0, 0, 0, 0]))
                span = _bestes_span(rect, spans)
                if not span:
                    continue
                for key in (
                    "fontname",
                    "font_ref",
                    "font_xref",
                    "font_flags",
                    "font_bold",
                    "font_italic",
                    "font_serif",
                    "font_mono",
                ):
                    anker[key] = span.get(key)
                if not anker.get("schriftgroesse"):
                    anker["schriftgroesse"] = span["schriftgroesse"]
            for font in _seitenfonts(seite):
                norm = font["basis_norm"]
                if not norm:
                    continue
                datensatz = gefundene_fonts.setdefault(
                    norm,
                    {"key": f"pdf:{norm}", "name": _anzeigename(font["basis"]), "seiten": []},
                )
                if seitenzahl not in datensatz["seiten"]:
                    datensatz["seiten"].append(seitenzahl)
    finally:
        dokument.close()
    index["fonts"] = sorted(gefundene_fonts.values(), key=lambda f: f["name"].lower())
    return index


def _ankerfont_erganzen(index: dict[str, Any], anker: dict[str, Any] | None, anker_id: str = ""):
    if not anker or anker.get("fontname"):
        return anker
    ids = [teil for teil in str(anker_id or anker.get("id") or "").split("|") if teil]
    alle = [a for seite in index.get("seiten", []) for a in seite.get("anker", [])]
    quelle = next((a for a in alle if a.get("id") in ids and a.get("fontname")), None)
    if not quelle:
        rect = fitz.Rect(*(anker.get("bbox") or [0, 0, 0, 0]))
        gleiche_seite = [a for a in alle if int(a.get("seite") or 0) == int(anker.get("seite") or 0) and a.get("fontname")]
        quelle = max(
            gleiche_seite,
            key=lambda a: (rect & fitz.Rect(*(a.get("bbox") or [0, 0, 0, 0]))).get_area(),
            default=None,
        )
    if quelle:
        for key in (
            "fontname",
            "font_ref",
            "font_xref",
            "font_flags",
            "font_bold",
            "font_italic",
            "font_serif",
            "font_mono",
        ):
            anker[key] = quelle.get(key)
    return anker


def anker_nach_id_mit_schrift(index: dict[str, Any], anker_id: str):
    return _ankerfont_erganzen(index, _URSPRUNG_ANKER_NACH_ID(index, anker_id), anker_id)


def ziel_aufloesen_mit_schrift(index: dict[str, Any], zustand: dict[str, Any], ziel: str, anker_id: str | None = None):
    return _ankerfont_erganzen(index, _URSPRUNG_ZIEL_AUFLOESEN(index, zustand, ziel, anker_id), anker_id or "")


def anker_auf_seite_mit_schrift(index: dict[str, Any], text: str, seite: int | None = None):
    return _ankerfont_erganzen(index, _URSPRUNG_ANKER_AUF_SEITE(index, text, seite), "")


def edit_aus_anker_mit_schrift(anker: dict[str, Any], wert: str, quelle: str = "chat", ziel: str = ""):
    edit = _URSPRUNG_EDIT_AUS_ANKER(anker, wert, quelle=quelle, ziel=ziel)
    for key in (
        "fontname",
        "font_ref",
        "font_xref",
        "font_flags",
        "font_bold",
        "font_italic",
        "font_serif",
        "font_mono",
    ):
        if anker.get(key) is not None:
            edit[key] = anker.get(key)
    edit.setdefault("font_key", "auto")
    return edit


def freie_position_mit_schrift(dateipfad: Path, index: dict[str, Any], seite: int, x: float, y: float, wert: str):
    edit = _URSPRUNG_FREIE_POSITION(dateipfad, index, seite, x, y, wert)
    nachbar = _interaction._naechster_textanker(index, seite, x, y) or {}
    for key in (
        "fontname",
        "font_ref",
        "font_xref",
        "font_flags",
        "font_bold",
        "font_italic",
        "font_serif",
        "font_mono",
    ):
        if nachbar.get(key) is not None:
            edit[key] = nachbar.get(key)
    edit.setdefault("font_key", "auto")
    return edit


def edit_speichern_mit_schrift(zustand: dict[str, Any] | None, edit: dict[str, Any]):
    daten = copy.deepcopy(zustand or {})
    edit = copy.deepcopy(edit)
    anker_id = str(edit.get("anker_id") or "")
    stil = dict((daten.get("auswahl_schriften") or {}).get(anker_id) or {})
    if stil:
        edit["font_key"] = str(stil.get("font_key") or "auto")
        if stil.get("font_size") is not None:
            edit["schriftgroesse"] = float(stil["font_size"])
            edit["font_size_user"] = True
    return _URSPRUNG_EDIT_SPEICHERN(daten, edit)


def _font_stil(edit: dict[str, Any]) -> str:
    bold = bool(edit.get("font_bold"))
    italic = bool(edit.get("font_italic"))
    if bold and italic:
        return "bolditalic"
    if bold:
        return "bold"
    if italic:
        return "italic"
    return "normal"


def _fallback_familie(edit: dict[str, Any]) -> str:
    if bool(edit.get("font_mono")):
        return "courier"
    if bool(edit.get("font_serif")):
        return "times"
    return "helvetica"


def _base14_name(familie: str, edit: dict[str, Any], stile_erhalten: bool = True) -> str:
    familie = familie if familie in _BASE14 else "helvetica"
    stil = _font_stil(edit) if stile_erhalten else "normal"
    return _BASE14[familie][stil]


def _font_auf_seite(seite: fitz.Page, edit: dict[str, Any], font_key: str | None = None, stile_erhalten: bool = True):
    key = str(font_key or edit.get("font_key") or "auto")
    if key.startswith("pdf:"):
        gesucht = key.split(":", 1)[1]
        treffer = _fontressource_finden(seite, gesucht)
        if treffer and treffer.get("referenz"):
            return f"/{treffer['referenz']}", int(treffer.get("xref") or 0)
        return _base14_name(_fallback_familie(edit), edit, stile_erhalten), 0
    if key in _BASE14:
        return _base14_name(key, edit, stile_erhalten), 0

    referenz = str(edit.get("font_ref") or "").lstrip("/")
    if referenz and any(f.get("referenz") == referenz for f in _seitenfonts(seite)):
        return f"/{referenz}", int(edit.get("font_xref") or 0)
    treffer = _fontressource_finden(seite, edit.get("fontname"))
    if treffer and treffer.get("referenz"):
        return f"/{treffer['referenz']}", int(treffer.get("xref") or 0)
    return _base14_name(_fallback_familie(edit), edit, True), 0


def _font_objekt(seite: fitz.Page, fontname: str, xref: int = 0):
    if xref > 0:
        try:
            extrahiert = seite.parent.extract_font(xref)
            puffer = extrahiert[-1] if extrahiert else b""
            if puffer:
                return fitz.Font(fontbuffer=puffer)
        except Exception:
            pass
    try:
        return fitz.Font(fontname=fontname.lstrip("/"))
    except Exception:
        return fitz.Font(fontname="helv")


def _font_hat_zeichen(font: fitz.Font, text: str) -> bool:
    try:
        return all(ch.isspace() or bool(font.has_glyph(ord(ch))) for ch in text)
    except Exception:
        return True


def _textbreite(font: fitz.Font, text: str, groesse: float) -> float:
    try:
        return float(font.text_length(text, fontsize=groesse))
    except Exception:
        return max(1.0, len(text) * groesse * 0.52)


def ersatz_einfuegen_mit_schrift(seite: fitz.Page, edit: dict[str, Any]) -> None:
    text = str(edit.get("neuer_text") or "")
    if not text:
        return
    rect = fitz.Rect(*(edit.get("bbox") or [0, 0, 0, 0]))
    write_x1 = max(rect.x1, min(float(edit.get("write_x1") or rect.x1), float(seite.rect.width) - 12))
    breite = max(rect.width, write_x1 - rect.x0)
    groesse = max(5.0, min(72.0, float(edit.get("schriftgroesse") or 10)))
    fontname, xref = _font_auf_seite(seite, edit)
    font = _font_objekt(seite, fontname, xref)
    if not _font_hat_zeichen(font, text):
        fallback = _base14_name(_fallback_familie(edit), edit, True)
        fontname, xref, font = fallback, 0, _font_objekt(seite, fallback, 0)
    textbreite = _textbreite(font, text, groesse)
    if textbreite > breite:
        groesse = max(5.0, groesse * (breite / max(1.0, textbreite)) * 0.97)
    farbe = _engine._farbe_aus_int(edit.get("farbe"))
    origin = edit.get("origin") or [rect.x0, rect.y1 - 1]
    punkt = fitz.Point(max(0.0, float(origin[0])), float(origin[1]))
    try:
        seite.insert_text(punkt, text[:1000], fontname=fontname, fontsize=groesse, color=farbe, overlay=True)
    except Exception:
        fallback = _base14_name(_fallback_familie(edit), edit, True)
        seite.insert_text(punkt, text[:1000], fontname=fallback, fontsize=groesse, color=farbe, overlay=True)


def _seite_komplett_umformatieren(seite: fitz.Page, einstellung: dict[str, Any]) -> None:
    font_key = str(einstellung.get("font_key") or "auto")
    if font_key == "auto":
        return
    stile_erhalten = bool(einstellung.get("stile_erhalten", True))
    spans = _spans_mit_schrift(seite)
    if not spans:
        return
    operationen: list[dict[str, Any]] = []
    for span in spans:
        rect = fitz.Rect(span["rect"])
        hintergrund = _engine._hintergrundfarbe(seite, rect)
        seite.add_redact_annot(rect, fill=hintergrund, cross_out=False)
        edit = {
            "neuer_text": span["text"],
            "bbox": [rect.x0, rect.y0, rect.x1, rect.y1],
            "origin": list(span["origin"]),
            "write_x1": rect.x1,
            "schriftgroesse": span["schriftgroesse"],
            "farbe": span["farbe"],
            "fontname": span["fontname"],
            "font_ref": span["font_ref"],
            "font_xref": span["font_xref"],
            "font_flags": span["font_flags"],
            "font_bold": span["font_bold"],
            "font_italic": span["font_italic"],
            "font_serif": span["font_serif"],
            "font_mono": span["font_mono"],
            "font_key": font_key,
        }
        if not stile_erhalten:
            edit["font_bold"] = False
            edit["font_italic"] = False
        operationen.append(edit)
    try:
        seite.apply_redactions(images=0, graphics=0, text=0)
    except TypeError:
        seite.apply_redactions(images=0)
    for edit in operationen:
        ersatz_einfuegen_mit_schrift(seite, edit)


def bearbeitetes_dokument_mit_schrift(dateipfad: Path, zustand: dict[str, Any] | None) -> fitz.Document:
    dokument = fitz.open(dateipfad)
    daten = copy.deepcopy(zustand or {})
    dokument_font = dict(daten.get("dokument_font") or {})
    if dokument_font.get("font_key") and dokument_font.get("font_key") != "auto":
        for seite in dokument:
            _seite_komplett_umformatieren(seite, dokument_font)

    edits = list(daten.get("edits") or [])
    nach_seite: dict[int, list[dict[str, Any]]] = {}
    for edit in edits:
        edit = copy.deepcopy(edit)
        if dokument_font.get("font_key") and str(edit.get("font_key") or "auto") == "auto":
            edit["font_key"] = dokument_font["font_key"]
            if not bool(dokument_font.get("stile_erhalten", True)):
                edit["font_bold"] = False
                edit["font_italic"] = False
        nach_seite.setdefault(max(1, int(edit.get("seite") or 1)), []).append(edit)
    for seitenzahl, seiten_edits in nach_seite.items():
        if 1 <= seitenzahl <= len(dokument):
            _engine._seite_bearbeiten(dokument[seitenzahl - 1], seiten_edits)
    return dokument


def _font_key_pruefen(dateipfad: Path, font_key: str) -> str:
    key = str(font_key or "auto").strip().lower()
    if key == "auto" or key in _BASE14:
        return key
    if key.startswith("pdf:"):
        erlaubt = {f["key"] for f in pdf_index_mit_schrift(dateipfad).get("fonts", [])}
        if key in erlaubt:
            return key
    raise HTTPException(status_code=422, detail="Diese Schrift ist im Dokument nicht verfügbar.")


def _font_liste(dateipfad: Path) -> list[dict[str, Any]]:
    erkannt = pdf_index_mit_schrift(dateipfad).get("fonts", [])
    return [
        {"key": "auto", "name": "Wie im Original", "gruppe": "automatisch"},
        *[{"key": f["key"], "name": f["name"], "gruppe": "im Dokument", "seiten": f["seiten"]} for f in erkannt],
        {"key": "helvetica", "name": "Helvetica", "gruppe": "Standardschriften"},
        {"key": "times", "name": "Times", "gruppe": "Standardschriften"},
        {"key": "courier", "name": "Courier", "gruppe": "Standardschriften"},
    ]


@app.get("/api/workspace/{entwurf_id}/fonts")
def live_schriften(entwurf_id: int, request: Request, db=Depends(datenbank_sitzung)):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = _workspace._entwurf_fuer_mitglied(db, mitglied, entwurf_id)
    return {
        "fonts": _font_liste(Path(eintrag.speicherort)),
        "dokument_font": dict((eintrag.zustand or {}).get("dokument_font") or {"font_key": "auto", "stile_erhalten": True}),
    }


@app.post("/api/workspace/{entwurf_id}/selection-font")
def live_auswahl_schrift(
    entwurf_id: int,
    eingabe: AuswahlSchriftEingabe,
    request: Request,
    db=Depends(datenbank_sitzung),
):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = _workspace._entwurf_fuer_mitglied(db, mitglied, entwurf_id)
    if not eingabe.anker_id and not eingabe.edit_id:
        raise HTTPException(status_code=422, detail="Bitte wählen Sie zuerst einen Text im Dokument aus.")
    key = _font_key_pruefen(Path(eintrag.speicherort), eingabe.font_key)
    zustand = copy.deepcopy(eintrag.zustand or {})
    seiten: set[int] = set()

    if eingabe.anker_id:
        auswahl = dict(zustand.get("auswahl_schriften") or {})
        auswahl[eingabe.anker_id] = {"font_key": key, "font_size": eingabe.font_size}
        zustand["auswahl_schriften"] = auswahl

    edits = list(zustand.get("edits") or [])
    for edit in edits:
        passt = (eingabe.edit_id and str(edit.get("id") or "") == eingabe.edit_id) or (
            eingabe.anker_id and str(edit.get("anker_id") or "") == eingabe.anker_id
        )
        if not passt:
            continue
        edit["font_key"] = key
        if eingabe.font_size is None:
            edit.pop("font_size_user", None)
        else:
            edit["schriftgroesse"] = float(eingabe.font_size)
            edit["font_size_user"] = True
        seiten.add(int(edit.get("seite") or 1))
    zustand["edits"] = edits
    zustand["revision"] = int(zustand.get("revision") or 0) + 1
    eintrag.zustand = zustand
    eintrag.aktualisiert_am = datetime.now(timezone.utc)
    db.add(Nutzungsereignis(organisation_id=mitglied.organisation_id, art="live_schrift", menge=1, kosten_euro=0, einzelheiten={"umfang": "auswahl", "font_key": key}))
    db.commit()
    return {"erfolg": True, "revision": zustand["revision"], "seiten": sorted(seiten), "font_key": key}


@app.post("/api/workspace/{entwurf_id}/document-font")
def live_dokument_schrift(
    entwurf_id: int,
    eingabe: DokumentSchriftEingabe,
    request: Request,
    db=Depends(datenbank_sitzung),
):
    mitglied = muss_angemeldet_sein(request, db)
    eintrag = _workspace._entwurf_fuer_mitglied(db, mitglied, entwurf_id)
    key = _font_key_pruefen(Path(eintrag.speicherort), eingabe.font_key)
    zustand = copy.deepcopy(eintrag.zustand or {})
    zustand["dokument_font"] = {"font_key": key, "stile_erhalten": bool(eingabe.stile_erhalten)}
    zustand["revision"] = int(zustand.get("revision") or 0) + 1
    eintrag.zustand = zustand
    eintrag.aktualisiert_am = datetime.now(timezone.utc)
    db.add(Nutzungsereignis(organisation_id=mitglied.organisation_id, art="live_schrift", menge=1, kosten_euro=0, einzelheiten={"umfang": "dokument", "font_key": key}))
    db.commit()
    return {
        "erfolg": True,
        "revision": zustand["revision"],
        "seiten": list(range(1, int(eintrag.seiten or 1) + 1)),
        "font_key": key,
    }


# Der Index enthält ab jetzt die tatsächliche PDF-Schriftressource. Alle direkten
# und semantischen Bearbeitungswege nutzen dadurch dieselbe Schriftinformation.
_engine.pdf_index = pdf_index_mit_schrift
_engine.anker_nach_id = anker_nach_id_mit_schrift
_engine.ziel_aufloesen = ziel_aufloesen_mit_schrift
_engine.edit_aus_anker = edit_aus_anker_mit_schrift
_engine.edit_speichern = edit_speichern_mit_schrift
_engine._ersatz_einfuegen = ersatz_einfuegen_mit_schrift
_engine.bearbeitetes_dokument = bearbeitetes_dokument_mit_schrift

_workspace.pdf_index = pdf_index_mit_schrift
_workspace.anker_nach_id = anker_nach_id_mit_schrift
_workspace.ziel_aufloesen = ziel_aufloesen_mit_schrift
_workspace._anker_auf_seite = anker_auf_seite_mit_schrift
_workspace.edit_aus_anker = edit_aus_anker_mit_schrift
_workspace.edit_speichern = edit_speichern_mit_schrift

_interaction.pdf_index = pdf_index_mit_schrift
_interaction.anker_nach_id = anker_nach_id_mit_schrift
_interaction.ziel_aufloesen = ziel_aufloesen_mit_schrift
_interaction._anker_auf_seite = anker_auf_seite_mit_schrift
_interaction.edit_aus_anker = edit_aus_anker_mit_schrift
_interaction.edit_speichern = edit_speichern_mit_schrift
_interaction._edit_aus_freier_position = freie_position_mit_schrift


__all__ = [
    "pdf_index_mit_schrift",
    "ersatz_einfuegen_mit_schrift",
    "bearbeitetes_dokument_mit_schrift",
]
