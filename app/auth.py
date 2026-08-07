from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Abonnement, Kontorolle, Mitglied


@dataclass(slots=True)
class Anmeldung:
    mitglied: Mitglied


def passwort_hashen(passwort: str) -> str:
    if len(passwort) < 8:
        raise ValueError("Das Passwort muss mindestens 8 Zeichen lang sein.")
    salz = os.urandom(16)
    schluessel = hashlib.scrypt(passwort.encode("utf-8"), salt=salz, n=2**14, r=8, p=1, dklen=64)
    return "scrypt$" + base64.urlsafe_b64encode(salz).decode() + "$" + base64.urlsafe_b64encode(schluessel).decode()


def passwort_pruefen(passwort: str, gespeichert: str | None) -> bool:
    if not gespeichert or not gespeichert.startswith("scrypt$"):
        return False
    try:
        _, salz_b64, schluessel_b64 = gespeichert.split("$", 2)
        salz = base64.urlsafe_b64decode(salz_b64.encode())
        erwartet = base64.urlsafe_b64decode(schluessel_b64.encode())
        ermittelt = hashlib.scrypt(passwort.encode("utf-8"), salt=salz, n=2**14, r=8, p=1, dklen=len(erwartet))
        return hmac.compare_digest(ermittelt, erwartet)
    except (ValueError, TypeError):
        return False


def token_erzeugen(laenge: int = 32) -> str:
    return secrets.token_urlsafe(laenge)


def _schreibzugriff_erlaubt(request: Request, mitglied: Mitglied) -> bool:
    """Zentrale Rollenregel für alle zustandsverändernden Produktaufrufe."""
    methode = request.method.upper()
    pfad = request.url.path.rstrip("/") or "/"

    if methode in {"GET", "HEAD", "OPTIONS"} or pfad == "/abmelden":
        return True
    if mitglied.ist_superadmin:
        return True

    # Store-Richtlinien verlangen, dass jeder Nutzer sein eigenes Konto löschen
    # kann. Die Aktion löscht ausschließlich das aktuell angemeldete Mitglied und
    # darf daher nicht von einer Verwaltungsrolle abhängen.
    if pfad == "/einstellungen/konto-loeschen":
        return True

    rolle = mitglied.rolle
    if rolle == Kontorolle.LESEN:
        return False

    verwaltungsbereiche = ("/team", "/einstellungen", "/abrechnung")
    if pfad.startswith(verwaltungsbereiche):
        return rolle in {Kontorolle.INHABER, Kontorolle.VERWALTUNG}

    vorlagenverwaltung = (
        pfad == "/api/vorlagen/analysieren"
        or pfad == "/api/vorlagen/korrigieren"
        or (pfad.startswith("/api/vorlagen/") and (pfad.endswith("/schema") or pfad.endswith("/bestaetigen")))
    )
    if vorlagenverwaltung:
        return rolle in {Kontorolle.INHABER, Kontorolle.VERWALTUNG, Kontorolle.BEARBEITUNG}

    if re.fullmatch(r"/vorlagen/\d+/verwenden", pfad):
        return rolle in {
            Kontorolle.INHABER,
            Kontorolle.VERWALTUNG,
            Kontorolle.BEARBEITUNG,
            Kontorolle.NUTZUNG,
        }

    if re.fullmatch(r"/dokumente/\d+/loeschen", pfad):
        return rolle in {Kontorolle.INHABER, Kontorolle.VERWALTUNG, Kontorolle.BEARBEITUNG}

    return rolle in {Kontorolle.INHABER, Kontorolle.VERWALTUNG, Kontorolle.BEARBEITUNG}


def mitglied_aus_sitzung(request: Request, db: Session) -> Mitglied | None:
    mitglied_id = request.session.get("mitglied_id")
    if not mitglied_id:
        return None
    mitglied = db.get(Mitglied, int(mitglied_id))
    if not mitglied or not mitglied.aktiv or not mitglied.organisation.aktiv:
        request.session.clear()
        return None

    abonnement = db.scalar(select(Abonnement).where(Abonnement.organisation_id == mitglied.organisation_id))
    erlaubte_status = {"aktiv", "testphase", "intern"}
    if not mitglied.ist_superadmin and (not abonnement or abonnement.status not in erlaubte_status):
        request.session.clear()
        return None

    if not _schreibzugriff_erlaubt(request, mitglied):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Für diese Aktion fehlt Ihrer Rolle die Berechtigung.")
    return mitglied


def anmeldung_erforderlich(request: Request, db: Session) -> Mitglied:
    mitglied = mitglied_aus_sitzung(request, db)
    if not mitglied:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bitte melden Sie sich zuerst an.")
    return mitglied


def verwaltung_erforderlich(request: Request, db: Session) -> Mitglied:
    mitglied = anmeldung_erforderlich(request, db)
    if not mitglied.ist_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Für diesen Bereich fehlt die Berechtigung.")
    return mitglied
