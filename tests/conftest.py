import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import storage
from backend.main import app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA", tmp_path / "projects")
    monkeypatch.setenv("RESUME_DATA_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("RESUME_GLYPH_CACHE_DIR", str(tmp_path / "glyph-cache"))


@pytest.fixture
def client():
    return TestClient(app, base_url="http://127.0.0.1:8765")


@pytest.fixture
def samples():
    return ROOT / "examples"
