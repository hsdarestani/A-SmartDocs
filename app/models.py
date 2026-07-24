from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Basis


def jetzt() -> datetime:
    return datetime.now(timezone.utc)


class Kontorolle(str, Enum):
    INHABER = "inhaber"
    VERWALTUNG = "verwaltung"
    BEARBEITUNG = "bearbeitung"
    NUTZUNG = "nutzung"
    LESEN = "lesen"


class Organisation(Basis):
    __tablename__ = "organisationen"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    branche: Mapped[str] = mapped_column(String(120), default="Dienstleistung")
    strasse: Mapped[str] = mapped_column(String(180), default="")
    plz: Mapped[str] = mapped_column(String(20), default="")
    ort: Mapped[str] = mapped_column(String(100), default="")
    telefon: Mapped[str] = mapped_column(String(50), default="")
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    mitglieder: Mapped[list[Mitglied]] = relationship(back_populates="organisation", cascade="all, delete-orphan")
    abonnement: Mapped[Abonnement | None] = relationship(back_populates="organisation", uselist=False, cascade="all, delete-orphan")
    vorlagen: Mapped[list[Dokumentvorlage]] = relationship(back_populates="organisation", cascade="all, delete-orphan")
    dokumente: Mapped[list[Dokumentausgabe]] = relationship(back_populates="organisation", cascade="all, delete-orphan")
    einladungen: Mapped[list[Einladung]] = relationship(back_populates="organisation", cascade="all, delete-orphan")
    rechnungen: Mapped[list[Rechnung]] = relationship(back_populates="organisation", cascade="all, delete-orphan")


class Mitglied(Basis):
    __tablename__ = "mitglieder"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisationen.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    passwort_hash: Mapped[str] = mapped_column(String(255), default="")
    rolle: Mapped[Kontorolle] = mapped_column(SqlEnum(Kontorolle), default=Kontorolle.NUTZUNG)
    ist_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    email_bestaetigt: Mapped[bool] = mapped_column(Boolean, default=True)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    letzter_zugriff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    organisation: Mapped[Organisation] = relationship(back_populates="mitglieder")
    dokumente: Mapped[list[Dokumentausgabe]] = relationship(back_populates="erstellt_von")


class Tarif(Basis):
    __tablename__ = "tarife"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    beschreibung: Mapped[str] = mapped_column(Text, default="")
    monatspreis: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    jahrespreis: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    dokumente_monat: Mapped[int] = mapped_column(Integer)
    vorlagen: Mapped[int] = mapped_column(Integer)
    unterkonten: Mapped[int] = mapped_column(Integer)
    speicher_mb: Mapped[int] = mapped_column(Integer)
    merkmale: Mapped[list] = mapped_column(JSON, default=list)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)

    abonnements: Mapped[list[Abonnement]] = relationship(back_populates="tarif")


class Abonnement(Basis):
    __tablename__ = "abonnements"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisationen.id"), unique=True)
    tarif_id: Mapped[int] = mapped_column(ForeignKey("tarife.id"))
    status: Mapped[str] = mapped_column(String(40), default="wartet_auf_zahlung")
    abrechnungszeitraum: Mapped[str] = mapped_column(String(20), default="monatlich")
    angefragter_tarif_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    angefragter_zeitraum: Mapped[str | None] = mapped_column(String(20), nullable=True)
    zahlungshinweis: Mapped[str] = mapped_column(String(255), default="")
    aktiviert_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    individueller_preis: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    dokumente_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vorlagen_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unterkonten_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speicher_override_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    testphase_bis: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gekuendigt_zum: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verlaengert_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    organisation: Mapped[Organisation] = relationship(back_populates="abonnement")
    tarif: Mapped[Tarif] = relationship(back_populates="abonnements")

    @property
    def preis(self) -> Decimal:
        if self.individueller_preis is not None:
            return self.individueller_preis
        if self.abrechnungszeitraum == "jaehrlich" and self.tarif.jahrespreis is not None:
            return self.tarif.jahrespreis
        return self.tarif.monatspreis

    @property
    def dokument_limit(self) -> int:
        return self.dokumente_override if self.dokumente_override is not None else self.tarif.dokumente_monat

    @property
    def vorlagen_limit(self) -> int:
        return self.vorlagen_override if self.vorlagen_override is not None else self.tarif.vorlagen

    @property
    def unterkonten_limit(self) -> int:
        return self.unterkonten_override if self.unterkonten_override is not None else self.tarif.unterkonten

    @property
    def speicher_limit_mb(self) -> int:
        return self.speicher_override_mb if self.speicher_override_mb is not None else self.tarif.speicher_mb


