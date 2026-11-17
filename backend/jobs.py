"""Background jobs. These call engine.pipeline and nothing else from the engine's internals.

The engine works on local files only. Each job downloads what it needs from storage into a temp
folder, runs the engine there, uploads its outputs under its own prefix, and removes the folder.
"""

from __future__ import annotations

import datetime as dt
import logging
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, update
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from backend.config import Settings
from backend.db import (TIMEOUT_MESSAGE, Dataset, Job, acquire_lease, claim_job, release_lease, save_if_current,
                        utcnow)
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


class RetryJob(Exception):
    """The attempt crashed for a reason that is not the file's fault and attempts are left: the job is
    queued again and the consumer asks the queue to deliver the message once more."""


class JobCancelled(Exception):
    """Raised in the engine thread, at its next progress report, once the job passed its deadline."""


class DeadlineExceeded(Exception):
    pass


class StorageError(Exception):
    """Any failure of the storage backend (the original is chained, never shown to the user)."""


@contextmanager
def _storage_errors():
    try:
        yield
    except Exception as exc:
        raise StorageError(type(exc).__name__) from exc


def _progress(ctx: Context, job_id: str, cancel: threading.Event):
    last = {"pct": -1, "step": ""}

    def report(pct: int, step: str) -> None:
        if cancel.is_set():
            raise JobCancelled()
        pct = max(0, min(99, int(pct)))          # 100 is set only when the outputs are saved
        if pct == last["pct"] and step == last["step"]:
            return
        last.update(pct=pct, step=step)
        _update(ctx, job_id, progress_pct=pct, current_step=step)

    return report


SUPERSEDED = "A newer run was started for this file, so this result was not kept."


def _job(ctx: Context, job_id: str) -> Job:
    with Session(ctx.engine) as session:
        return session.get(Job, job_id)


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


def _with_deadline(work, generation: int, cancel: threading.Event, seconds: float) -> bool:
    """Run the synchronous engine in a worker thread so the deadline can be enforced. A Python thread
    cannot be killed: past the deadline it is told to stop (it raises JobCancelled at its next progress
    report and removes its own output) and is abandoned. On a serverless function it ends with the instance."""
    box: dict = {}

    def target() -> None:
        try:
            box["saved"] = work(generation, cancel)
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        cancel.set()
        raise DeadlineExceeded()
    if "error" in box:
        raise box["error"]
    return box["saved"]


def _fail(ctx: Context, job_id: str, code: str, message: str) -> None:
    try:
        _update(ctx, job_id, status="failed", error_code=code, error_message=message)
    except SQLAlchemyError:
        log.exception("job %s: could not record the failure; its deadline will expire it", job_id)


def _run(ctx: Context, job_id: str, work, retryable: bool = False) -> bool:
    """work(generation, cancel) computes the result and saves it with save_if_current; returns that bool.
    Returns False when the job was not claimed (a redelivery, or the job was replaced).
    retryable: an unexpected crash puts the job back to queued and raises RetryJob while attempts are left."""
    s = ctx.settings
    if not claim_job(ctx.engine, job_id, lease_seconds=s.job_lease_seconds, max_attempts=s.job_max_attempts):
        return False                            # a redelivery of a job that is running, finished or replaced
    try:
        saved = _with_deadline(work, _job(ctx, job_id).generation, threading.Event(), s.job_deadline_seconds)
    except IngestError as exc:
        _fail(ctx, job_id, "unreadable_file", exc.message)
    except EngineError as exc:
        _fail(ctx, job_id, "invalid_request", exc.message)
    except DeadlineExceeded:
        log.error("job %s passed its %s s deadline", job_id, s.job_deadline_seconds)
        _fail(ctx, job_id, "job_timeout", TIMEOUT_MESSAGE)
    except StorageError:
        log.exception("job %s: storage error", job_id)
        _fail(ctx, job_id, "storage_error", "The file store was not available. Please try again.")
    except SQLAlchemyError:
        log.exception("job %s: database error", job_id)
        _fail(ctx, job_id, "database_error", "The database was not available. Please try again.")
    except Exception:
        log.exception("job %s failed", job_id)
        if retryable and _job(ctx, job_id).attempts < s.job_max_attempts:
            _update(ctx, job_id, status="queued", progress_pct=0, current_step="Retrying",
                    deadline_at=utcnow() + dt.timedelta(seconds=s.job_queue_wait_seconds))
            raise RetryJob()
        _fail(ctx, job_id, "internal_error", "Something went wrong while processing the file.")
    else:
        try:
            if saved:
                _update(ctx, job_id, status="done", progress_pct=100, current_step="Done")
            else:
                _update(ctx, job_id, status="superseded", error_code="superseded", error_message=SUPERSEDED)
        except SQLAlchemyError:
            log.exception("job %s: could not record the result", job_id)
    return True


