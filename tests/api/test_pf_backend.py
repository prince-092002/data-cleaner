"""Pre-deploy backend tidy-up: cleanup loop only in-process, cron time budget, one-lease Excel wait,
count the job before the dataset is changed, per-job expiry, counter_set race, zip-bomb guard."""

import datetime as dt
import io
import threading
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend import cron, jobs, main
from backend.config import Settings
from backend.db import Counter, Dataset, Job, acquire_lease, counter_set, make_engine, utcnow
from backend.main import create_app
from backend.storage import MAX_XLSX_UNCOMPRESSED, BlobStorage, looks_like, run_key
from tests.api.fake_blob import FakeBlobClient

SALES = Path(__file__).parents[2] / "sample_data" / "sales_orders_messy.csv"
CUSTOMERS = Path(__file__).parents[2] / "sample_data" / "customers_messy.xlsx"
AUTH = {"Authorization": "Bearer pf-secret"}


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "pf-secret")


def make(tmp_path, **settings):
    fake = FakeBlobClient()
    return create_app(Settings(storage_dir=tmp_path / "s", **settings), storage=BlobStorage(fake)), fake


def upload(c) -> str:
    r = c.post("/api/datasets", files={"file": (SALES.name, io.BytesIO(SALES.read_bytes()))})
    assert r.status_code == 201, r.text
    return r.json()["dataset_id"]


def stuck_job(app, dataset_id, job_id):
    now = utcnow()
    with Session(app.state.ctx.engine) as s:
        s.add(Job(id=job_id, dataset_id=dataset_id, type="profile", status="running", started_at=now,
                  deadline_at=now - dt.timedelta(minutes=5), created_at=now, updated_at=now))
        s.commit()


def status(app, job_id) -> str:
    with Session(app.state.ctx.engine) as s:
        return s.get(Job, job_id).status


# ----------------------------------------------------------------------------- 2: cleanup loop

@pytest.mark.parametrize("runner, starts", [("queue", 0), ("inprocess", 1)])
def test_cleanup_loop_starts_only_for_the_inprocess_runner(tmp_path, monkeypatch, runner, starts):
    started = []

    async def fake_loop(ctx):
        started.append(1)

    monkeypatch.setattr(main, "cleanup_loop", fake_loop)
    app, _ = make(tmp_path, job_runner=runner)
    with TestClient(app):
        pass
    assert len(started) == starts


# ----------------------------------------------------------------------------- 5: cron budget

def test_cron_stops_at_its_budget_and_the_next_run_resumes(tmp_path, monkeypatch):
    app, fake = make(tmp_path)
    with TestClient(app) as c:
        ids = [upload(c) for _ in range(2)]
        with Session(app.state.ctx.engine) as s:
            for i in ids:
                d = s.get(Dataset, i)
                d.expires_at = utcnow() - dt.timedelta(hours=1)
                s.add(d)
            s.commit()
        monkeypatch.setattr(cron, "BUDGET_SECONDS", 0)
        r = c.get("/api/cron/cleanup", headers=AUTH)
        assert r.status_code == 200 and r.json()["partial"] is True
        assert fake.blobs                                      # not everything was deleted
        monkeypatch.setattr(cron, "BUDGET_SECONDS", 200)
        r = c.get("/api/cron/cleanup", headers=AUTH)
        assert r.json()["partial"] is False and fake.blobs == {}


# ----------------------------------------------------------------------------- 6: Excel wait

def test_excel_wait_is_one_lease_and_gives_the_clean_error(tmp_path, monkeypatch):
    app, fake = make(tmp_path)
    ctx = app.state.ctx
    with TestClient(app) as c:
        dataset_id = upload(c)
        run_id = "22222222-2222-4222-8222-222222222222"
        with Session(ctx.engine) as s:
            d = s.get(Dataset, dataset_id)
            d.results_json, d.results_run_id = "{}", run_id
            s.add(d)
            s.commit()
        ctx.storage.put_bytes(run_key(dataset_id, run_id, "clean.csv"), b"a\n1\n")
        assert acquire_lease(ctx.engine, f"xlsx:{run_id}", dataset_id, 600)      # another request is building
        monkeypatch.setattr(jobs, "XLSX_LEASE_SECONDS", 1)
        t = time.monotonic()
        r = c.post(f"/api/datasets/{dataset_id}/downloads/clean.xlsx/prepare")
        assert r.status_code == 500 and r.json()["error"]["code"] == "excel_failed"
        assert time.monotonic() - t < 2.5            # one lease (1 s here), not three


# ----------------------------------------------------------------------------- 8: refused request

def test_refused_profile_request_leaves_the_dataset_unchanged(tmp_path):
    app, _ = make(tmp_path, daily_job_cap=0)
    with TestClient(app) as c:
        dataset_id = upload(c)
        r = c.post(f"/api/datasets/{dataset_id}/profile", json={"header_row": 1})
        assert r.status_code == 429
        with Session(app.state.ctx.engine) as s:
            d = s.get(Dataset, dataset_id)
            assert d.sheet is None and d.header_row is None


# ----------------------------------------------------------------------------- 14: per-job expiry

def test_job_poll_expires_only_that_job(tmp_path):
    app, _ = make(tmp_path)
    a, b = "33333333-3333-4333-8333-333333333333", "44444444-4444-4444-8444-444444444444"
    with TestClient(app) as c:
        dataset_id = upload(c)
        stuck_job(app, dataset_id, a)
        stuck_job(app, dataset_id, b)
        assert c.get(f"/api/jobs/{a}").json()["status"] == "failed"
        assert status(app, b) == "running"                    # not touched by someone else's poll
        assert c.get("/api/cron/cleanup", headers=AUTH).json()["expired_jobs"] == 1
        assert status(app, b) == "failed"


# ----------------------------------------------------------------------------- 15: counter_set race

def test_two_first_time_counter_set_calls_do_not_fail(tmp_path):
    engine = make_engine(tmp_path / "app.db")
    errors = []
    for i in range(30):
        barrier = threading.Barrier(2)

        def call(n, key=f"k{i}"):
            barrier.wait()
            try:
                counter_set(engine, key, n)
            except Exception as exc:               # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=call, args=(n,)) for n in (1, 2)]
        [t.start() for t in threads]
        [t.join() for t in threads]
    assert errors == []
    with Session(engine) as s:
        assert all(s.get(Counter, f"k{i}").n in (1, 2) for i in range(30))


# ----------------------------------------------------------------------------- 4: zip size

def _xlsx_with(tmp_path, payload_size: int) -> Path:
    path = tmp_path / "x.xlsx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", b"0" * payload_size)
    return path


def test_xlsx_that_expands_past_the_limit_is_rejected(tmp_path):
    bomb = _xlsx_with(tmp_path, MAX_XLSX_UNCOMPRESSED + 1024)
    assert bomb.stat().st_size < 1024 * 1024                  # tiny on disk, huge when opened
    assert looks_like(bomb, "xlsx") is False
    assert looks_like(_xlsx_with(tmp_path, 1024), "xlsx") is True
    assert looks_like(CUSTOMERS, "xlsx") is True
