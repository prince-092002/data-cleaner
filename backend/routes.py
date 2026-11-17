"""HTTP routes. See CONTRACT.md section 8. No cleaning logic lives here."""

from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import os
import tempfile
import urllib.parse
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from backend import errors, runner
from backend.db import Dataset, Job, expire_stuck_jobs, iso, mark_superseded, start_generation, utcnow
from backend.limits import check_storage_room, count_job, count_upload
from backend.jobs import Context, ensure_xlsx, run_clean_job, run_profile_job
from backend.storage import (DOWNLOADS, StorageNotFound, TooLarge, file_key, is_uuid, looks_like, original_key,
                             run_key, runs_prefix, write_limited)
from engine import pipeline
from engine.errors import IngestError, PlanError
from engine.models import DatasetProfile, Decisions

router = APIRouter(prefix="/api")
log = logging.getLogger("data_cleaner.routes")

ALLOWED = {".csv": "csv", ".xlsx": "xlsx"}
# Job states the website does not know (CONTRACT 8.8) are shown as failed, with their own error code.
API_STATUS = {"superseded": "failed", "expired": "failed"}
CHANGE_FILTERS = ("rule_id", "column", "action", "change_type")


class ProfileRequest(BaseModel):
    sheet: str | None = None
    header_row: int | None = None


def _ctx(request: Request) -> Context:
    return request.app.state.ctx


def _display_name(raw: str | None) -> str:
    """Base name only, whatever the client's operating system. Used for display, never as a path."""
    name = PureWindowsPath(PurePosixPath(raw or "").name).name.strip()
    return name[:200] or "upload"


def _dataset(ctx: Context, dataset_id: str) -> Dataset:
    if is_uuid(dataset_id):
        with Session(ctx.engine) as session:
            dataset = session.get(Dataset, dataset_id)
            if dataset is not None and dataset.expires_at > utcnow():
                session.expunge(dataset)
                return dataset
    raise errors.not_found("This dataset")


def _new_job(ctx: Context, dataset_id: str, job_type: str) -> str:
    """Start a new generation of the dataset and a job that belongs to it, in one transaction."""
    now = utcnow()
    job_id = str(uuid.uuid4())
    with Session(ctx.engine) as session:
        generation = start_generation(session, dataset_id, clear_profile=job_type == "profile")
        mark_superseded(session, dataset_id, keep_job_id=job_id)
        # A queued job needs a deadline too, so a lost message cannot leave it queued forever.
        session.add(Job(id=job_id, dataset_id=dataset_id, type=job_type, generation=generation, created_at=now,
                        updated_at=now, deadline_at=now + dt.timedelta(seconds=ctx.settings.job_queue_wait_seconds)))
        session.commit()
    return job_id


# --------------------------------------------------------------------------- upload

@router.post("/datasets", status_code=201)
def upload_dataset(request: Request, file: UploadFile):
    ctx = _ctx(request)
    check_storage_room(ctx)
    filename = _display_name(file.filename)
    file_type = ALLOWED.get(Path(filename).suffix.lower())
    if file_type is None:
        raise errors.ApiError(415, "unsupported_file_type", "Only .csv and .xlsx files are supported.")

    dataset_id = str(uuid.uuid4())
    limit = ctx.settings.max_upload_bytes
    # The upload is checked on a local temp file first; storage only ever receives a file that passed.
    with tempfile.TemporaryDirectory() as tmp:
        original = Path(tmp) / f"original.{file_type}"
        try:
            size = write_limited(file.file, original, limit)
        except TooLarge:
            raise errors.ApiError(413, "file_too_large", f"Files must be {limit / (1024 * 1024):g} MB or smaller.")
        if size == 0:
            raise errors.ApiError(422, "unreadable_file", "The file is empty.")
        if not looks_like(original, file_type):
            raise errors.ApiError(
                415, "unsupported_file_type",
                f"This file does not look like a real .{file_type} file.",
            )
        try:
            inspection = pipeline.inspect(original)
        except IngestError as exc:
            raise errors.ApiError(422, "unreadable_file", exc.message)
        count_upload(ctx, request)       # after every check, so a rejected upload spends no slot
        ctx.storage.put_file(original_key(dataset_id, file_type), original)
    ctx.storage.put_bytes(file_key(dataset_id, "inspection.json"), inspection.model_dump_json().encode("utf-8"))
    now = utcnow()
    dataset = Dataset(
        id=dataset_id, filename=filename, file_type=file_type, size_bytes=size,
        created_at=now, expires_at=now + dt.timedelta(hours=ctx.settings.ttl_hours),
    )
    with Session(ctx.engine) as session:
        session.add(dataset)
        session.commit()
        expires_at = iso(dataset.expires_at)
    return {
        "dataset_id": dataset_id,
        "filename": filename,
        "file_type": file_type,
        "size_bytes": size,
        "expires_at": expires_at,
        "sheets": [s.model_dump() for s in inspection.sheets],
    }


