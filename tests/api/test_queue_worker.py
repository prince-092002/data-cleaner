"""Step 13: job runner selection, queue consumer, deadline, retries and stuck-job expiry (fake queue, fake storage)."""

import datetime as dt
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlmodel import Session

from backend import jobs, runner, worker
from backend.config import Settings
from backend.db import Dataset, Job, expire_stuck_jobs, utcnow
from backend.jobs import RetryJob
from backend.main import create_app
from backend.storage import BlobStorage
from engine.errors import IngestError
from tests.api.fake_blob import FakeBlobClient
from tests.api.test_api import upload

TIMEOUT_MESSAGE = "This file took too long to process. Try a smaller file."


class FakeQueue:
    """Records sends; deliver() redelivers while the consumer asks for a retry, as the real queue does."""

    def __init__(self):
        self.sent: list[str] = []
        self.fail_sends = False

    def send(self, job_id: str) -> None:
        if self.fail_sends:
            raise RuntimeError("https://queue.internal/secret-token")
        self.sent.append(job_id)

    def deliver(self, ctx, job_id: str, limit: int = 10) -> int:
        for n in range(1, limit + 1):
            try:
                worker.handle_message(ctx, job_id)
                return n
            except RetryJob:
                continue
        raise AssertionError("retried forever")


@pytest.fixture
def queue(monkeypatch):
    fake = FakeQueue()
    monkeypatch.setattr(runner, "send_job_message", fake.send)
    return fake


def make_app(tmp_path, **settings):
    return create_app(Settings(storage_dir=tmp_path / "s", job_runner="queue", **settings),
                      storage=BlobStorage(FakeBlobClient()))


@pytest.fixture
def app(tmp_path, queue):
    return make_app(tmp_path)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def start_profile(client) -> tuple[str, str]:
    dataset_id = upload(client).json()["dataset_id"]
    r = client.post(f"/api/datasets/{dataset_id}/profile", json={})
    assert r.status_code == 202
    return dataset_id, r.json()["job_id"]


def job_state(client, job_id) -> dict:
    return client.get(f"/api/jobs/{job_id}").json()


def count_calls(monkeypatch, name, replacement=None):
    calls = []
    real = getattr(jobs.pipeline, name)

    def wrapper(*args, **kwargs):
        calls.append(1)
        return (replacement or real)(*args, **kwargs)

    monkeypatch.setattr(jobs.pipeline, name, wrapper)
    return calls


# --------------------------------------------------------------------------- selection and start

def test_default_runner_is_inprocess_and_queue_needs_the_setting(monkeypatch):
    monkeypatch.delenv("DC_JOB_RUNNER", raising=False)
    monkeypatch.setenv("VERCEL", "1")                      # Vercel variables alone never select the queue
    assert Settings().job_runner == "inprocess"
    monkeypatch.setenv("DC_JOB_RUNNER", "queue")
    assert Settings().job_runner == "queue"
    monkeypatch.setenv("DC_JOB_RUNNER", "bogus")
    with pytest.raises(ValueError):
        Settings()


def test_start_only_queues_the_job_and_does_no_engine_work(client, queue, monkeypatch):
    calls = count_calls(monkeypatch, "profile")
    dataset_id, job_id = start_profile(client)
    assert queue.sent == [job_id] and calls == []
    assert job_state(client, job_id)["status"] == "queued"
    with Session(client.app.state.ctx.engine) as s:
        row = s.get(Job, job_id)
        assert dt.timedelta(seconds=200) < row.deadline_at - row.created_at <= dt.timedelta(seconds=600)


def test_consumer_runs_profile_then_clean_through_the_queue(client, queue):
    ctx = client.app.state.ctx
    dataset_id, job_id = start_profile(client)
    queue.deliver(ctx, job_id)
    assert job_state(client, job_id)["status"] == "done"
    proposals = client.get(f"/api/datasets/{dataset_id}/profile").json()["proposals"]
    r = client.post(f"/api/datasets/{dataset_id}/clean", json={"approved": [p["id"] for p in proposals]})
    clean_id = r.json()["job_id"]
    queue.deliver(ctx, clean_id)
    assert job_state(client, clean_id)["status"] == "done"
    assert client.get(f"/api/datasets/{dataset_id}/downloads/clean.csv").status_code == 200


