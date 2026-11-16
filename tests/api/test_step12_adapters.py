"""Step 12: Blob backend end to end (fake client), downloads, Excel build guard, superseded jobs."""

import datetime as dt
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend import routes
from backend.cleanup import cleanup_expired
from backend.config import Settings
from backend.db import Dataset, Job, utcnow
from backend.main import create_app
from backend.storage import BlobStorage
from tests.api.fake_blob import FakeBlobClient
from tests.api.test_api import DOWNLOADS, app, cleaned, client, profiled, upload  # noqa: F401 (fixtures)


@pytest.fixture
def blob():
    return FakeBlobClient()


@pytest.fixture
def blob_app(tmp_path, blob):
    return create_app(Settings(storage_dir=tmp_path / "s"), storage=BlobStorage(blob))


@pytest.fixture
def blob_client(blob_app):
    with TestClient(blob_app) as c:
        yield c


def test_full_flow_on_blob_with_per_job_prefixes_and_a_shared_cache(blob_client, blob, blob_app, tmp_path):
    dataset_id, run_id = cleaned(blob_client)
    assert blob_client.get(f"/api/jobs/{run_id}").json()["status"] == "done"
    assert not list((tmp_path / "s").glob("*/"))                      # nothing on local disk but app.db
    keys = set(blob.blobs)
    assert f"{dataset_id}/original.csv" in keys and f"{dataset_id}/inspection.json" in keys
    assert any(k.startswith(f"{dataset_id}/cache/ingest-") and k.endswith(".parquet") for k in keys)
    assert {f"{dataset_id}/runs/{run_id}/{n}" for n in ("clean.csv", "changelog.csv", "recipe.yaml", "report.html")} <= keys

    for name in DOWNLOADS:
        r = blob_client.get(f"/api/datasets/{dataset_id}/downloads/{name}")
        assert r.status_code == 200 and r.content, name
        assert "attachment" in r.headers["content-disposition"] and "_" in r.headers["content-disposition"]
    assert blob_client.get(f"/api/datasets/{dataset_id}/downloads/clean.csv").headers["content-type"].startswith("text/csv")
    assert blob_client.get(f"/api/datasets/{dataset_id}/downloads/clean.xlsx").content.startswith(b"PK")
    assert blob_client.get(f"/api/datasets/{dataset_id}/results").json()["changes"]["total"] > 0


def test_a_clean_on_another_instance_reuses_the_cache_a_profile_stored(blob_client, blob, tmp_path, monkeypatch):
    dataset_id = profiled(blob_client)
    # A second app instance (own process memory, own temp folders) sharing only the blob store and database.
    from engine import ingest
    calls = []
    real = ingest.ingest
    monkeypatch.setattr(ingest, "ingest", lambda *a, **k: calls.append(1) or real(*a, **k))
    proposals = blob_client.get(f"/api/datasets/{dataset_id}/profile").json()["proposals"]
    r = blob_client.post(f"/api/datasets/{dataset_id}/clean", json={"approved": [p["id"] for p in proposals]})
    assert blob_client.get(f"/api/jobs/{r.json()['job_id']}").json()["status"] == "done"
    assert calls == []                                              # the file was not parsed again


def test_cleanup_deletes_a_datasets_blobs_by_prefix(blob_client, blob, blob_app):
    dataset_id, _ = cleaned(blob_client)
    other = profiled(blob_client)
    ctx = blob_app.state.ctx
    with Session(ctx.engine) as s:
        row = s.get(Dataset, dataset_id)
        row.expires_at = utcnow() - dt.timedelta(minutes=1)
        s.add(row)
        s.commit()
    assert cleanup_expired(ctx) == 1
    assert not [k for k in blob.blobs if k.startswith(dataset_id)]
    assert [k for k in blob.blobs if k.startswith(other)]
    assert blob_client.get(f"/api/datasets/{dataset_id}/results").status_code == 404


def test_orphan_blobs_are_removed_once_old(blob_client, blob, blob_app):
    stray = "11111111-1111-4111-8111-111111111111"
    blob.put_blob(f"{stray}/original.csv", b"x", access="private")
    ctx = blob_app.state.ctx
    assert cleanup_expired(ctx) == 0                                # too young: could be an upload in progress
    assert cleanup_expired(ctx, now=utcnow() + dt.timedelta(hours=2)) == 1
    assert not blob.blobs