# --------------------------------------------------------------------------- profile

@router.post("/datasets/{dataset_id}/profile", status_code=202)
def start_profile(
    request: Request,
    dataset_id: str,
    background: BackgroundTasks,
    body: ProfileRequest | None = Body(default=None),
):
    ctx = _ctx(request)
    dataset = _dataset(ctx, dataset_id)
    body = body or ProfileRequest()
    try:
        sheets = json.loads(ctx.storage.read_bytes(file_key(dataset_id, "inspection.json")))["sheets"]
    except StorageNotFound:
        raise errors.not_found("This dataset")
    by_name = {s["name"]: s for s in sheets}
    if dataset.file_type == "csv":
        if body.sheet is not None:
            raise errors.invalid_request("CSV files do not have sheets.")
        sheet = sheets[0]
    else:
        if body.sheet is not None and body.sheet not in by_name:
            raise errors.invalid_request(f'Sheet "{body.sheet}" was not found in this file.')
        sheet = by_name[body.sheet] if body.sheet is not None else sheets[0]
    header_row = body.header_row if body.header_row is not None else sheet["detected_header_row"]
    if header_row < 0 or header_row >= max(sheet["row_count_estimate"], 1):
        raise errors.invalid_request("The header row is outside the file.")

    count_job(ctx, request)       # first: a refused request must not change the dataset
    with Session(ctx.engine) as session:
        row = session.get(Dataset, dataset_id)
        row.sheet, row.header_row = sheet["name"], header_row
        session.add(row)
        session.commit()
    dataset.sheet, dataset.header_row = sheet["name"], header_row

    # A new profile replaces the old one and anything cleaned from it (a new generation).
    job_id = _new_job(ctx, dataset_id, "profile")
    ctx.storage.delete_prefix(runs_prefix(dataset_id))      # the old results are gone now, not at 24 h
    if ctx.settings.job_runner == "queue":
        runner.enqueue(ctx, job_id)
    else:
        background.add_task(run_profile_job, ctx, job_id, dataset)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str):
    ctx = _ctx(request)
    expire_stuck_jobs(ctx.engine, job_id)    # a job past its deadline lost its worker: fail it now, never poll forever
    with Session(ctx.engine) as session:
        job = session.get(Job, job_id) if is_uuid(job_id) else None
        if job is None:
            raise errors.not_found("This job")
        return {
            "job_id": job.id,
            "dataset_id": job.dataset_id,
            "type": job.type,
            "status": API_STATUS.get(job.status, job.status),
            "progress_pct": job.progress_pct,
            "current_step": job.current_step,
            "error": {"code": job.error_code, "message": job.error_message}
            if API_STATUS.get(job.status, job.status) == "failed" else None,
            "created_at": iso(job.created_at),
            "updated_at": iso(job.updated_at),
        }


@router.get("/datasets/{dataset_id}/profile")
def get_profile(request: Request, dataset_id: str):
    ctx = _ctx(request)
    dataset = _dataset(ctx, dataset_id)
    if dataset.profile_json is None:
        raise errors.not_ready("The profile is not ready yet. Start a profile job and wait for it to finish.")
    return {"dataset_id": dataset_id, **json.loads(dataset.profile_json)}


# --------------------------------------------------------------------------- clean

@router.post("/datasets/{dataset_id}/clean", status_code=202)
def start_clean(request: Request, dataset_id: str, decisions: Decisions, background: BackgroundTasks):
    ctx = _ctx(request)
    dataset = _dataset(ctx, dataset_id)
    if dataset.profile_json is None:
        raise errors.not_ready("Profile the file before cleaning it.")
    profile = DatasetProfile.model_validate_json(dataset.profile_json)
    try:
        plan = pipeline.build_plan(profile, decisions)
    except PlanError as exc:
        raise errors.invalid_request(exc.message)

    count_job(ctx, request)
    job_id = _new_job(ctx, dataset_id, "clean")
    ctx.storage.put_bytes(run_key(dataset_id, job_id, "plan.json"), plan.model_dump_json().encode("utf-8"))
    if ctx.settings.job_runner == "queue":
        runner.enqueue(ctx, job_id)
    else:
        background.add_task(run_clean_job, ctx, job_id, dataset, plan)
    return {"job_id": job_id}


_CHANGELOG_CACHE_FILES = 20


