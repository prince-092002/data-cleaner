"""SQLite tables (SQLModel): datasets and jobs. See CONTRACT.md section 8.8."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import logging

from sqlalchemy import Engine, inspect, update
from sqlmodel import Field, Session, SQLModel, create_engine, select

log = logging.getLogger("data_cleaner.db")


def utcnow() -> dt.datetime:
    """Timezone-aware UTC, to the second."""
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(value: dt.datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(dt.timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class Dataset(SQLModel, table=True):
    id: str = Field(primary_key=True)
    filename: str                      # as uploaded; for display and download names only, never a path
    file_type: str                     # csv | xlsx
    size_bytes: int
    sheet: str | None = None
    header_row: int | None = None
    created_at: dt.datetime
    expires_at: dt.datetime
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
    status: str = "queued"             # queued | running | done | failed
    progress_pct: int = 0
    current_step: str = "Queued"
    error_code: str | None = None
    error_message: str | None = None
    generation: int = 0                # the dataset generation this job belongs to
    created_at: dt.datetime
    updated_at: dt.datetime


def make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False})
    tables = inspect(engine)
    if tables.has_table("dataset") and "generation" not in {c["name"] for c in tables.get_columns("dataset")}:
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
