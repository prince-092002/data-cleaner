"""Step 12: job states, the idempotent claim and the Excel build lease (SQLite always, Postgres if configured)."""

import datetime as dt
import uuid

from sqlalchemy import update
from sqlmodel import Session

from backend.db import Job, acquire_lease, claim_job, mark_superseded, release_lease, utcnow


def _job(engine, status="queued", **fields) -> str:
    now = utcnow()
    job_id = str(uuid.uuid4())
    with Session(engine) as s:
        s.add(Job(id=job_id, dataset_id=str(uuid.uuid4()), type="profile", status=status,
                  created_at=now, updated_at=now, **fields))
        s.commit()
    return job_id


def _get(engine, job_id) -> Job:
    with Session(engine) as s:
        return s.get(Job, job_id)


def _overdue(engine, job_id):
    with Session(engine) as s:
        s.execute(update(Job).where(Job.id == job_id).values(deadline_at=utcnow() - dt.timedelta(seconds=1)))
        s.commit()


def test_first_delivery_claims_and_second_does_nothing(db_engine):
    job_id = _job(db_engine)
    assert claim_job(db_engine, job_id) is True
    job = _get(db_engine, job_id)
    assert (job.status, job.attempts) == ("running", 1) and job.started_at and job.deadline_at > utcnow()
    assert claim_job(db_engine, job_id) is False          # redelivery while running within its deadline
    assert _get(db_engine, job_id).attempts == 1


def test_finished_and_superseded_jobs_are_not_claimed(db_engine):
    done, old = _job(db_engine, status="done"), _job(db_engine, status="superseded")
    assert claim_job(db_engine, done) is False and claim_job(db_engine, old) is False
    assert (_get(db_engine, done).attempts, _get(db_engine, old).attempts) == (0, 0)


def test_a_running_job_past_its_deadline_is_claimed_again(db_engine):
    job_id = _job(db_engine)
    claim_job(db_engine, job_id)
    _overdue(db_engine, job_id)
    assert claim_job(db_engine, job_id) is True
    assert _get(db_engine, job_id).attempts == 2


def test_a_job_out_of_attempts_becomes_expired(db_engine):
    job_id = _job(db_engine)
    for _ in range(3):
        assert claim_job(db_engine, job_id, max_attempts=3) is True
        _overdue(db_engine, job_id)
    assert claim_job(db_engine, job_id, max_attempts=3) is False
    job = _get(db_engine, job_id)
    assert job.status == "expired" and job.error_code == "expired"


def test_a_new_job_supersedes_the_older_active_ones(db_engine):
    dataset_id = str(uuid.uuid4())
    now = utcnow()
    with Session(db_engine) as s:
        s.add(Job(id="old-q", dataset_id=dataset_id, type="clean", status="queued", created_at=now, updated_at=now))
        s.add(Job(id="old-done", dataset_id=dataset_id, type="clean", status="done", created_at=now, updated_at=now))
        s.commit()
        mark_superseded(s, dataset_id, keep_job_id="new")
        s.commit()
    assert _get(db_engine, "old-q").status == "superseded" and _get(db_engine, "old-q").error_code == "superseded"
    assert _get(db_engine, "old-done").status == "done"


def test_lease_is_held_by_one_caller_until_released_or_expired(db_engine):
    assert acquire_lease(db_engine, "xlsx:run1", "d1", seconds=60) is not None
    assert acquire_lease(db_engine, "xlsx:run1", "d1", seconds=60) is None
    assert acquire_lease(db_engine, "xlsx:run2", "d1", seconds=-1) is not None          # already expired
    assert acquire_lease(db_engine, "xlsx:run2", "d1", seconds=60) is not None          # so it can be taken over
    first = acquire_lease(db_engine, "xlsx:run3", "d1", seconds=60)
    release_lease(db_engine, "xlsx:run3", first)
    assert acquire_lease(db_engine, "xlsx:run3", "d1", seconds=60) is not None
