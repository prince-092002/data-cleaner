"""In-browser stand-in for backend/routes.py: same JSON shapes and error codes, no web code.

Runs in CPython (tests) and in Pyodide (the Web Worker). Datasets live in memory and under a
work folder; nothing is shared between visitors. Only engine.pipeline is called.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

from engine import pipeline
from engine.errors import EngineError, IngestError, PlanError
from engine.models import DatasetProfile, Decisions

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_XLSX_UNCOMPRESSED = 60 * 1024 * 1024
ALLOWED = {".csv": "csv", ".xlsx": "xlsx"}
# Same names, suffixes and MIME types as backend/storage.py DOWNLOADS.
DOWNLOADS = {
    "clean.csv": ("_clean.csv", "text/csv; charset=utf-8"),
    "clean.xlsx": ("_clean.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "report.html": ("_report.html", "text/html; charset=utf-8"),
    "recipe.yaml": ("_recipe.yaml", "application/yaml"),
    "changelog.csv": ("_changelog.csv", "text/csv; charset=utf-8"),
}
CHANGE_FILTERS = ("rule_id", "column", "action", "change_type")
Progress = Callable[[int, str], None]


class AdapterError(Exception):
    """Mirrors backend.errors.ApiError so the website's ApiError and friendly messages work."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _not_found(what: str = "This item") -> AdapterError:
    return AdapterError(404, "not_found", f"{what} was not found. Files are deleted 24 hours after upload.")


def _not_ready(message: str) -> AdapterError:
    return AdapterError(409, "not_ready", message)


def _invalid(message: str) -> AdapterError:
    return AdapterError(400, "invalid_request", message)


_work: Path | None = None
_datasets: dict[str, dict[str, Any]] = {}


def reset(work_dir: Path | str | None = None) -> None:
    """Forget every dataset (tests, and a fresh worker)."""
    global _work
    _datasets.clear()
    _work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="dc-browser-"))
    _work.mkdir(parents=True, exist_ok=True)


def _ds(dataset_id: str) -> dict[str, Any]:
    if dataset_id not in _datasets:
        raise _not_found("This dataset")
    return _datasets[dataset_id]


def _display_name(raw: str | None) -> str:
    name = PureWindowsPath(PurePosixPath(raw or "").name).name.strip()
    return name[:200] or "upload"


def _looks_like(path: Path, file_type: str) -> bool:
    with open(path, "rb") as fh:
        head = fh.read(8192)
    if file_type == "xlsx":
        if not head.startswith(b"PK\x03\x04") or not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if sum(i.file_size for i in zf.infolist()) > MAX_XLSX_UNCOMPRESSED:
                return False
        return "[Content_Types].xml" in names and any(n.startswith("xl/") for n in names)
    if head.startswith((b"PK\x03\x04", b"%PDF", b"\xd0\xcf\x11\xe0", b"\x89PNG", b"\xff\xd8\xff", b"GIF8")):
        return False
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return True
    return b"\x00" not in head


# --------------------------------------------------------------------------- upload

def upload(name: str, data: bytes) -> dict[str, Any]:
    filename = _display_name(name)
    file_type = ALLOWED.get(Path(filename).suffix.lower())
    if file_type is None:
        raise AdapterError(415, "unsupported_file_type", "Only .csv and .xlsx files are supported.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise AdapterError(413, "file_too_large", f"Files must be {MAX_UPLOAD_BYTES / (1024 * 1024):g} MB or smaller.")
    if len(data) == 0:
        raise AdapterError(422, "unreadable_file", "The file is empty.")
    if _work is None:
        reset()
    dataset_id = str(uuid.uuid4())
    folder = _work / dataset_id
    folder.mkdir(parents=True)
    original = folder / f"original.{file_type}"
    original.write_bytes(data)
    try:
        if not _looks_like(original, file_type):
            raise AdapterError(415, "unsupported_file_type", f"This file does not look like a real .{file_type} file.")
        try:
            inspection = pipeline.inspect(original)
        except IngestError as exc:
            raise AdapterError(422, "unreadable_file", exc.message)
    except AdapterError:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    for old in _datasets.values():  # one dataset at a time keeps the tab's memory flat
        shutil.rmtree(old["dir"], ignore_errors=True)
    _datasets.clear()
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24)
    _datasets[dataset_id] = {
        "id": dataset_id, "filename": filename, "file_type": file_type, "dir": folder, "original": original,
        "sheets": [s.model_dump() for s in inspection.sheets], "sheet": None, "header_row": None,
        "profile": None, "results": None, "out": None,
    }
    return {
        "dataset_id": dataset_id, "filename": filename, "file_type": file_type, "size_bytes": len(data),
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"), "sheets": _datasets[dataset_id]["sheets"],
    }


# --------------------------------------------------------------------------- profile

