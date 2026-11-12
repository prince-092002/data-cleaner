"""M6 step 4: an old job can never overwrite a newer one; the upload cap holds while streaming."""

import asyncio
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend import routes
from backend.config import MB, Settings
from backend.db import Job
from backend.jobs import run_clean_job, run_profile_job
from backend.main import create_app

SALES = Path(__file__).parents[2] / "sample_data" / "sales_orders_messy.csv"
CRLF = b"\r\n"


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(storage_dir=tmp_path / "storage"))


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def _upload(client) -> str:
    r = client.post("/api/datasets", files={"file": (SALES.name, io.BytesIO(SALES.read_bytes()))})
    assert r.status_code == 201
    return r.json()["dataset_id"]


def _job(app, job_id) -> Job:
    with Session(app.state.ctx.engine) as session:
        return session.get(Job, job_id)


# --------------------------------------------------------------------------- stale jobs

def test_old_profile_job_finishing_late_is_discarded(client, app, monkeypatch):
    dataset_id = _upload(client)
    held = []
    monkeypatch.setattr(routes, "run_profile_job", lambda *args: held.append(args))
    old_job = client.post(f"/api/datasets/{dataset_id}/profile", json={"header_row": 1}).json()["job_id"]
    monkeypatch.setattr(routes, "run_profile_job", run_profile_job)

    new_job = client.post(f"/api/datasets/{dataset_id}/profile", json={"header_row": 0}).json()["job_id"]
    assert client.get(f"/api/jobs/{new_job}").json()["status"] == "done"

    run_profile_job(*held[0])                              # the old job finishes last
    old = client.get(f"/api/jobs/{old_job}").json()
    assert old["status"] == "failed" and old["error"]["code"] == "superseded"
    assert client.get(f"/api/datasets/{dataset_id}/profile").json()["source"]["header_row"] == 0


def test_old_clean_job_finishing_late_is_discarded(client, app, monkeypatch):
    dataset_id = _upload(client)
    client.post(f"/api/datasets/{dataset_id}/profile")
    held = []
    monkeypatch.setattr(routes, "run_clean_job", lambda *args: held.append(args))
    old_job = client.post(f"/api/datasets/{dataset_id}/clean", json={}).json()["job_id"]
    monkeypatch.setattr(routes, "run_clean_job", run_clean_job)

    client.post(f"/api/datasets/{dataset_id}/profile")      # a new profile replaces everything
    run_clean_job(*held[0])
    assert _job(app, old_job).error_code == "superseded"
    assert client.get(f"/api/datasets/{dataset_id}/results").status_code == 409
    assert client.get(f"/api/datasets/{dataset_id}/downloads/clean.csv").status_code == 409


def test_newest_clean_wins_when_two_cleans_overlap(client, app, monkeypatch):
    dataset_id = _upload(client)
    client.post(f"/api/datasets/{dataset_id}/profile")
    held = []
    monkeypatch.setattr(routes, "run_clean_job", lambda *args: held.append(args))
    old_job = client.post(f"/api/datasets/{dataset_id}/clean", json={}).json()["job_id"]
    monkeypatch.setattr(routes, "run_clean_job", run_clean_job)
    new_job = client.post(f"/api/datasets/{dataset_id}/clean", json={}).json()["job_id"]

    old_dir = app.state.ctx.storage.run_dir(dataset_id, old_job)
    assert old_dir.exists()                                 # never deleted while its job may still write
    run_clean_job(*held[0])
    assert not old_dir.exists()                             # removed by the superseded job itself
    assert client.get(f"/api/datasets/{dataset_id}/results").json()["run_id"] == new_job
    assert _job(app, old_job).error_code == "superseded"
    assert client.get(f"/api/datasets/{dataset_id}/downloads/changelog.csv").text.count(old_job) == 0


# --------------------------------------------------------------------------- upload cap

