"""HTTP routes. See CONTRACT.md section 8. No cleaning logic lives here."""

from __future__ import annotations

import csv
import datetime as dt
import json
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session

from backend import errors
from backend.db import Dataset, Job, iso, start_generation, utcnow
from backend.jobs import Context, run_clean_job, run_profile_job
from backend.storage import DOWNLOADS, TooLarge, is_uuid, looks_like
from engine import pipeline
from engine.errors import IngestError, PlanError
from engine.models import DatasetProfile, Decisions

router = APIRouter(prefix="/api")

ALLOWED = {".csv": "csv", ".xlsx": "xlsx"}
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
        session.add(Job(id=job_id, dataset_id=dataset_id, type=job_type, generation=generation,
                        created_at=now, updated_at=now))
        session.commit()
    return job_id


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- upload

@router.post("/datasets", status_code=201)
def upload_dataset(request: Request, file: UploadFile):
    ctx = _ctx(request)
    filename = _display_name(file.filename)
    file_type = ALLOWED.get(Path(filename).suffix.lower())
    if file_type is None:
        raise errors.ApiError(415, "unsupported_file_type", "Only .csv and .xlsx files are supported.")

    dataset_id = str(uuid.uuid4())
    limit = ctx.settings.max_upload_bytes
    try:
        size = ctx.storage.save_upload(dataset_id, file_type, file.file, limit)
    except TooLarge:
        raise errors.ApiError(413, "file_too_large", f"Files must be {limit / (1024 * 1024):g} MB or smaller.")

    original = ctx.storage.original(dataset_id, file_type)
    try:
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
    except errors.ApiError:
        ctx.storage.delete(dataset_id)
        raise

    ctx.storage.file(dataset_id, "inspection.json").write_text(inspection.model_dump_json(), encoding="utf-8")
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
    sheets = _read_json(ctx.storage.file(dataset_id, "inspection.json"))["sheets"]
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

    with Session(ctx.engine) as session:
        row = session.get(Dataset, dataset_id)
        row.sheet, row.header_row = sheet["name"], header_row
        session.add(row)
        session.commit()
    dataset.sheet, dataset.header_row = sheet["name"], header_row

    # A new profile replaces the old one and anything cleaned from it (a new generation).
    job_id = _new_job(ctx, dataset_id, "profile")
    background.add_task(run_profile_job, ctx, job_id, dataset)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str):
    ctx = _ctx(request)
    with Session(ctx.engine) as session:
        job = session.get(Job, job_id) if is_uuid(job_id) else None
        if job is None:
            raise errors.not_found("This job")
        return {
            "job_id": job.id,
            "dataset_id": job.dataset_id,
            "type": job.type,
            "status": job.status,
            "progress_pct": job.progress_pct,
            "current_step": job.current_step,
            "error": {"code": job.error_code, "message": job.error_message} if job.status == "failed" else None,
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

    job_id = _new_job(ctx, dataset_id, "clean")
    run_dir = ctx.storage.run_dir(dataset_id, job_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")
    background.add_task(run_clean_job, ctx, job_id, dataset, plan)
    return {"job_id": job_id}


def _changes(path: Path, filters: dict[str, str], limit: int, offset: int) -> dict[str, Any]:
    """Read one page of the change log, filtering as it streams."""
    total = 0
    items: list[dict[str, Any]] = []
    with open(path, encoding="utf-8", newline="") as fh:
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
    run_dir = ctx.storage.run_dir(dataset_id, dataset.results_run_id)
    given = {"rule_id": rule_id, "column": column, "action": action, "change_type": change_type}
    filters = {k: v for k, v in given.items() if v}
    return {
        "dataset_id": dataset_id,
        "run_id": result["run_id"],
        "before": result["before"],
        "after": result["after"],
        "columns": result["columns"],
        "summary": result["summary"],
        "changes": _changes(run_dir / "changelog.csv", filters, limit, offset),
        "downloads": list(DOWNLOADS),
        "warnings": result["warnings"],
    }


# --------------------------------------------------------------------------- downloads

@router.get("/datasets/{dataset_id}/downloads/{name}")
def download(request: Request, dataset_id: str, name: str):
    ctx = _ctx(request)
    dataset = _dataset(ctx, dataset_id)
    if name not in DOWNLOADS:
        raise errors.not_found("This download")
    if dataset.results_json is None:
        raise errors.not_ready("This file is not ready yet. Clean the file first.")
    path = ctx.storage.run_dir(dataset_id, dataset.results_run_id) / name
    if not path.exists():
        raise errors.not_ready("This file is not ready yet. Clean the file first.")
    suffix, media_type = DOWNLOADS[name]
    stem = Path(dataset.filename).stem or "data"
    return FileResponse(path, media_type=media_type, filename=stem + suffix)
