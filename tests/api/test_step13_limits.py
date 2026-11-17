"""Step 13: cron cleanup, immediate deletion, Blob guard, daily job caps (all on FakeBlobClient storage)."""

import datetime as dt
import io
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from backend import limits
from backend.cleanup import cleanup_expired
from backend.config import Settings
from backend.db import Counter, Dataset, Job, acquire_lease, release_lease, utcnow
from backend.main import create_app
from backend.storage import BlobStorage
from tests.api.fake_blob import FakeBlobClient

SALES = Path(__file__).parents[2] / "sample_data" / "sales_orders_messy.csv"
SECRET = "test-cron-secret-123"
AUTH = {"Authorization": f"Bearer {SECRET}"}
MSG_GLOBAL = "The demo has reached today's limit. Please try again tomorrow."
MSG_IP = "You have reached today's limit for this demo. Please try again tomorrow."


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", SECRET)


def make(tmp_path, **settings):
    fake = FakeBlobClient()
    app = create_app(Settings(storage_dir=tmp_path / "s", **settings), storage=BlobStorage(fake))
    return app, fake


def upload(client) -> str:
    r = client.post("/api/datasets", files={"file": (SALES.name, io.BytesIO(SALES.read_bytes()))})
    assert r.status_code == 201, r.text
    return r.json()["dataset_id"]


def expire(app, dataset_id, delta):
    with Session(app.state.ctx.engine) as s:
        d = s.get(Dataset, dataset_id)
        d.expires_at = utcnow() + delta
        s.add(d)
        s.commit()


def counter(app, key) -> int | None:
    with Session(app.state.ctx.engine) as s:
        c = s.get(Counter, key)
        return c.n if c else None


# ----------------------------------------------------------------------------- a) cron

