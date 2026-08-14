from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, select, update

from .auth import passwort_pruefen
from .database import Sitzung, datenbank_sitzung
from .main import app, aktuelles_mitglied, cfg, grundkontext, muss_angemeldet_sein, vorlagen
from .models import (
    Arbeitsausgabe,
    Arbeitsdokument,
    Dokumentausgabe,
    Dokumentvorlage,
    Kontorolle,
    Mitglied,
    Nutzungsereignis,
    Organisation,
    Tarif,
)

SUPPORT_EMAIL = "app@aplus-solution.de"


def _alte_tarifwechselroute(route) -> bool:
    return (
        getattr(route, "path", None) == "/abrechnung/tarif-wechseln"
        and "POST" in (getattr(route, "methods", set()) or set())
    )


# Die Store-Version darf keinen versteckten oder nur per URL erreichbaren Upgrade-Pfad behalten.
# Die ältere Route aus main.py wird deshalb vollständig aus dem Router entfernt.
app.router.routes[:] = [route for route in app.router.routes if not _alte_tarifwechselroute(route)]


@app.post("/abrechnung/tarif-wechseln")
def enterprise_tarifwechsel_gesperrt():
    raise HTTPException(
        status_code=403,
        detail="Vertrags- und Kontingentänderungen werden ausschließlich außerhalb der App direkt mit A+ Solution verwaltet.",
    )


@app.on_event("startup")
def enterprise_tarifbeschreibungen_sicherstellen() -> None:
    """Entfernt auch in bestehenden Datenbanken jede Consumer-Positionierung der Tarife."""
    beschreibungen = {
        "Start": "Für kleine Unternehmen und Organisationsteams mit wiederkehrenden Geschäftsdokumenten.",
        "Unternehmen": "Für wachsende Unternehmen mit mehreren Mitarbeitenden und regelmäßigem Dokumentenaufkommen.",
        "Professionell": "Für Organisationen mit hohem Volumen, individuellen Kontingenten und erweiterten Verwaltungsanforderungen.",
    }
    with Sitzung() as db:
        geaendert = False
        for name, beschreibung in beschreibungen.items():
            tarif = db.scalar(select(Tarif).where(Tarif.name == name))
            if tarif and tarif.beschreibung != beschreibung:
                tarif.beschreibung = beschreibung
                geaendert = True
        if geaendert:
            db.commit()


def _public_context(request: Request, db, bereich: str) -> dict:
    context = grundkontext(request, db, bereich)
    domain = str(cfg.domain or "").strip().strip("/")
    if domain.startswith("http://") or domain.startswith("https://"):
        basis_url = domain
    elif domain and domain not in {"localhost", "127.0.0.1"}:
        basis_url = f"https://{domain}"
    else:
        basis_url = str(request.base_url).rstrip("/")
    context.update({"support_email": SUPPORT_EMAIL, "basis_url": basis_url})
    return context


def _pfade_der_organisation(db, organisation_id: int) -> set[Path]:
    pfade: set[Path] = set()
    for modell in (Dokumentvorlage, Dokumentausgabe, Arbeitsdokument, Arbeitsausgabe):
        for wert in db.scalars(select(modell.speicherort).where(modell.organisation_id == organisation_id)).all():
            if wert:
                try:
                    pfade.add(Path(str(wert)))
                except Exception:
                    pass
    return pfade


def _dateien_entfernen(pfade: set[Path]) -> None:
    for pfad in pfade:
        try:
            pfad.unlink(missing_ok=True)
        except Exception:
            # Ein fehlgeschlagener Dateizugriff darf die DB-Löschung nicht halb fertig lassen.
            pass


def _mitglied_loeschen(db, mitglied: Mitglied) -> str:
    organisation = db.get(Organisation, mitglied.organisation_id)
    if not organisation:
        raise HTTPException(status_code=404, detail="Das Unternehmenskonto wurde nicht gefunden.")

    mitglieder = db.scalars(
        select(Mitglied)
        .where(Mitglied.organisation_id == organisation.id, Mitglied.id != mitglied.id)
        .order_by(Mitglied.erstellt_am.asc(), Mitglied.id.asc())
    ).all()

    ist_inhaber = mitglied.rolle == Kontorolle.INHABER
    if ist_inhaber and not mitglieder:
        pfade = _pfade_der_organisation(db, organisation.id)
        # Direkter Arbeitsfluss ist nicht als ORM-Beziehung an Organisation gebunden.
        db.execute(delete(Arbeitsausgabe).where(Arbeitsausgabe.organisation_id == organisation.id))
        db.execute(delete(Arbeitsdokument).where(Arbeitsdokument.organisation_id == organisation.id))
        db.execute(delete(Nutzungsereignis).where(Nutzungsereignis.organisation_id == organisation.id))
        db.delete(organisation)
        db.commit()
        _dateien_entfernen(pfade)
        return "organisation"

    if ist_inhaber and mitglieder:
        nachfolger = next((m for m in mitglieder if m.aktiv), mitglieder[0])
        nachfolger.rolle = Kontorolle.INHABER

    # Historische Firmendokumente gehören dem Unternehmen, nicht dem persönlichen Konto.
    # Personenbezug des gelöschten Mitglieds wird daraus entfernt.
    db.execute(update(Dokumentvorlage).where(Dokumentvorlage.erstellt_von_id == mitglied.id).values(erstellt_von_id=None))
    db.execute(update(Dokumentausgabe).where(Dokumentausgabe.erstellt_von_id == mitglied.id).values(erstellt_von_id=None))
    db.execute(update(Arbeitsdokument).where(Arbeitsdokument.erstellt_von_id == mitglied.id).values(erstellt_von_id=None))
    db.execute(update(Arbeitsausgabe).where(Arbeitsausgabe.erstellt_von_id == mitglied.id).values(erstellt_von_id=None))
    db.delete(mitglied)
    db.commit()
    return "mitglied"


