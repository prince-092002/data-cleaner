"""Tables (SQLModel) on SQLite (default) or Postgres (DATABASE_URL): datasets, jobs, leases.
See CONTRACT.md section 8.8."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import logging

from sqlalchemy import DateTime, Engine, TypeDecorator, case, exists, inspect, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Column, Field, Session, SQLModel, create_engine, delete, select

log = logging.getLogger("data_cleaner.db")


def utcnow() -> dt.datetime:
    """Timezone-aware UTC, to the second."""
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(value: dt.datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(dt.timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class UTCDateTime(TypeDecorator):
    """Stored as UTC without a zone and always read back timezone-aware, the same on SQLite and Postgres."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None) if value is not None else None

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=dt.timezone.utc) if value is not None else None


def _time(nullable: bool = False):
    return Column(UTCDateTime(), nullable=nullable)


class Dataset(SQLModel, table=True):
    id: str = Field(primary_key=True)
    filename: str                      # as uploaded; for display and download names only, never a path
    file_type: str                     # csv | xlsx
    size_bytes: int
    sheet: str | None = None
    header_row: int | None = None
    created_at: dt.datetime = Field(sa_column=_time())
    expires_at: dt.datetime = Field(sa_column=_time())
    # Bumped by every new profile or clean job. A job saves its result only if the generation it
    # started with is still current, so an old job can never overwrite a newer one.
    generation: int = 0
    profile_json: str | None = None    # DatasetProfile of the current generation
    results_json: str | None = None    # CleanResult of the current generation
    results_run_id: str | None = None  # clean job whose output folder holds the downloads


class Job(SQLModel, table=True):
    id: str = Field(primary_key=True)
    dataset_id: str = Field(index=True)
    type: str                          # profile | clean
    # queued | running | done | failed | superseded | expired (the API shows the last two as "failed")
    status: str = "queued"
    progress_pct: int = 0
    current_step: str = "Queued"
    error_code: str | None = None
    error_message: str | None = None
    generation: int = 0                # the dataset generation this job belongs to
    attempts: int = 0                  # claims so far (a queue may deliver a message more than once)
    started_at: dt.datetime | None = Field(default=None, sa_column=_time(True))
    deadline_at: dt.datetime | None = Field(default=None, sa_column=_time(True))   # running past this may be claimed again
    created_at: dt.datetime = Field(sa_column=_time())
    updated_at: dt.datetime = Field(sa_column=_time())


class Lease(SQLModel, table=True):
    """A short-lived lock shared by every server instance, for example one Excel build per run."""

    key: str = Field(primary_key=True)
    dataset_id: str = Field(index=True)
    holder: str
    expires_at: dt.datetime = Field(sa_column=_time())


class Counter(SQLModel, table=True):
    """Shared counters: "stored_bytes", "jobs:<UTC date>", "ip:<UTC date>:<hash>". See backend/limits.py."""

    key: str = Field(primary_key=True)
    n: int = 0


ACTIVE = ("queued", "running")


def normalize_url(url: str) -> str:
    """Neon and Vercel give postgres:// or postgresql://; SQLAlchemy needs the psycopg 3 driver name."""
    for scheme in ("postgres://", "postgresql://"):
        if url.startswith(scheme):
            return "postgresql+psycopg://" + url[len(scheme):]
    return url


def make_engine(target: Path | str) -> Engine:
    """A file path gives SQLite; a postgres URL gives Postgres (DATABASE_URL)."""
    if isinstance(target, Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{target.as_posix()}", connect_args={"check_same_thread": False})
    else:
        # prepare_threshold=None: Neon's pooled URL goes through PgBouncer, which cannot keep prepared statements.
        engine = create_engine(normalize_url(target), connect_args={"prepare_threshold": None}, pool_pre_ping=True)
    tables = inspect(engine)
    if tables.has_table("job") and "attempts" not in {c["name"] for c in tables.get_columns("job")}:
        # Pre-M6 database. Its data lives at most 24 hours, so it is rebuilt rather than migrated.
        log.warning("old database layout found; recreating tables")
        SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    return engine


def start_generation(session: Session, dataset_id: str, *, clear_profile: bool) -> int:
    """Begin a new generation: clears results (and the profile for a new profile job)."""
    values = {"generation": Dataset.generation + 1, "results_json": None, "results_run_id": None}
    if clear_profile:
        values["profile_json"] = None
    session.execute(update(Dataset).where(Dataset.id == dataset_id).values(**values))
    return session.execute(select(Dataset.generation).where(Dataset.id == dataset_id)).scalar_one()


def save_if_current(engine: Engine, dataset_id: str, generation: int, job_id: str | None = None, **values) -> bool:
    """One guarded UPDATE: writes only while the dataset is still at this generation and, when job_id is
    given, that job is still running (a timed-out or replaced job can never publish)."""
    with Session(engine) as session:
        guard = [Dataset.id == dataset_id, Dataset.generation == generation]
        if job_id is not None:
            guard.append(exists().where(Job.id == job_id, Job.status == "running"))
        result = session.execute(update(Dataset).where(*guard).values(**values))
        session.commit()
        return result.rowcount == 1


def mark_superseded(session: Session, dataset_id: str, keep_job_id: str) -> None:
    """A new profile or clean replaces older jobs of the dataset that have not finished."""
    session.execute(
        update(Job)
        .where(Job.dataset_id == dataset_id, Job.id != keep_job_id, Job.status.in_(ACTIVE))
        .values(status="superseded", error_code="superseded", updated_at=utcnow(),
                error_message="A newer run was started for this file, so this result was not kept.")
    )


def claim_job(engine: Engine, job_id: str, *, lease_seconds: int = 270, max_attempts: int = 3) -> bool:
    """Idempotent and safe across processes: ONE conditional UPDATE decides who runs the job.

    Claimable: queued, or running with its deadline passed (the earlier worker died). A job that is
    running within its deadline, finished, superseded or expired is left alone (returns False). A job
    past its deadline with no attempts left becomes expired.
    """
    now = utcnow()
    with Session(engine) as session:
        claimed = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.attempts < max_attempts,
                   (Job.status == "queued") | ((Job.status == "running") & (Job.deadline_at <= now)))
            .values(status="running", attempts=Job.attempts + 1, started_at=now, updated_at=now,
                    deadline_at=now + dt.timedelta(seconds=lease_seconds), current_step="Starting")
        ).rowcount == 1
        if not claimed:
            session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running", Job.deadline_at <= now, Job.attempts >= max_attempts)
                .values(status="expired", error_code="expired", updated_at=now,
                        error_message="This job ran out of time. Please try again.")
            )
        session.commit()
        return claimed