def test_a_message_that_cannot_be_sent_fails_the_job_safely(client, queue):
    queue.fail_sends = True
    dataset_id = upload(client).json()["dataset_id"]
    job_id = client.post(f"/api/datasets/{dataset_id}/profile", json={}).json()["job_id"]
    job = job_state(client, job_id)
    assert job["status"] == "failed" and job["error"]["code"] == "internal_error"
    assert "secret" not in job["error"]["message"] and "http" not in job["error"]["message"]


# --------------------------------------------------------------------------- redelivery and superseding

def test_a_redelivery_after_done_does_nothing(client, queue, monkeypatch):
    calls = count_calls(monkeypatch, "profile")
    _, job_id = start_profile(client)
    ctx = client.app.state.ctx
    queue.deliver(ctx, job_id)
    queue.deliver(ctx, job_id)
    assert len(calls) == 1 and job_state(client, job_id)["status"] == "done"


def test_simultaneous_double_delivery_runs_the_engine_once(client, queue, monkeypatch):
    real = jobs.pipeline.profile

    def slow(*args, **kwargs):
        time.sleep(0.5)
        return real(*args, **kwargs)

    calls = count_calls(monkeypatch, "profile", slow)
    _, job_id = start_profile(client)
    ctx = client.app.state.ctx
    threads = [threading.Thread(target=worker.handle_message, args=(ctx, job_id)) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 1 and job_state(client, job_id)["status"] == "done"


def test_two_starts_for_one_dataset_only_the_newer_job_runs(client, queue, monkeypatch):
    calls = count_calls(monkeypatch, "profile")
    dataset_id = upload(client).json()["dataset_id"]
    first = client.post(f"/api/datasets/{dataset_id}/profile", json={}).json()["job_id"]
    second = client.post(f"/api/datasets/{dataset_id}/profile", json={}).json()["job_id"]
    ctx = client.app.state.ctx
    queue.deliver(ctx, first)
    assert calls == [] and job_state(client, first)["error"]["code"] == "superseded"
    queue.deliver(ctx, second)
    assert len(calls) == 1 and job_state(client, second)["status"] == "done"


def test_a_queued_job_whose_generation_moved_on_is_not_run(client, queue, monkeypatch):
    calls = count_calls(monkeypatch, "profile")
    dataset_id, job_id = start_profile(client)
    with Session(client.app.state.ctx.engine) as s:            # the dataset moved on without superseding this row
        s.execute(update(Dataset).where(Dataset.id == dataset_id).values(generation=Dataset.generation + 1))
        s.commit()
    queue.deliver(client.app.state.ctx, job_id)
    assert calls == [] and job_state(client, job_id)["status"] == "failed"


def test_a_message_for_an_unknown_job_is_acknowledged(client, queue):
    worker.handle_message(client.app.state.ctx, "00000000-0000-4000-8000-000000000000")


# --------------------------------------------------------------------------- deadline

def test_a_job_over_its_deadline_fails_with_job_timeout_and_is_not_redelivered(tmp_path, queue, monkeypatch):
    app = make_app(tmp_path, job_deadline_seconds=0.3)
    real = jobs.pipeline.profile

    def slow(*args, progress=None, **kwargs):
        for _ in range(20):
            time.sleep(0.1)
            progress(10, "Reading file")                    # the engine reports progress as it goes
        return real(*args, progress=progress, **kwargs)

    monkeypatch.setattr(jobs.pipeline, "profile", slow)
    with TestClient(app) as client:
        dataset_id, job_id = start_profile(client)
        started = time.monotonic()
        assert queue.deliver(app.state.ctx, job_id) == 1       # returns normally: one delivery only
        assert time.monotonic() - started < 1.5
        job = job_state(client, job_id)
        assert job["status"] == "failed"
        assert job["error"] == {"code": "job_timeout", "message": TIMEOUT_MESSAGE}
        time.sleep(0.3)                                        # the abandoned thread stops at its next progress report
        assert client.get(f"/api/datasets/{dataset_id}/profile").status_code == 409


# --------------------------------------------------------------------------- failures and retries

def crash(*args, **kwargs):
    raise RuntimeError("/srv/secret/path boom")


def test_an_engine_crash_is_retried_twice_by_attempts_then_fails(client, queue, monkeypatch):
    calls = count_calls(monkeypatch, "profile", crash)
    _, job_id = start_profile(client)
    assert queue.deliver(client.app.state.ctx, job_id) == 3
    assert len(calls) == 3
    job = job_state(client, job_id)
    assert job["status"] == "failed" and job["error"]["code"] == "internal_error"
    assert "secret" not in job["error"]["message"] and "/srv" not in job["error"]["message"]
    with Session(client.app.state.ctx.engine) as s:
        assert s.get(Job, job_id).attempts == 3


def test_a_crash_that_goes_away_on_retry_ends_done(client, queue, monkeypatch):
    real = jobs.pipeline.profile
    state = {"n": 0}

    def flaky(*args, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(jobs.pipeline, "profile", flaky)
    _, job_id = start_profile(client)
    assert queue.deliver(client.app.state.ctx, job_id) == 2
    assert job_state(client, job_id)["status"] == "done"


def test_a_job_waiting_for_a_retry_is_shown_as_queued_not_failed(client, queue, monkeypatch):
    count_calls(monkeypatch, "profile", crash)
    _, job_id = start_profile(client)
    with pytest.raises(RetryJob):
        worker.handle_message(client.app.state.ctx, job_id)
    assert job_state(client, job_id)["status"] == "queued"


def test_an_unreadable_file_is_not_retried(client, queue, monkeypatch):
    def unreadable(*args, **kwargs):
        raise IngestError("This file could not be read.")

    calls = count_calls(monkeypatch, "profile", unreadable)
    _, job_id = start_profile(client)
    assert queue.deliver(client.app.state.ctx, job_id) == 1 and len(calls) == 1
    assert job_state(client, job_id)["error"]["code"] == "unreadable_file"


def test_a_storage_error_fails_with_a_plain_message_and_is_not_retried(client, queue, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("https://blob.vercel-storage.com/x?token=secret")

    monkeypatch.setattr(client.app.state.ctx.storage, "get_file", broken)
    _, job_id = start_profile(client)
    assert queue.deliver(client.app.state.ctx, job_id) == 1
    job = job_state(client, job_id)
    assert job["status"] == "failed" and job["error"]["code"] == "storage_error"
    assert "secret" not in job["error"]["message"] and "http" not in job["error"]["message"]


def test_a_database_error_fails_with_a_plain_message_and_is_not_retried(client, queue, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def broken(*args, **kwargs):
        raise OperationalError("select secret", {}, Exception("password=hunter2"))

    monkeypatch.setattr(jobs, "save_if_current", broken)
    _, job_id = start_profile(client)
    assert queue.deliver(client.app.state.ctx, job_id) == 1
    job = job_state(client, job_id)
    assert job["status"] == "failed" and job["error"]["code"] == "database_error"
    assert "hunter2" not in job["error"]["message"] and "select" not in job["error"]["message"]


# --------------------------------------------------------------------------- stuck jobs

def _stuck(engine, status, seconds_ago=5) -> str:
    now = utcnow()
    job_id = str(uuid.uuid4())
    with Session(engine) as s:
        s.add(Job(id=job_id, dataset_id=str(uuid.uuid4()), type="profile", status=status, created_at=now, updated_at=now,
                  deadline_at=now - dt.timedelta(seconds=seconds_ago)))
        s.commit()
    return job_id


def _row(engine, job_id) -> Job:
    with Session(engine) as s:
        return s.get(Job, job_id)


def test_expire_stuck_jobs_fails_overdue_jobs_only(db_engine):
    running, queued = _stuck(db_engine, "running"), _stuck(db_engine, "queued")
    fresh, done = _stuck(db_engine, "running", seconds_ago=-60), _stuck(db_engine, "done")
    assert expire_stuck_jobs(db_engine) == 2
    assert (_row(db_engine, running).status, _row(db_engine, running).error_code) == ("failed", "job_timeout")
    assert (_row(db_engine, queued).status, _row(db_engine, queued).error_code) == ("failed", "expired")
    assert _row(db_engine, running).error_message == TIMEOUT_MESSAGE
    assert (_row(db_engine, fresh).status, _row(db_engine, done).status) == ("running", "done")
    assert expire_stuck_jobs(db_engine) == 0


def test_get_job_expires_a_stuck_job(client, queue):
    engine = client.app.state.ctx.engine
    job = job_state(client, _stuck(engine, "running"))
    assert job["status"] == "failed" and job["error"] == {"code": "job_timeout", "message": TIMEOUT_MESSAGE}
    assert job_state(client, _stuck(engine, "queued"))["error"]["code"] == "expired"   # a lost message


def test_the_lease_matches_the_deadline():
    s = Settings()
    assert s.job_deadline_seconds == 240 and 240 < s.job_lease_seconds <= 300


def test_worker_writes_are_counted_in_stored_bytes(tmp_path, queue, monkeypatch):
    """The queue consumer builds its own Context; its writes must reach the same byte counter as the routes'."""
    from backend.db import counter_get
    monkeypatch.setenv("DC_STORAGE_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("DC_STORAGE_BACKEND", "local")
    worker.get_ctx.cache_clear()
    app = create_app(Settings(storage_dir=tmp_path / "s", job_runner="queue"))
    try:
        with TestClient(app) as client:
            dataset_id, job_id = start_profile(client)
            ctx = worker.get_ctx()
            queue.deliver(ctx, job_id)
            clean_id = client.post(f"/api/datasets/{dataset_id}/clean", json={}).json()["job_id"]
            queue.deliver(ctx, clean_id)
            assert ctx.storage.size_under("") > 0
            assert counter_get(ctx.engine, "stored_bytes") == ctx.storage.size_under("")
    finally:
        worker.get_ctx.cache_clear()


# --------------------------------------------------------------------------- round 2: timed-out and retried clean jobs

def _profiled_through_queue(client, queue):
    dataset_id, job_id = start_profile(client)
    queue.deliver(client.app.state.ctx, job_id)
    proposals = client.get(f"/api/datasets/{dataset_id}/profile").json()["proposals"]
    return dataset_id, {"approved": [p["id"] for p in proposals]}


def test_a_timed_out_clean_can_never_publish_results(tmp_path, queue, monkeypatch):
    app = make_app(tmp_path)
    blob = app.state.ctx.storage.c
    real = jobs.pipeline.clean

    def slow_then_finish(*args, **kwargs):
        time.sleep(0.8)
        kwargs["progress"] = lambda *a: None             # never sees the cancel flag: the thread runs to the end
        return real(*args, **kwargs)

    with TestClient(app) as client:
        dataset_id, body = _profiled_through_queue(client, queue)
        clean_id = client.post(f"/api/datasets/{dataset_id}/clean", json=body).json()["job_id"]
        app.state.ctx.settings.job_deadline_seconds = 0.3     # tiny deadline for the clean only, not the profile
        monkeypatch.setattr(jobs.pipeline, "clean", slow_then_finish)
        queue.deliver(app.state.ctx, clean_id)
        assert job_state(client, clean_id)["error"]["code"] == "job_timeout"
        left = lambda: [k for k in blob.blobs if f"/runs/{clean_id}/" in k]
        deadline = time.monotonic() + 15                    # the abandoned thread finishes and cleans up meanwhile
        while left() and time.monotonic() < deadline:
            time.sleep(0.1)
        with Session(app.state.ctx.engine) as s:
            dataset = s.get(Dataset, dataset_id)
            assert dataset.results_json is None and dataset.results_run_id is None
        assert not left()
        assert job_state(client, clean_id)["error"]["code"] == "job_timeout"


def test_a_clean_crash_that_goes_away_on_retry_ends_done(client, queue, monkeypatch):
    dataset_id, body = _profiled_through_queue(client, queue)
    clean_id = client.post(f"/api/datasets/{dataset_id}/clean", json=body).json()["job_id"]
    real = jobs.pipeline.clean
    state = {"n": 0}

    def flaky(*args, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(jobs.pipeline, "clean", flaky)
    assert queue.deliver(client.app.state.ctx, clean_id) == 2
    assert job_state(client, clean_id)["status"] == "done"