def _changelog_path(ctx: Context, dataset: Dataset) -> Path:
    """The run's change log in the instance temp folder: downloaded once, reused by every page and
    filter request while the file exists. A run's change log never changes, and the folder keeps
    only the newest few files."""
    # shortcut: a per-instance temp copy (lost on a cold start), fine because one re-download per instance per run is cheap, revisit if Blob transfer runs short
    cache = Path(tempfile.gettempdir()) / "dc-changes"
    path = cache / f"{dataset.id}-{dataset.results_run_id}.csv"
    if path.exists():
        return path
    cache.mkdir(parents=True, exist_ok=True)
    part = cache / f"{path.name}.{uuid.uuid4().hex}.part"
    try:
        ctx.storage.get_file(run_key(dataset.id, dataset.results_run_id, "changelog.csv"), part)
    except StorageNotFound:
        part.unlink(missing_ok=True)
        raise errors.not_ready("The results are not ready yet. Start a clean job and wait for it to finish.")
    os.replace(part, path)
    for old in sorted(cache.glob("*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)[_CHANGELOG_CACHE_FILES:]:
        old.unlink(missing_ok=True)
    return path


def _changes(ctx: Context, dataset: Dataset, filters: dict[str, str], limit: int, offset: int) -> dict[str, Any]:
    """Read one page of the change log (a cached temp file), filtering as it streams."""
    total = 0
    items: list[dict[str, Any]] = []
    with open(_changelog_path(ctx, dataset), encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if any(row[key] != value for key, value in filters.items()):
                continue
            if offset <= total < offset + limit:
                item: dict[str, Any] = {k: (v if v != "" else None) for k, v in row.items()}
                item["row_id"] = int(item["row_id"]) if item["row_id"] is not None else None
                items.append(item)
            total += 1
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/datasets/{dataset_id}/results")
def get_results(
    request: Request,
    dataset_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    rule_id: str | None = None,
    column: str | None = None,
    action: str | None = None,
    change_type: str | None = None,
):
    ctx = _ctx(request)
    dataset = _dataset(ctx, dataset_id)
    if dataset.results_json is None:
        raise errors.not_ready("The results are not ready yet. Start a clean job and wait for it to finish.")
    result = json.loads(dataset.results_json)
    given = {"rule_id": rule_id, "column": column, "action": action, "change_type": change_type}
    filters = {k: v for k, v in given.items() if v}
    return {
        "dataset_id": dataset_id,
        "run_id": result["run_id"],
        "before": result["before"],
        "after": result["after"],
        "columns": result["columns"],
        "summary": result["summary"],
        "changes": _changes(ctx, dataset, filters, limit, offset),
        "downloads": list(DOWNLOADS),
        "warnings": result["warnings"],
    }


# --------------------------------------------------------------------------- downloads

def _prepare_download(ctx: Context, dataset: Dataset, name: str) -> str:
    """The storage key of the current clean run's output file. clean.xlsx is built on first request
    (once, even for simultaneous requests) and then kept for that run; a build failure is its own
    error and touches nothing else. A dataset or run that vanished meanwhile is a 404, never a 500."""
    if dataset.results_json is None:
        raise errors.not_ready("This file is not ready yet. Clean the file first.")
    key = run_key(dataset.id, dataset.results_run_id, name)
    try:
        if name == "clean.xlsx":          # other files are not checked here: opening the stream finds a missing one
            try:
                ensure_xlsx(ctx, dataset)
            except StorageNotFound:
                raise
            except Exception:
                log.exception("building clean.xlsx failed for dataset %s", dataset.id)
                raise errors.ApiError(
                    500, "excel_failed",
                    "The Excel file could not be built. The CSV file and the report are still available.",
                )
    except StorageNotFound:
        raise errors.not_found("This dataset")
    return key


@router.post("/datasets/{dataset_id}/downloads/clean.xlsx/prepare")
def prepare_excel(request: Request, dataset_id: str):
    """Build clean.xlsx now, so the website can show "Preparing your Excel file" and then download."""
    ctx = _ctx(request)
    _prepare_download(ctx, _dataset(ctx, dataset_id), "clean.xlsx")
    return {"ready": True}


@router.get("/datasets/{dataset_id}/downloads/{name}")
def download(request: Request, dataset_id: str, name: str):
    ctx = _ctx(request)
    dataset = _dataset(ctx, dataset_id)
    if name not in DOWNLOADS:
        raise errors.not_found("This download")
    key = _prepare_download(ctx, dataset, name)
    suffix, media_type = DOWNLOADS[name]
    filename = (Path(dataset.filename).stem or "data") + suffix
    try:
        stream = ctx.storage.open_stream(key)       # opened now, so a missing file is a clean error, not a broken stream
    except StorageNotFound:
        raise errors.not_ready("This file is not ready yet. Clean the file first.")
    quoted = urllib.parse.quote(filename)
    disposition = f'attachment; filename="{filename}"' if quoted == filename else f"attachment; filename*=utf-8''{quoted}"
    return StreamingResponse(stream, media_type=media_type, headers={"Content-Disposition": disposition})
