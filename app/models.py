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
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    mitglieder: Mapped[list[Mitglied]] = relationship(back_populates="organisation", cascade="all, delete-orphan")
    abonnement: Mapped[Abonnement | None] = relationship(back_populates="organisation", uselist=False)
    vorlagen: Mapped[list[Dokumentvorlage]] = relationship(back_populates="organisation")


class Mitglied(Basis):
    __tablename__ = "mitglieder"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisationen.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    rolle: Mapped[Kontorolle] = mapped_column(SqlEnum(Kontorolle), default=Kontorolle.NUTZUNG)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    letzter_zugriff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organisation: Mapped[Organisation] = relationship(back_populates="mitglieder")


class Tarif(Basis):
    __tablename__ = "tarife"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    monatspreis: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    dokumente_monat: Mapped[int] = mapped_column(Integer)
    vorlagen: Mapped[int] = mapped_column(Integer)
    unterkonten: Mapped[int] = mapped_column(Integer)
    speicher_mb: Mapped[int] = mapped_column(Integer)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)

    abonnements: Mapped[list[Abonnement]] = relationship(back_populates="tarif")


class Abonnement(Basis):
    __tablename__ = "abonnements"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisationen.id"), unique=True)
    tarif_id: Mapped[int] = mapped_column(ForeignKey("tarife.id"))
    status: Mapped[str] = mapped_column(String(40), default="aktiv")
    individueller_preis: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    dokumente_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vorlagen_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unterkonten_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speicher_override_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verlaengert_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    organisation: Mapped[Organisation] = relationship(back_populates="abonnement")
    tarif: Mapped[Tarif] = relationship(back_populates="abonnements")

    @property
    def preis(self) -> Decimal:
        return self.individueller_preis if self.individueller_preis is not None else self.tarif.monatspreis


class Dokumentvorlage(Basis):
    __tablename__ = "dokumentvorlagen"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int | None] = mapped_column(ForeignKey("organisationen.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    dateiname: Mapped[str] = mapped_column(String(255))
    speicherort: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(50), default="wird analysiert")
    seiten: Mapped[int] = mapped_column(Integer, default=1)
    erkannte_felder: Mapped[int] = mapped_column(Integer, default=0)
    schema: Mapped[dict] = mapped_column(JSON, default=dict)
    zusammenfassung: Mapped[str] = mapped_column(Text, default="")
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    organisation: Mapped[Organisation | None] = relationship(back_populates="vorlagen")
    dialoge: Mapped[list[Vorlagendialog]] = relationship(back_populates="vorlage", cascade="all, delete-orphan")


class Vorlagendialog(Basis):
    __tablename__ = "vorlagendialoge"

    id: Mapped[int] = mapped_column(primary_key=True)
    vorlage_id: Mapped[int] = mapped_column(ForeignKey("dokumentvorlagen.id", ondelete="CASCADE"), index=True)
    rolle: Mapped[str] = mapped_column(String(20))
    nachricht: Mapped[str] = mapped_column(Text)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    vorlage: Mapped[Dokumentvorlage] = relationship(back_populates="dialoge")


class Nutzungsereignis(Basis):
    __tablename__ = "nutzungsereignisse"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int | None] = mapped_column(ForeignKey("organisationen.id"), nullable=True, index=True)
    art: Mapped[str] = mapped_column(String(80))
    menge: Mapped[int] = mapped_column(Integer, default=1)
    kosten_euro: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    einzelheiten: Mapped[dict] = mapped_column(JSON, default=dict)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