# --------------------------------------------------------------------------- bug 2: one Excel build

def test_two_simultaneous_excel_requests_build_it_once(client, app, monkeypatch):
    dataset_id, _ = cleaned(client)
    builds = []
    real = routes.pipeline.build_xlsx

    def slow_build(out_dir):
        builds.append(1)
        time.sleep(1.0)
        return real(out_dir)

    monkeypatch.setattr(routes.pipeline, "build_xlsx", slow_build)
    results = []
    gate = threading.Barrier(2)

    def click():
        gate.wait()
        results.append(client.post(f"/api/datasets/{dataset_id}/downloads/clean.xlsx/prepare").status_code)

    threads = [threading.Thread(target=click) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results == [200, 200]
    assert len(builds) == 1                                         # the second request waited for the first


def test_dataset_deleted_during_the_excel_build_is_404_not_500(client, app, monkeypatch):
    from backend.cleanup import delete_dataset
    dataset_id, _ = cleaned(client)
    ctx = app.state.ctx
    real = routes.pipeline.build_xlsx

    def build_then_expire(out_dir):
        built = real(out_dir)
        with Session(ctx.engine) as s:
            delete_dataset(ctx, s, s.get(Dataset, dataset_id))
            s.commit()
        return built

    monkeypatch.setattr(routes.pipeline, "build_xlsx", build_then_expire)
    r = client.get(f"/api/datasets/{dataset_id}/downloads/clean.xlsx")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert not list(ctx.storage.root.glob(f"{dataset_id}*"))


def test_download_of_a_file_deleted_from_storage_is_404_or_409_never_500(client, app):
    dataset_id, run_id = cleaned(client)
    (app.state.ctx.storage.run_dir(dataset_id, run_id) / "report.html").unlink()
    assert client.get(f"/api/datasets/{dataset_id}/downloads/report.html").status_code in (404, 409)


def test_download_names_and_content_types(client):
    dataset_id, _ = cleaned(client)
    r = client.get(f"/api/datasets/{dataset_id}/downloads/changelog.csv")
    assert r.headers["content-disposition"] == 'attachment; filename="sales_orders_messy_changelog.csv"'
    assert r.headers["content-type"] == "text/csv; charset=utf-8"


# --------------------------------------------------------------------------- job states

def test_a_replaced_job_is_stored_as_superseded_and_shown_as_failed(client, app, monkeypatch):
    dataset_id = upload(client).json()["dataset_id"]
    held = []
    monkeypatch.setattr(routes, "run_profile_job", lambda *args: held.append(args))
    first = client.post(f"/api/datasets/{dataset_id}/profile", json={}).json()["job_id"]
    client.post(f"/api/datasets/{dataset_id}/profile", json={})
    with Session(app.state.ctx.engine) as s:
        assert s.get(Job, first).status == "superseded"
    body = client.get(f"/api/jobs/{first}").json()
    assert body["status"] == "failed" and body["error"]["code"] == "superseded"
    from backend.jobs import run_profile_job
    run_profile_job(*held[0])                                        # a late delivery does nothing
    with Session(app.state.ctx.engine) as s:
        assert s.get(Job, first).attempts == 0


def test_blob_and_database_are_chosen_by_environment(monkeypatch, tmp_path):
    from backend.db import normalize_url
    from backend.storage import LocalStorage, make_storage
    assert isinstance(make_storage(Settings(storage_dir=tmp_path)), LocalStorage)
    monkeypatch.setenv("DC_STORAGE_BACKEND", "blob")
    assert isinstance(make_storage(Settings(storage_dir=tmp_path)), BlobStorage)
    monkeypatch.setenv("DC_STORAGE_BACKEND", "s3")
    with pytest.raises(ValueError, match="DC_STORAGE_BACKEND"):
        Settings(storage_dir=tmp_path)
    monkeypatch.delenv("DC_STORAGE_BACKEND")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    assert Settings(storage_dir=tmp_path).database_url == "postgres://u:p@h/db"
    assert normalize_url("postgres://u:p@h/db?sslmode=require") == "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert normalize_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
