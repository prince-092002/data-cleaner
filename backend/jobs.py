"""Background jobs. These call engine.pipeline and nothing else from the engine's internals."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlmodel import Session

from backend.config import Settings
from backend.db import Dataset, Job, utcnow
from backend.storage import Storage
from engine import pipeline
from engine.errors import EngineError, IngestError
from engine.models import ApprovedPlan

log = logging.getLogger("data_cleaner.jobs")


@dataclass
class Context:
    settings: Settings
    engine: Engine
    storage: Storage


def _update(ctx: Context, job_id: str, **fields) -> None:
    with Session(ctx.engine) as session:
        job = session.get(Job, job_id)
        if job is None:                 # dataset was deleted while the job ran
            return
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = utcnow()
        session.add(job)
        session.commit()


def _progress(ctx: Context, job_id: str):
    last = {"pct": -1, "step": ""}

    def report(pct: int, step: str) -> None:
        pct = max(0, min(99, int(pct)))          # 100 is set only when the outputs are saved
        if pct == last["pct"] and step == last["step"]:
            return
        last.update(pct=pct, step=step)
        _update(ctx, job_id, progress_pct=pct, current_step=step)

    return report


def _run(ctx: Context, job_id: str, work) -> None:
    _update(ctx, job_id, status="running", current_step="Starting")
    try:
        work()
    except IngestError as exc:
        _update(ctx, job_id, status="failed", error_code="unreadable_file", error_message=exc.message)
    except EngineError as exc:
        _update(ctx, job_id, status="failed", error_code="invalid_request", error_message=exc.message)
    except Exception:
        log.exception("job %s failed", job_id)
        _update(ctx, job_id, status="failed", error_code="internal_error",
                error_message="Something went wrong while processing the file.")
    else:
        _update(ctx, job_id, status="done", progress_pct=100, current_step="Done")


def run_profile_job(ctx: Context, job_id: str, dataset: Dataset) -> None:
    def work() -> None:
        result = pipeline.profile(
            ctx.storage.original(dataset.id, dataset.file_type),
            sheet=dataset.sheet,
            header_row=dataset.header_row,
            progress=_progress(ctx, job_id),
            display_name=dataset.filename,
        )
        target = ctx.storage.file(dataset.id, "profile.json")
        target.write_text(result.model_dump_json(), encoding="utf-8")

    _run(ctx, job_id, work)


def run_clean_job(ctx: Context, job_id: str, dataset: Dataset, plan: ApprovedPlan) -> None:
    def work() -> None:
        result = pipeline.clean(
            ctx.storage.original(dataset.id, dataset.file_type),
            plan,
            ctx.storage.dataset_dir(dataset.id),
            run_id=job_id,
            progress=_progress(ctx, job_id),
            display_name=dataset.filename,
        )
        target = ctx.storage.file(dataset.id, "results.json")
        target.write_text(result.model_dump_json(), encoding="utf-8")

    _run(ctx, job_id, work)
