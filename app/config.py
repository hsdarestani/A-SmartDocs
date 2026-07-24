from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Einstellungen(BaseSettings):
    domain: str = "localhost"
    database_url: str = "sqlite:////daten/smartdocs.sqlite3"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    app_secret: str = "entwicklung-nicht-fuer-produktivbetrieb"
    max_upload_mb: int = 20
    datenpfad: Path = Path("/daten")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def upload_pfad(self) -> Path:
        pfad = self.datenpfad / "hochgeladen"
        pfad.mkdir(parents=True, exist_ok=True)
        return pfad

    @property
    def ausgabe_pfad(self) -> Path:
        pfad = self.datenpfad / "ausgaben"
        pfad.mkdir(parents=True, exist_ok=True)
        return pfad


@lru_cache
def einstellungen() -> Einstellungen:
    return Einstellungen()
