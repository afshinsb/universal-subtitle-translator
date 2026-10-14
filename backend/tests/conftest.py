"""Keep the developer's .env, database, media and credentials out of tests."""
import os

import pytest

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["OPENAI_API_KEY"] = ""
os.environ["OPENAI_MODEL"] = "test-model"
os.environ["MEDIA_ROOT"] = ""


@pytest.fixture(autouse=True)
def isolated_data(monkeypatch, tmp_path):
    from app.config import settings
    from app.services import translator

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    for name in ("upload", "output", "temp"):
        monkeypatch.setattr(settings, f"{name}_dir", tmp_path / "data" / name)
    monkeypatch.setattr(settings, "database_path", tmp_path / "data" / "app.db")
    monkeypatch.setattr(settings, "media_root", None)

    def no_provider():
        raise AssertionError("Tests must mock the translation provider.")

    monkeypatch.setattr(translator, "get_openai_client", no_provider)


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "auth_enabled", False)
    with TestClient(app) as test_client:
        yield test_client