@app.get("/datenschutz-app", response_class=HTMLResponse)
def app_datenschutz(request: Request, db=Depends(datenbank_sitzung)):
    return vorlagen.TemplateResponse("store_datenschutz.html", _public_context(request, db, "datenschutz"))


@app.get("/nutzungsbedingungen", response_class=HTMLResponse)
def app_nutzungsbedingungen(request: Request, db=Depends(datenbank_sitzung)):
    return vorlagen.TemplateResponse("store_nutzungsbedingungen.html", _public_context(request, db, "bedingungen"))


@app.get("/support", response_class=HTMLResponse)
def app_support(request: Request, db=Depends(datenbank_sitzung)):
    return vorlagen.TemplateResponse("store_support.html", _public_context(request, db, "support"))


@app.get("/konto-loeschen", response_class=HTMLResponse)
def konto_loeschen_web(request: Request, db=Depends(datenbank_sitzung)):
    context = _public_context(request, db, "konto-loeschen")
    context["angemeldet"] = bool(aktuelles_mitglied(request, db))
    return vorlagen.TemplateResponse("store_konto_loeschen.html", context)


@app.post("/konto-loeschen/anfragen", response_class=HTMLResponse)
def konto_loeschen_anfragen(
    request: Request,
    email: str = Form(...),
    bestaetigung: str | None = Form(default=None),
    db=Depends(datenbank_sitzung),
):
    mail = email.strip().lower()[:255]
    if "@" not in mail or not bestaetigung:
        context = _public_context(request, db, "konto-loeschen")
        context.update({"fehler": "Bitte geben Sie eine gültige E-Mail-Adresse ein und bestätigen Sie die Löschanfrage.", "email": mail})
        return vorlagen.TemplateResponse("store_konto_loeschen.html", context, status_code=422)

    konto = db.scalar(select(Mitglied).where(Mitglied.email == mail))
    db.add(
        Nutzungsereignis(
            organisation_id=konto.organisation_id if konto else None,
            art="konto_loeschanfrage_extern",
            menge=1,
            kosten_euro=0,
            einzelheiten={
                "email": mail,
                "status": "offen",
                "quelle": "oeffentliche-loeschseite",
                "angefragt_am": datetime.now(timezone.utc).isoformat(),
            },
        )
    )
    db.commit()
    context = _public_context(request, db, "konto-loeschen")
    context["erfolg"] = True
    return vorlagen.TemplateResponse("store_konto_loeschen.html", context)


@app.post("/einstellungen/konto-loeschen")
def konto_im_app_loeschen(
    request: Request,
    passwort: str = Form(...),
    bestaetigung: str | None = Form(default=None),
    db=Depends(datenbank_sitzung),
):
    mitglied = muss_angemeldet_sein(request, db)
    if mitglied.ist_superadmin:
        raise HTTPException(status_code=403, detail="Das A+ Verwaltungskonto kann hier nicht gelöscht werden.")
    if not bestaetigung:
        request.session["hinweis"] = {"text": "Bitte bestätigen Sie die endgültige Kontolöschung.", "art": "fehler"}
        return RedirectResponse("/einstellungen#konto-loeschen", status_code=303)
    if not passwort_pruefen(passwort, mitglied.passwort_hash):
        request.session["hinweis"] = {"text": "Das Passwort ist nicht korrekt.", "art": "fehler"}
        return RedirectResponse("/einstellungen#konto-loeschen", status_code=303)

    typ = _mitglied_loeschen(db, mitglied)
    request.session.clear()
    return RedirectResponse(f"/konto-geloescht?typ={typ}", status_code=303)


@app.get("/konto-geloescht", response_class=HTMLResponse)
def konto_geloescht(request: Request, db=Depends(datenbank_sitzung)):
    context = _public_context(request, db, "konto-geloescht")
    context["typ"] = request.query_params.get("typ", "mitglied")
    return vorlagen.TemplateResponse("store_konto_geloescht.html", context)


__all__ = ["SUPPORT_EMAIL"]
