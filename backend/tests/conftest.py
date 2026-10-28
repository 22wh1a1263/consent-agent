import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["REFERENCE_DATE"] = "2026-10-15"
os.environ.pop("LLM_API_KEY", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def auth(client, username):
    token = client.post("/auth/login", json={"username": username}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def alice(client):
    h = auth(client, "alice")
    # start each test with a clean slate for alice's grants
    for g in client.get("/grants", headers=h).json():
        client.delete(f"/grants/{g['tool']}", headers=h)
    return h


@pytest.fixture()
def bob(client):
    return auth(client, "bob")
