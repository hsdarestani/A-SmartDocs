from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest


TEST_DB = Path("/tmp/a-smartdocs-pytest.sqlite3")
TEST_DATA = Path("/tmp/a-smartdocs-pytest-daten")
TEST_DB.unlink(missing_ok=True)
shutil.rmtree(TEST_DATA, ignore_errors=True)

os.environ["DOMAIN"] = "localhost"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["DATENPFAD"] = str(TEST_DATA)
os.environ["APP_SECRET"] = "pytest-smartdocs-geheimnis"
os.environ["OPENAI_API_KEY"] = ""
os.environ["MAX_UPLOAD_MB"] = "2"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def saubere_sitzung(client: TestClient):
    client.post("/abmelden")
    yield
    client.post("/abmelden")
