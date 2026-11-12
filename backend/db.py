"""SQLite tables (SQLModel): datasets and jobs. See CONTRACT.md section 8.8."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Field, Session, SQLModel, create_engine, select


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


class Job(SQLModel, table=True):
    id: str = Field(primary_key=True)
    dataset_id: str = Field(index=True)
    type: str                          # profile | clean
    status: str = "queued"             # queued | running | done | failed
    progress_pct: int = 0
    current_step: str = "Queued"
    error_code: str | None = None
    error_message: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


def make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


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
