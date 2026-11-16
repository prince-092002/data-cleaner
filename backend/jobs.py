"""Background jobs. These call engine.pipeline and nothing else from the engine's internals.

The engine works on local files only. Each job downloads what it needs from storage into a temp
folder, runs the engine there, uploads its outputs under its own prefix, and removes the folder.
"""

from __future__ import annotations

import datetime as dt
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, update
from sqlmodel import Session, select

from backend.config import Settings
from backend.db import (Dataset, Job, acquire_lease, claim_job, release_lease, save_if_current, utcnow)
from backend.storage import (StorageBackend, StorageNotFound, cache_prefix, dataset_prefix, original_key, run_key,
                             run_prefix, runs_prefix)
from engine import pipeline
from engine.errors import EngineError, IngestError
from engine.models import ApprovedPlan

log = logging.getLogger("data_cleaner.jobs")


@dataclass
class Context:
    settings: Settings
    engine: Engine
    storage: StorageBackend


def _update(ctx: Context, job_id: str, **fields) -> None:
    """Change a job only while it is still running: a superseded or finished job is never touched."""
    with Session(ctx.engine) as session:
        session.execute(
            update(Job).where(Job.id == job_id, Job.status == "running").values(**fields, updated_at=utcnow())
        )
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
    """Clean jobs of this dataset that may still be writing their run folder: queued or running ones,
    and ones superseded within the job lease (a running job can be superseded and still be writing;
    it removes its own folder when it ends)."""
    recent = utcnow() - dt.timedelta(seconds=ctx.settings.job_lease_seconds)
    with Session(ctx.engine) as session:
        return set(session.exec(
            select(Job.id).where(Job.dataset_id == dataset_id, Job.type == "clean",
                                 Job.status.in_(["queued", "running"])
                                 | ((Job.status == "superseded") & (Job.updated_at > recent)))
        ).all())


def _run(ctx: Context, job_id: str, work) -> bool:
    """work(generation) computes the result and saves it with save_if_current; returns that bool.
    Returns False when the job was not claimed (a redelivery, or the job was replaced)."""
    s = ctx.settings
    if not claim_job(ctx.engine, job_id, lease_seconds=s.job_lease_seconds, max_attempts=s.job_max_attempts):
        return False                            # a redelivery of a job that is running, finished or replaced
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
            _update(ctx, job_id, status="superseded", error_code="superseded", error_message=SUPERSEDED)
    return True


def _fetch_inputs(ctx: Context, dataset: Dataset, tmp: Path) -> tuple[Path, Path, set[str]]:
    """The original and the read-once cache, downloaded into tmp. Returns (original, cache_dir, cache files)."""
    original = tmp / f"original.{dataset.file_type}"
    ctx.storage.get_file(original_key(dataset.id, dataset.file_type), original)
    cache = tmp / "cache"
    ctx.storage.download_prefix(cache_prefix(dataset.id), cache)
    return original, cache, {p.name for p in cache.glob("*")}


def run_profile_job(ctx: Context, job_id: str, dataset: Dataset) -> None:
    def work(generation: int) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            original, cache, known = _fetch_inputs(ctx, dataset, Path(tmp))
            result = pipeline.profile(
                original,
                sheet=dataset.sheet,
                header_row=dataset.header_row,
                progress=_progress(ctx, job_id),
                display_name=dataset.filename,
                cache_dir=cache,      # read-once cache for the clean job (same cache key, so a copy is as good)
            )
            ctx.storage.upload_dir(cache, cache_prefix(dataset.id), skip=known)
        return save_if_current(ctx.engine, dataset.id, generation, profile_json=result.model_dump_json())

    _run(ctx, job_id, work)


def run_clean_job(ctx: Context, job_id: str, dataset: Dataset, plan: ApprovedPlan) -> None:
    prefix = run_prefix(dataset.id, job_id)          # only this job writes under it

    def work(generation: int) -> bool:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                original, cache, _ = _fetch_inputs(ctx, dataset, Path(tmp))
                out_dir = Path(tmp) / "out"
                out_dir.mkdir()
                result = pipeline.clean(
                    original, plan, out_dir,
                    run_id=job_id,
                    progress=_progress(ctx, job_id),
                    display_name=dataset.filename,
                    cache_dir=cache,
                )
                ctx.storage.upload_dir(out_dir, prefix)
            saved = save_if_current(ctx.engine, dataset.id, generation,
                                    results_json=result.model_dump_json(), results_run_id=job_id)
        except BaseException:
            ctx.storage.delete_prefix(prefix)
            raise
        if saved:
            # Never delete a folder another clean job may still be writing; it removes its own.
            keep = {job_id} | _active_clean_runs(ctx, dataset.id)
            existing = {k[len(runs_prefix(dataset.id)):].split("/")[0] for k, _ in ctx.storage.list_keys(runs_prefix(dataset.id))}
            for run in existing - keep:
                ctx.storage.delete_prefix(run_prefix(dataset.id, run))
        else:
            ctx.storage.delete_prefix(prefix)
        return saved

    if not _run(ctx, job_id, work):
        with Session(ctx.engine) as session:
            job = session.get(Job, job_id)
        if job is not None and job.status == "superseded":        # replaced before it started: nothing to keep
            ctx.storage.delete_prefix(prefix)


# --------------------------------------------------------------------------- Excel on download

XLSX_LEASE_SECONDS = 120


def ensure_xlsx(ctx: Context, dataset: Dataset) -> None:
    """Make sure clean.xlsx exists for the dataset's current run, built once even when several
    requests (on any server instance) ask at the same moment: a database lease decides who builds,
    the others wait for the file. Raises StorageNotFound when the run or the dataset is gone."""
    run_id = dataset.results_run_id
    target, csv_key = (run_key(dataset.id, run_id, n) for n in ("clean.xlsx", "clean.csv"))
    lease = f"xlsx:{run_id}"
    give_up = time.monotonic() + 3 * XLSX_LEASE_SECONDS
    while True:
        if ctx.storage.exists(target):
            return
        if not ctx.storage.exists(csv_key):
            raise StorageNotFound(csv_key)
        holder = acquire_lease(ctx.engine, lease, dataset.id, XLSX_LEASE_SECONDS)
        if holder:
            try:
                if not ctx.storage.exists(target):               # another instance may have just finished
                    _build_xlsx(ctx, dataset, run_id)
            finally:
                release_lease(ctx.engine, lease, holder)
            return
        if time.monotonic() > give_up:
            raise TimeoutError("waited too long for another request to build clean.xlsx")
        time.sleep(0.2)


def _build_xlsx(ctx: Context, dataset: Dataset, run_id: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for name in ("clean.csv", "xlsx_spec.json"):
            ctx.storage.get_file(run_key(dataset.id, run_id, name), out / name)
        built = pipeline.build_xlsx(out)
        ctx.storage.put_file(run_key(dataset.id, run_id, "clean.xlsx"), built)
    with Session(ctx.engine) as session:
        alive = session.get(Dataset, dataset.id) is not None
    if not alive:                       # deleted while the build ran: leave nothing behind
        ctx.storage.delete_prefix(dataset_prefix(dataset.id))
        raise StorageNotFound(dataset.id)