def test_cron_rejects_missing_wrong_and_unset_secret(tmp_path, monkeypatch):
    app, fake = make(tmp_path)
    with TestClient(app) as c:
        dataset_id = upload(c)
        expire(app, dataset_id, -dt.timedelta(hours=1))
        assert c.get("/api/cron/cleanup").status_code == 401
        assert c.get("/api/cron/cleanup", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert c.get("/api/cron/cleanup", headers={"Authorization": SECRET}).status_code == 401   # no Bearer
        monkeypatch.delenv("CRON_SECRET")
        assert c.get("/api/cron/cleanup", headers={"Authorization": "Bearer "}).status_code == 401
        assert c.get("/api/cron/cleanup", headers=AUTH).status_code == 401
        assert fake.blobs                                   # nothing was deleted
        with Session(app.state.ctx.engine) as s:
            assert s.get(Dataset, dataset_id) is not None


def test_cron_deletes_blobs_and_rows_together(tmp_path):
    app, fake = make(tmp_path)
    with TestClient(app) as c:
        dataset_id = upload(c)
        assert c.post(f"/api/datasets/{dataset_id}/profile").status_code == 202
        assert c.post(f"/api/datasets/{dataset_id}/clean", json={}).status_code == 202
        assert fake.blobs and counter(app, "stored_bytes") > 0
        expire(app, dataset_id, -dt.timedelta(minutes=1))
        r = c.get("/api/cron/cleanup", headers=AUTH)
        assert r.status_code == 200 and r.json()["removed"] == 1
        assert fake.blobs == {}
        with Session(app.state.ctx.engine) as s:
            assert s.exec(select(Dataset)).all() == [] and s.exec(select(Job)).all() == []
        assert counter(app, "stored_bytes") == 0
        assert c.get(f"/api/datasets/{dataset_id}/downloads/clean.csv").status_code == 404


def test_cleanup_at_the_24_hour_boundary(tmp_path):
    app, fake = make(tmp_path)
    ctx = app.state.ctx
    with TestClient(app) as c:
        dataset_id = upload(c)
    with Session(ctx.engine) as s:
        expires = s.get(Dataset, dataset_id).expires_at
    assert cleanup_expired(ctx, now=expires - dt.timedelta(seconds=1)) == 0     # just under 24 h
    assert fake.blobs
    assert cleanup_expired(ctx, now=expires + dt.timedelta(seconds=1)) == 1     # just over
    assert fake.blobs == {}


def test_cron_skips_while_another_run_holds_the_lease(tmp_path):
    app, fake = make(tmp_path)
    with TestClient(app) as c:
        dataset_id = upload(c)
        expire(app, dataset_id, -dt.timedelta(hours=1))
        holder = acquire_lease(app.state.ctx.engine, "cron:cleanup", "-", 600)
        r = c.get("/api/cron/cleanup", headers=AUTH)
        assert r.status_code == 200 and r.json()["skipped"] is True and fake.blobs
        release_lease(app.state.ctx.engine, "cron:cleanup", holder)
        assert c.get("/api/cron/cleanup", headers=AUTH).json()["removed"] == 1


def test_two_simultaneous_cron_calls_are_safe(tmp_path):
    app, fake = make(tmp_path)
    with TestClient(app) as c:
        for _ in range(3):
            expire(app, upload(c), -dt.timedelta(hours=1))
        codes = []
        threads = [threading.Thread(target=lambda: codes.append(c.get("/api/cron/cleanup", headers=AUTH).status_code))
                   for _ in range(2)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert codes == [200, 200] and fake.blobs == {}


def test_cron_recomputes_the_byte_total(tmp_path):
    app, fake = make(tmp_path)
    with TestClient(app) as c:
        upload(c)
        real = sum(len(b) for b in fake.blobs.values())
        with Session(app.state.ctx.engine) as s:
            s.get(Counter, "stored_bytes").n = 7
            s.commit()
        c.get("/api/cron/cleanup", headers=AUTH)
        assert counter(app, "stored_bytes") == real


# ----------------------------------------------------------------------------- b) immediate deletion

def test_new_profile_deletes_old_results_at_once(tmp_path):
    app, fake = make(tmp_path)
    with TestClient(app) as c:
        dataset_id = upload(c)
        c.post(f"/api/datasets/{dataset_id}/profile")
        c.post(f"/api/datasets/{dataset_id}/clean", json={})
        assert any("/runs/" in k for k in fake.blobs)
        before = counter(app, "stored_bytes")
        c.post(f"/api/datasets/{dataset_id}/profile")
        assert not any("/runs/" in k for k in fake.blobs)
        assert counter(app, "stored_bytes") < before
        assert c.get(f"/api/datasets/{dataset_id}/downloads/clean.csv").status_code == 409


def test_expired_dataset_downloads_are_404(tmp_path):
    app, _ = make(tmp_path)
    with TestClient(app) as c:
        dataset_id = upload(c)
        c.post(f"/api/datasets/{dataset_id}/profile")
        c.post(f"/api/datasets/{dataset_id}/clean", json={})
        expire(app, dataset_id, -dt.timedelta(seconds=1))
        assert c.get(f"/api/datasets/{dataset_id}/downloads/clean.csv").status_code == 404


# ----------------------------------------------------------------------------- c) Blob guard

def test_upload_refused_when_storage_is_full(tmp_path):
    app, fake = make(tmp_path, storage_limit_bytes=1)
    with TestClient(app) as c:
        upload(c)                                            # empty store: accepted
        r = c.post("/api/datasets", files={"file": (SALES.name, io.BytesIO(SALES.read_bytes()))})
        assert r.status_code == 503
        assert r.json()["error"] == {"code": "storage_full",
                                     "message": "The demo is full right now. Please try again tomorrow."}
        assert len(fake.blobs) == 2                          # the refused upload wrote nothing


# ----------------------------------------------------------------------------- d) caps

def test_global_daily_cap_counts_profile_and_clean_and_resets_by_date(tmp_path, monkeypatch):
    app, _ = make(tmp_path, daily_job_cap=2)
    with TestClient(app) as c:
        dataset_id = upload(c)
        assert c.post(f"/api/datasets/{dataset_id}/profile").status_code == 202
        assert c.post(f"/api/datasets/{dataset_id}/clean", json={}).status_code == 202
        r = c.post(f"/api/datasets/{dataset_id}/profile")
        assert r.status_code == 429
        assert r.json()["error"] == {"code": "too_many_jobs", "message": MSG_GLOBAL}
        tomorrow = limits.utc_today() + dt.timedelta(days=1)
        monkeypatch.setattr(limits, "utc_today", lambda: tomorrow)
        assert c.post(f"/api/datasets/{dataset_id}/profile").status_code == 202


def test_ip_cap_is_per_address_and_stores_only_a_hash(tmp_path):
    app, _ = make(tmp_path, daily_ip_cap=2)
    a, b = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}, {"x-forwarded-for": "198.51.100.9"}
    with TestClient(app) as c:
        dataset_id = upload(c)
        url = f"/api/datasets/{dataset_id}/profile"
        assert [c.post(url, headers=a).status_code for _ in range(2)] == [202, 202]
        r = c.post(url, headers=a)
        assert r.status_code == 429 and r.json()["error"] == {"code": "too_many_jobs", "message": MSG_IP}
        assert c.post(url, headers=b).status_code == 202       # another address is unaffected
        assert [c.post(url).status_code for _ in range(4)] == [202] * 4   # no header: no shared bucket
        with Session(app.state.ctx.engine) as s:
            keys = [k.key for k in s.exec(select(Counter)).all()]
        assert not any("203.0.113.7" in k or "198.51.100.9" in k for k in keys)


def test_global_refusal_does_not_use_up_the_ip_allowance(tmp_path):
    # Per-IP caps never exceed the global cap (config clamp), so the hand-back shows with a second address.
    app, _ = make(tmp_path, daily_job_cap=1, daily_ip_cap=1)
    a, b = {"x-forwarded-for": "203.0.113.7"}, {"x-forwarded-for": "198.51.100.9"}
    with TestClient(app) as c:
        dataset_id = upload(c)
        url = f"/api/datasets/{dataset_id}/profile"
        assert c.post(url, headers=a).status_code == 202
        r = c.post(url, headers=b)
        assert r.status_code == 429 and r.json()["error"]["message"] == MSG_GLOBAL
        with Session(app.state.ctx.engine) as s:
            ip_rows = sorted(k.n for k in s.exec(select(Counter)).all() if k.key.startswith("ip:"))
        assert ip_rows == [0, 1]


# ----------------------------------------------------------------------------- round 2

def test_cron_expires_a_stuck_running_job(tmp_path):
    app, _ = make(tmp_path)
    with TestClient(app) as c:
        dataset_id = upload(c)
        now = utcnow()
        with Session(app.state.ctx.engine) as s:
            s.add(Job(id="11111111-1111-4111-8111-111111111111", dataset_id=dataset_id, type="profile",
                      status="running", started_at=now - dt.timedelta(hours=1),
                      deadline_at=now - dt.timedelta(minutes=5), created_at=now, updated_at=now))
            s.commit()
        r = c.get("/api/cron/cleanup", headers=AUTH)
        assert r.status_code == 200 and r.json()["expired_jobs"] == 1
        with Session(app.state.ctx.engine) as s:
            assert s.get(Job, "11111111-1111-4111-8111-111111111111").status == "failed"


def _ip_keys(tmp_path, monkeypatch, salt):
    if salt:
        monkeypatch.setenv("DC_IP_HASH_SALT", salt)
    else:
        monkeypatch.delenv("DC_IP_HASH_SALT", raising=False)
    app, _ = make(tmp_path / (salt or "none"))
    with TestClient(app) as c:
        c.post(f"/api/datasets/{upload(c)}/profile", headers={"x-forwarded-for": "203.0.113.7"})
        with Session(app.state.ctx.engine) as s:
            return [k.key for k in s.exec(select(Counter)).all() if k.key.startswith("ip:")]


def test_ip_key_hides_the_address_and_changes_with_the_salt(tmp_path, monkeypatch):
    a = _ip_keys(tmp_path, monkeypatch, "salt-one")
    b = _ip_keys(tmp_path, monkeypatch, "salt-two")
    assert len(a) == len(b) == 1 and a != b
    assert "203.0.113.7" not in a[0] and "salt-one" not in a[0]


# ----------------------------------------------------------------------------- round 3

UP_GLOBAL = "The demo has reached today's upload limit. Please try again tomorrow."
UP_IP = "You have reached today's upload limit for this demo. Please try again tomorrow."


def post_upload(c, headers=None, name=SALES.name, data=None):
    return c.post("/api/datasets", files={"file": (name, io.BytesIO(SALES.read_bytes() if data is None else data))},
                  headers=headers or {})


def test_upload_ip_cap_refuses_over_the_cap_and_resets_by_date(tmp_path, monkeypatch):
    app, fake = make(tmp_path, daily_ip_upload_cap=2)
    a, b = {"x-forwarded-for": "203.0.113.7"}, {"x-forwarded-for": "198.51.100.9"}
    with TestClient(app) as c:
        assert [post_upload(c, a).status_code for _ in range(2)] == [201, 201]
        r = post_upload(c, a)
        assert r.status_code == 429 and r.json()["error"] == {"code": "too_many_uploads", "message": UP_IP}
        assert len(fake.blobs) == 4                           # the refused upload saved nothing
        assert post_upload(c, b).status_code == 201           # another address is unaffected
        assert post_upload(c).status_code == 201              # no header: no per-IP cap
        tomorrow = limits.utc_today() + dt.timedelta(days=1)
        monkeypatch.setattr(limits, "utc_today", lambda: tomorrow)
        assert post_upload(c, a).status_code == 201


def test_global_upload_cap(tmp_path):
    app, _ = make(tmp_path, daily_upload_cap=1)
    with TestClient(app) as c:
        assert post_upload(c).status_code == 201
        r = post_upload(c)
        assert r.status_code == 429 and r.json()["error"] == {"code": "too_many_uploads", "message": UP_GLOBAL}


def test_rejected_uploads_do_not_spend_an_upload_slot(tmp_path):
    app, _ = make(tmp_path, daily_ip_upload_cap=1, daily_upload_cap=1, max_upload_bytes=1000)
    h = {"x-forwarded-for": "203.0.113.7"}
    with TestClient(app) as c:
        assert post_upload(c, h, name="x.txt").status_code == 415      # wrong type
        assert post_upload(c, h).status_code == 413                    # too large
        assert post_upload(c, h, data=b"a,b\n1,2\n").status_code == 201  # slot still free
    app2, _ = make(tmp_path / "full", daily_ip_upload_cap=1, storage_limit_bytes=1)
    with TestClient(app2) as c:
        assert post_upload(c, h, data=b"a,b\n1,2\n").status_code == 201
        assert post_upload(c, h).status_code == 503                    # storage_full
        with Session(app2.state.ctx.engine) as s:
            used = [k.n for k in s.exec(select(Counter)).all() if k.key.startswith("upip:")]
        assert used == [1]
