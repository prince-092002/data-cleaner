"""Background jobs. These call engine.pipeline and nothing else from the engine's internals."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlmodel import Session, select

from backend.config import Settings
from backend.db import Dataset, Job, save_if_current, utcnow
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


SUPERSEDED = "A newer run was started for this file, so this result was not kept."


def _generation(ctx: Context, job_id: str) -> int:
    with Session(ctx.engine) as session:
        return session.get(Job, job_id).generation


def _active_clean_runs(ctx: Context, dataset_id: str) -> set[str]:
    """Clean jobs of this dataset that may still be writing their run folder."""
    with Session(ctx.engine) as session:
        return set(session.exec(
            select(Job.id).where(Job.dataset_id == dataset_id, Job.type == "clean",
                                 Job.status.in_(["queued", "running"]))
        ).all())


def _run(ctx: Context, job_id: str, work) -> None:
    """work(generation) computes the result and saves it with save_if_current; returns that bool."""
    _update(ctx, job_id, status="running", current_step="Starting")
    try:
        saved = work(_generation(ctx, job_id))
    except IngestError as exc:
        _update(ctx, job_id, status="failed", error_code="unreadable_file", error_message=exc.message)
    except EngineError as exc:
        _update(ctx, job_id, status="failed", error_code="invalid_request", error_message=exc.message)
    except Exception:
        log.exception("job %s failed", job_id)
        _update(ctx, job_id, status="failed", error_code="internal_error",
                error_message="Something went wrong while processing the file.")
    else:
        if saved:
            _update(ctx, job_id, status="done", progress_pct=100, current_step="Done")
        else:
            _update(ctx, job_id, status="failed", error_code="superseded", error_message=SUPERSEDED)


def run_profile_job(ctx: Context, job_id: str, dataset: Dataset) -> None:
    def work(generation: int) -> bool:
        result = pipeline.profile(
            ctx.storage.original(dataset.id, dataset.file_type),
            sheet=dataset.sheet,
            header_row=dataset.header_row,
            progress=_progress(ctx, job_id),
            display_name=dataset.filename,
        )
        return save_if_current(ctx.engine, dataset.id, generation, profile_json=result.model_dump_json())

    _run(ctx, job_id, work)


def run_clean_job(ctx: Context, job_id: str, dataset: Dataset, plan: ApprovedPlan) -> None:
    out_dir = ctx.storage.run_dir(dataset.id, job_id)

    def work(generation: int) -> bool:
        try:
            result = pipeline.clean(
                ctx.storage.original(dataset.id, dataset.file_type),
                plan,
                out_dir,
                run_id=job_id,
                progress=_progress(ctx, job_id),
                display_name=dataset.filename,
            )
            saved = save_if_current(ctx.engine, dataset.id, generation,
                                    results_json=result.model_dump_json(), results_run_id=job_id)
        except BaseException:
            shutil.rmtree(out_dir, ignore_errors=True)
            raise
        if saved:
            # Never delete a folder another clean job may still be writing; it removes its own.
            ctx.storage.delete_runs_except(dataset.id, keep={job_id} | _active_clean_runs(ctx, dataset.id))
        else:
            shutil.rmtree(out_dir, ignore_errors=True)
        return saved

    _run(ctx, job_id, work)
