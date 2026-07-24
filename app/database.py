from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import einstellungen


class Basis(DeclarativeBase):
    pass


konfiguration = einstellungen()
engine = create_engine(konfiguration.database_url, pool_pre_ping=True)
Sitzung = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def datenbank_sitzung() -> Generator[Session, None, None]:
    sitzung = Sitzung()
    try:
        yield sitzung
    finally:
        sitzung.close()