class Dokumentvorlage(Basis):
    __tablename__ = "dokumentvorlagen"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int | None] = mapped_column(ForeignKey("organisationen.id"), nullable=True, index=True)
    erstellt_von_id: Mapped[int | None] = mapped_column(ForeignKey("mitglieder.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(180))
    dateiname: Mapped[str] = mapped_column(String(255))
    speicherort: Mapped[str] = mapped_column(String(500))
    inhaltstyp: Mapped[str] = mapped_column(String(100), default="application/pdf")
    originalgroesse: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="wird analysiert")
    seiten: Mapped[int] = mapped_column(Integer, default=1)
    erkannte_felder: Mapped[int] = mapped_column(Integer, default=0)
    schema: Mapped[dict] = mapped_column(JSON, default=dict)
    zusammenfassung: Mapped[str] = mapped_column(Text, default="")
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
    aktualisiert_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    organisation: Mapped[Organisation | None] = relationship(back_populates="vorlagen")
    dialoge: Mapped[list[Vorlagendialog]] = relationship(back_populates="vorlage", cascade="all, delete-orphan")
    dokumente: Mapped[list[Dokumentausgabe]] = relationship(back_populates="vorlage", cascade="all, delete-orphan")


class Vorlagendialog(Basis):
    __tablename__ = "vorlagendialoge"

    id: Mapped[int] = mapped_column(primary_key=True)
    vorlage_id: Mapped[int] = mapped_column(ForeignKey("dokumentvorlagen.id", ondelete="CASCADE"), index=True)
    rolle: Mapped[str] = mapped_column(String(20))
    nachricht: Mapped[str] = mapped_column(Text)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    vorlage: Mapped[Dokumentvorlage] = relationship(back_populates="dialoge")


class Dokumentausgabe(Basis):
    __tablename__ = "dokumentausgaben"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisationen.id", ondelete="CASCADE"), index=True)
    vorlage_id: Mapped[int] = mapped_column(ForeignKey("dokumentvorlagen.id", ondelete="CASCADE"), index=True)
    erstellt_von_id: Mapped[int | None] = mapped_column(ForeignKey("mitglieder.id"), nullable=True)
    titel: Mapped[str] = mapped_column(String(200))
    dateiname: Mapped[str] = mapped_column(String(255))
    speicherort: Mapped[str] = mapped_column(String(500))
    eingaben: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="fertig")
    seiten: Mapped[int] = mapped_column(Integer, default=1)
    dateigroesse: Mapped[int] = mapped_column(Integer, default=0)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    organisation: Mapped[Organisation] = relationship(back_populates="dokumente")
    vorlage: Mapped[Dokumentvorlage] = relationship(back_populates="dokumente")
    erstellt_von: Mapped[Mitglied | None] = relationship(back_populates="dokumente")


class Einladung(Basis):
    __tablename__ = "einladungen"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisationen.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    rolle: Mapped[Kontorolle] = mapped_column(SqlEnum(Kontorolle), default=Kontorolle.NUTZUNG)
    token: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    angenommen: Mapped[bool] = mapped_column(Boolean, default=False)
    laeuft_ab_am: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    organisation: Mapped[Organisation] = relationship(back_populates="einladungen")


class Rechnung(Basis):
    __tablename__ = "rechnungen"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisationen.id", ondelete="CASCADE"), index=True)
    nummer: Mapped[str] = mapped_column(String(80), unique=True)
    betrag: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(40), default="bezahlt")
    abrechnungszeitraum: Mapped[str] = mapped_column(String(120), default="")
    faellig_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    organisation: Mapped[Organisation] = relationship(back_populates="rechnungen")


class Nutzungsereignis(Basis):
    __tablename__ = "nutzungsereignisse"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int | None] = mapped_column(ForeignKey("organisationen.id"), nullable=True, index=True)
    art: Mapped[str] = mapped_column(String(80))
    menge: Mapped[int] = mapped_column(Integer, default=1)
    kosten_euro: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    einzelheiten: Mapped[dict] = mapped_column(JSON, default=dict)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