def _multipart_chunks(payload: bytes, chunk: int) -> list[bytes]:
    boundary = b"testboundary"
    head = (b"--" + boundary + CRLF
            + b'Content-Disposition: form-data; name="file"; filename="big.csv"' + CRLF
            + b"Content-Type: text/csv" + CRLF + CRLF)
    body = head + payload + CRLF + b"--" + boundary + b"--" + CRLF
    return [body[i:i + chunk] for i in range(0, len(body), chunk)]


def _post_chunked(app, chunks: list[bytes]) -> tuple[int, int, dict]:
    """POST over raw ASGI with no Content-Length; returns (chunks pulled by the app, status, body).
    TestClient reads the whole body up front, so it cannot show when the server stops reading."""
    pulled = 0

    async def receive():
        nonlocal pulled
        if pulled < len(chunks):
            pulled += 1
            return {"type": "http.request", "body": chunks[pulled - 1], "more_body": pulled < len(chunks)}
        return {"type": "http.disconnect"}

    sent = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/api/datasets", "raw_path": b"/api/datasets", "query_string": b"",
        "root_path": "", "client": ("test", 1), "server": ("test", 80),
        "headers": [(b"host", b"test"), (b"content-type", b"multipart/form-data; boundary=testboundary")],
    }
    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return pulled, status, json.loads(body)


def _csv(rows: int) -> bytes:
    return b"a,b\n" + b"1,2\n" * rows


def test_upload_without_content_length_stops_once_over_the_limit(tmp_path):
    app = create_app(Settings(storage_dir=tmp_path / "s", max_upload_bytes=1 * MB))
    chunks = _multipart_chunks(_csv(2 * MB), 64 * 1024)          # about 8 MB
    pulled, status, body = _post_chunked(app, chunks)
    assert status == 413 and body["error"]["code"] == "file_too_large"
    assert "1 MB" in body["error"]["message"]
    assert pulled < len(chunks) / 2                         # stopped early, did not read it all
    assert [p.name for p in (tmp_path / "s").iterdir()] == ["app.db"]


def test_upload_without_content_length_under_the_limit_is_accepted(tmp_path):
    app = create_app(Settings(storage_dir=tmp_path / "s", max_upload_bytes=1 * MB))
    pulled, status, body = _post_chunked(app, _multipart_chunks(_csv(1000), 1024))
    assert status == 201 and body["file_type"] == "csv"


def test_upload_limit_comes_from_dc_max_upload_mb(monkeypatch, tmp_path):
    monkeypatch.setenv("DC_MAX_UPLOAD_MB", "4")
    settings = Settings(storage_dir=tmp_path / "s")
    assert settings.max_upload_bytes == 4 * MB
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json() == {"status": "ok", "max_upload_mb": 4}
    monkeypatch.delenv("DC_MAX_UPLOAD_MB")
    assert Settings().max_upload_bytes == 50 * MB


def test_download_of_a_missing_output_file_is_409_not_500(client, app):
    dataset_id = _upload(client)
    client.post(f"/api/datasets/{dataset_id}/profile")
    run_id = client.post(f"/api/datasets/{dataset_id}/clean", json={}).json()["job_id"]
    (app.state.ctx.storage.run_dir(dataset_id, run_id) / "clean.csv").unlink()
    r = client.get(f"/api/datasets/{dataset_id}/downloads/clean.csv")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_ready"


def test_upload_limit_accepts_decimal_megabytes_and_rejects_nonsense(monkeypatch, tmp_path):
    monkeypatch.setenv("DC_MAX_UPLOAD_MB", "4.5")
    settings = Settings(storage_dir=tmp_path / "s")
    assert settings.max_upload_bytes == int(4.5 * MB)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json()["max_upload_mb"] == 4.5
    monkeypatch.setenv("DC_MAX_UPLOAD_MB", "4MB")
    with pytest.raises(ValueError, match="DC_MAX_UPLOAD_MB"):
        Settings(storage_dir=tmp_path / "s")