def _fetch_inputs(ctx: Context, dataset: Dataset, tmp: Path) -> tuple[Path, Path, set[str]]:
    """The original and the read-once cache, downloaded into tmp. Returns (original, cache_dir, cache files)."""
    original = tmp / f"original.{dataset.file_type}"
    ctx.storage.get_file(original_key(dataset.id, dataset.file_type), original)
    cache = tmp / "cache"
    ctx.storage.download_prefix(cache_prefix(dataset.id), cache)
    return original, cache, {p.name for p in cache.glob("*")}


def _read_or_none(ctx: Context, key: str) -> bytes | None:
    try:
        return ctx.storage.read_bytes(key)
    except StorageNotFound:
        return None


def run_profile_job(ctx: Context, job_id: str, dataset: Dataset, retryable: bool = False) -> None:
    def work(generation: int, cancel: threading.Event) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            with _storage_errors():
                original, cache, known = _fetch_inputs(ctx, dataset, Path(tmp))
            result = pipeline.profile(
                original,
                sheet=dataset.sheet,
                header_row=dataset.header_row,
                progress=_progress(ctx, job_id, cancel),
                display_name=dataset.filename,
                cache_dir=cache,      # read-once cache for the clean job (same cache key, so a copy is as good)
            )
            with _storage_errors():
                ctx.storage.upload_dir(cache, cache_prefix(dataset.id), skip=known)
        return save_if_current(ctx.engine, dataset.id, generation, job_id, profile_json=result.model_dump_json())

    _run(ctx, job_id, work, retryable)


def run_clean_job(ctx: Context, job_id: str, dataset: Dataset, plan: ApprovedPlan, retryable: bool = False) -> None:
    prefix = run_prefix(dataset.id, job_id)          # only this job writes under it

    def work(generation: int, cancel: threading.Event) -> bool:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with _storage_errors():
                    original, cache, _ = _fetch_inputs(ctx, dataset, Path(tmp))
                out_dir = Path(tmp) / "out"
                out_dir.mkdir()
                result = pipeline.clean(
                    original, plan, out_dir,
                    run_id=job_id,
                    progress=_progress(ctx, job_id, cancel),
                    display_name=dataset.filename,
                    cache_dir=cache,
                )
                if cancel.is_set():                  # timed out while finishing: publish nothing
                    raise JobCancelled()
                with _storage_errors():
                    ctx.storage.upload_dir(out_dir, prefix)
            saved = save_if_current(ctx.engine, dataset.id, generation, job_id,
                                    results_json=result.model_dump_json(), results_run_id=job_id)
        except BaseException as exc:
            # A crashed attempt that will be retried keeps plan.json: the redelivery reads it.
            plan_key = run_key(dataset.id, job_id, "plan.json")
            keep = None if isinstance(exc, JobCancelled) else _read_or_none(ctx, plan_key)
            ctx.storage.delete_prefix(prefix)
            if keep is not None:
                ctx.storage.put_bytes(plan_key, keep)
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

    if not _run(ctx, job_id, work, retryable):
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
    give_up = time.monotonic() + XLSX_LEASE_SECONDS      # one lease: the request ends well inside the 300 s function limit
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
