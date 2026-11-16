"""Tables (SQLModel) on SQLite (default) or Postgres (DATABASE_URL): datasets, jobs, leases.
See CONTRACT.md section 8.8."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import logging

from sqlalchemy import DateTime, Engine, TypeDecorator, inspect, update
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


def save_if_current(engine: Engine, dataset_id: str, generation: int, **values) -> bool:
    """One guarded UPDATE: writes only while the dataset is still at this generation."""
    with Session(engine) as session:
        result = session.execute(
            update(Dataset)
            .where(Dataset.id == dataset_id, Dataset.generation == generation)
            .values(**values)
        )
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


def claim_job(engine: Engine, job_id: str, *, lease_seconds: int = 900, max_attempts: int = 3) -> bool:
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