def profile(dataset_id: str, sheet: str | None = None, header_row: int | None = None,
            progress: Progress | None = None) -> dict[str, Any]:
    ds = _ds(dataset_id)
    sheets = ds["sheets"]
    by_name = {s["name"]: s for s in sheets}
    if ds["file_type"] == "csv":
        if sheet is not None:
            raise _invalid("CSV files do not have sheets.")
        chosen = sheets[0]
    else:
        if sheet is not None and sheet not in by_name:
            raise _invalid(f'Sheet "{sheet}" was not found in this file.')
        chosen = by_name[sheet] if sheet is not None else sheets[0]
    row = header_row if header_row is not None else chosen["detected_header_row"]
    if row < 0 or row >= max(chosen["row_count_estimate"], 1):
        raise _invalid("The header row is outside the file.")
    ds["sheet"], ds["header_row"] = chosen["name"], row
    # A new profile replaces the old one and anything cleaned from it.
    ds["results"] = ds["profile"] = None
    shutil.rmtree(ds["dir"] / "out", ignore_errors=True)
    try:
        result = pipeline.profile(ds["original"], sheet=ds["sheet"], header_row=row, progress=progress,
                                  display_name=ds["filename"], cache_dir=ds["dir"] / "cache")
    except IngestError as exc:
        raise AdapterError(422, "unreadable_file", exc.message)
    except EngineError as exc:
        raise _invalid(exc.message)
    ds["profile"] = json.loads(result.model_dump_json())
    return get_profile(dataset_id)


def get_profile(dataset_id: str) -> dict[str, Any]:
    ds = _ds(dataset_id)
    if ds["profile"] is None:
        raise _not_ready("The profile is not ready yet. Start a profile job and wait for it to finish.")
    return {"dataset_id": dataset_id, **ds["profile"]}


# --------------------------------------------------------------------------- clean

def clean(dataset_id: str, decisions_json: str, progress: Progress | None = None) -> None:
    ds = _ds(dataset_id)
    if ds["profile"] is None:
        raise _not_ready("Profile the file before cleaning it.")
    try:
        decisions = Decisions.model_validate_json(decisions_json)
    except ValueError as exc:
        raise _invalid(str(exc).splitlines()[0])
    try:
        plan = pipeline.build_plan(DatasetProfile.model_validate(ds["profile"]), decisions)
    except PlanError as exc:
        raise _invalid(exc.message)
    out = ds["dir"] / "out"
    shutil.rmtree(out, ignore_errors=True)
    run_id = str(uuid.uuid4())
    try:
        result = pipeline.clean(ds["original"], plan, out, run_id=run_id, progress=progress,
                                display_name=ds["filename"], cache_dir=ds["dir"] / "cache")
    except IngestError as exc:
        raise AdapterError(422, "unreadable_file", exc.message)
    except EngineError as exc:
        raise _invalid(exc.message)
    ds["results"], ds["out"] = json.loads(result.model_dump_json()), out


def _changes(out: Path, filters: dict[str, str], limit: int, offset: int) -> dict[str, Any]:
    total = 0
    items: list[dict[str, Any]] = []
    # shortcut: re-reads the whole change log for every page, fine for a 20 MB file, cache the rows if paging feels slow
    with open(out / "changelog.csv", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if any(row[key] != value for key, value in filters.items()):
                continue
            if offset <= total < offset + limit:
                item: dict[str, Any] = {k: (v if v != "" else None) for k, v in row.items()}
                item["row_id"] = int(item["row_id"]) if item["row_id"] is not None else None
                items.append(item)
            total += 1
    return {"total": total, "limit": limit, "offset": offset, "items": items}


def results(dataset_id: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
    ds = _ds(dataset_id)
    query = query or {}
    limit, offset = int(query.get("limit", 100)), int(query.get("offset", 0))
    if not 1 <= limit <= 500:
        raise _invalid("limit: must be between 1 and 500")
    if offset < 0:
        raise _invalid("offset: must be 0 or more")
    if ds["results"] is None:
        raise _not_ready("The results are not ready yet. Start a clean job and wait for it to finish.")
    res = ds["results"]
    filters = {k: str(query[k]) for k in CHANGE_FILTERS if query.get(k)}
    return {
        "dataset_id": dataset_id, "run_id": res["run_id"], "before": res["before"], "after": res["after"],
        "columns": res["columns"], "summary": res["summary"],
        "changes": _changes(ds["out"], filters, limit, offset),
        "downloads": list(DOWNLOADS), "warnings": res["warnings"],
    }


# --------------------------------------------------------------------------- downloads

def build_xlsx(dataset_id: str) -> Path:
    ds = _ds(dataset_id)
    if ds["results"] is None:
        raise _not_ready("This file is not ready yet. Clean the file first.")
    try:
        return pipeline.build_xlsx(ds["out"])
    except Exception:
        raise AdapterError(500, "excel_failed",
                           "The Excel file could not be built. The CSV file and the report are still available.")


def file(dataset_id: str, name: str) -> tuple[bytes, str, str]:
    """(bytes, download filename, MIME type) of one output file."""
    ds = _ds(dataset_id)
    if name not in DOWNLOADS:
        raise _not_found("This download")
    path = build_xlsx(dataset_id) if name == "clean.xlsx" else None
    if ds["results"] is None:
        raise _not_ready("This file is not ready yet. Clean the file first.")
    suffix, mime = DOWNLOADS[name]
    return (path or ds["out"] / name).read_bytes(), (Path(ds["filename"]).stem or "data") + suffix, mime
