"""The built frontend (public/, made by the Vercel build) is mounted at / without hiding the API."""

from fastapi.testclient import TestClient

from backend import main
from backend.config import Settings


def test_public_dir_is_served_at_root_and_api_still_wins(tmp_path, monkeypatch):
    public = tmp_path / "public"
    public.mkdir()
    (public / "index.html").write_text("<h1>app</h1>")
    monkeypatch.setattr(main, "PUBLIC_DIR", public, raising=False)
    client = TestClient(main.create_app(Settings(storage_dir=tmp_path / "s")))
    assert "<h1>app</h1>" in client.get("/").text
    assert client.get("/api/health").json()["status"] == "ok"
    missing = client.get("/api/nope")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"


def test_without_public_dir_nothing_is_mounted(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "PUBLIC_DIR", tmp_path / "absent", raising=False)
    client = TestClient(main.create_app(Settings(storage_dir=tmp_path / "s")))
    assert client.get("/").json()["error"]["code"] == "not_found"