TIMEOUT_MESSAGE = "This file took too long to process. Try a smaller file."


def fail_job(engine: Engine, job_id: str, code: str, message: str) -> None:
    """End a queued or running job as failed (a job that already ended is left alone)."""
    with Session(engine) as session:
        session.execute(update(Job).where(Job.id == job_id, Job.status.in_(ACTIVE))
                        .values(status="failed", error_code=code, error_message=message, updated_at=utcnow()))
        session.commit()


def expire_stuck_jobs(engine: Engine) -> int:
    """Fail every queued or running job past its deadline; returns how many changed. Two conditional
    UPDATEs, so it is safe to call from any instance at any time (GET /api/jobs and the cron route).
    A running job past its deadline lost its worker (out of memory, timeout): job_timeout. A queued one
    lost its message: expired."""
    now, changed = utcnow(), 0
    with Session(engine) as session:
        for status, code in (("running", "job_timeout"), ("queued", "expired")):
            changed += session.execute(
                update(Job).where(Job.status == status, Job.deadline_at <= now)
                .values(status="failed", error_code=code, error_message=TIMEOUT_MESSAGE, updated_at=now)
            ).rowcount
        session.commit()
    return changed


def acquire_lease(engine: Engine, key: str, dataset_id: str, seconds: int = 120) -> str | None:
    """Take the lock `key` (returns a holder token), or None if another caller holds it unexpired."""
    holder, now = uuid.uuid4().hex, utcnow()
    expires = now + dt.timedelta(seconds=seconds)
    with Session(engine) as session:
        try:
            session.add(Lease(key=key, dataset_id=dataset_id, holder=holder, expires_at=expires))
            session.commit()
            return holder
        except IntegrityError:
            session.rollback()
        taken = session.execute(
            update(Lease).where(Lease.key == key, Lease.expires_at <= now)
            .values(holder=holder, expires_at=expires)
        ).rowcount == 1
        session.commit()
        return holder if taken else None


def release_lease(engine: Engine, key: str, holder: str) -> None:
    with Session(engine) as session:
        session.execute(delete(Lease).where(Lease.key == key, Lease.holder == holder))
        session.commit()


def fail_interrupted_jobs(engine: Engine) -> int:
    """Jobs left queued or running by a previous server process can never finish."""
    with Session(engine) as session:
        stuck = session.exec(select(Job).where(Job.status.in_(["queued", "running"]))).all()
        for job in stuck:
            job.status = "failed"
            job.error_code = "interrupted"
            job.error_message = "The server restarted while this job was running. Please try again."
            job.updated_at = utcnow()
            session.add(job)
        session.commit()
        return len(stuck)


def counter_add(engine: Engine, key: str, delta: int = 1, cap: int | None = None) -> bool:
    """Atomically add delta to a counter (created on first use, never below 0). With a cap the add
    happens only if the result stays within it (one conditional UPDATE, or an INSERT for a new key),
    so concurrent instances cannot overshoot. Returns False when the cap refused it."""
    new = case((Counter.n + delta < 0, 0), else_=Counter.n + delta)
    guard = [Counter.key == key] + ([Counter.n + delta <= cap] if cap is not None else [])
    with Session(engine) as session:
        for _ in range(2):          # the second pass covers an INSERT that lost a race
            if session.execute(update(Counter).where(*guard).values(n=new)).rowcount == 1:
                session.commit()
                return True
            if cap is not None and delta > cap:
                return False
            try:
                session.add(Counter(key=key, n=max(delta, 0)))
                session.commit()
                return True
            except IntegrityError:
                session.rollback()
        return False


def counter_set(engine: Engine, key: str, n: int) -> None:
    with Session(engine) as session:
        if session.execute(update(Counter).where(Counter.key == key).values(n=n)).rowcount == 0:
            try:
                session.add(Counter(key=key, n=n))
            except IntegrityError:
                pass
        session.commit()


def counter_get(engine: Engine, key: str) -> int:
    with Session(engine) as session:
        row = session.get(Counter, key)
        return row.n if row else 0
