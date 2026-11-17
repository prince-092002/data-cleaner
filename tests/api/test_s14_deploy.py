"""Step 14: production start-up guard, cap defaults and clamps, IPv6 grouping, change-log cache."""

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import limits
from backend.config import Settings
from backend.main import create_app
from backend.storage import BlobStorage
from tests.api.fake_blob import FakeBlobClient

SALES = Path(__file__).parents[2] / "sample_data" / "sales_orders_messy.csv"
PROD_OK = {"DC_STORAGE_BACKEND": "blob", "DC_JOB_RUNNER": "queue", "DATABASE_URL": "placeholder-database-url"}


# ----------------------------------------------------------------------------- c) start-up guard

@pytest.mark.parametrize("vercel_env", ["production", "preview"])
@pytest.mark.parametrize("missing", ["DC_STORAGE_BACKEND", "DC_JOB_RUNNER", "DATABASE_URL"])
def test_vercel_refuses_to_start_without_production_settings(monkeypatch, vercel_env, missing):
    monkeypatch.setenv("VERCEL_ENV", vercel_env)
    for k, v in PROD_OK.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError, match=missing):
        Settings()


def test_vercel_start_up_error_names_every_problem_in_one_message(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "production")
    for k in PROD_OK:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError) as e:
        Settings()
    assert all(k in str(e.value) for k in PROD_OK)


def test_vercel_starts_with_production_settings_and_dev_is_unchecked(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "production")
    for k, v in PROD_OK.items():
        monkeypatch.setenv(k, v)
    Settings()
    monkeypatch.setenv("VERCEL_ENV", "development")     # vercel dev: local rules
    monkeypatch.delenv("DATABASE_URL")
    Settings()


# ----------------------------------------------------------------------------- e) caps

def test_default_upload_cap_applies_only_to_the_queue_runner(monkeypatch):
    monkeypatch.delenv("DC_DAILY_UPLOAD_CAP", raising=False)
    monkeypatch.setenv("DC_JOB_RUNNER", "inprocess")
    assert Settings().daily_upload_cap is None
    monkeypatch.setenv("DC_JOB_RUNNER", "queue")
    assert Settings().daily_upload_cap == 5
    monkeypatch.setenv("DC_JOB_RUNNER", "inprocess")
    monkeypatch.setenv("DC_DAILY_UPLOAD_CAP", "3")
    assert Settings().daily_upload_cap == 3


def test_local_runs_are_not_upload_capped_by_default(tmp_path):
    app = create_app(Settings(storage_dir=tmp_path / "s"), storage=BlobStorage(FakeBlobClient()))
    with TestClient(app) as c:
        for _ in range(7):
            r = c.post("/api/datasets", files={"file": (SALES.name, io.BytesIO(b"a,b\n1,2\n"))})
            assert r.status_code == 201


def test_per_ip_caps_never_exceed_the_global_caps():
    s = Settings(daily_upload_cap=3, daily_ip_upload_cap=20, daily_job_cap=4, daily_ip_cap=10)
    assert (s.daily_ip_upload_cap, s.daily_ip_cap) == (3, 4)
    s = Settings(daily_upload_cap=30, daily_ip_upload_cap=2, daily_job_cap=40, daily_ip_cap=5)
    assert (s.daily_ip_upload_cap, s.daily_ip_cap) == (2, 5)
    assert Settings(daily_upload_cap=None, daily_ip_upload_cap=7).daily_ip_upload_cap == 7


def _request(ip):
    return SimpleNamespace(headers={"x-forwarded-for": ip})


def test_ipv6_addresses_share_a_slot_per_64_and_ipv4_is_unchanged():
    key = limits.ip_group
    assert key("2001:db8:1:2:aaaa:bbbb:cccc:dddd") == key("2001:db8:1:2:1::9") == "2001:db8:1:2::"
    assert key("2001:db8:1:3::1") != key("2001:db8:1:2::1")
    assert key("203.0.113.7") == "203.0.113.7"
    assert key("not-an-ip") == "not-an-ip"


def test_two_addresses_in_one_64_use_one_upload_slot(tmp_path):
    app = create_app(Settings(storage_dir=tmp_path / "s", daily_upload_cap=10, daily_ip_upload_cap=1),
                     storage=BlobStorage(FakeBlobClient()))
    up = lambda c, ip: c.post("/api/datasets", files={"file": ("a.csv", io.BytesIO(b"a,b\n1,2\n"))},
                              headers={"x-forwarded-for": ip})
    with TestClient(app) as c:
        assert up(c, "2001:db8:1:2::1").status_code == 201
        assert up(c, "2001:db8:1:2:ffff::2").status_code == 429
        assert up(c, "2001:db8:1:9::1").status_code == 201


# ----------------------------------------------------------------------------- e) N2 change-log cache

def test_change_log_is_downloaded_once_per_run(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    fake = FakeBlobClient()
    app = create_app(Settings(storage_dir=tmp_path / "s"), storage=BlobStorage(fake))
    with TestClient(app) as c:
        d = c.post("/api/datasets", files={"file": (SALES.name, io.BytesIO(SALES.read_bytes()))}).json()["dataset_id"]
        assert c.post(f"/api/datasets/{d}/profile", json={}).status_code == 202
        assert c.post(f"/api/datasets/{d}/clean", json={}).status_code == 202
        first = c.get(f"/api/datasets/{d}/results?limit=5").json()
        gets = fake.calls["get"]
        second = c.get(f"/api/datasets/{d}/results?limit=5&offset=5").json()
        third = c.get(f"/api/datasets/{d}/results?limit=5&rule_id=coerce_numeric").json()
        assert fake.calls["get"] == gets, "page and filter clicks must not download the change log again"
        assert first["changes"]["total"] == second["changes"]["total"] > 5
        assert second["changes"]["items"] != first["changes"]["items"]
        assert third["changes"]["total"] < first["changes"]["total"]
