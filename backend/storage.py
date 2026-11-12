"""Files on local disk. Layout in CONTRACT.md section 9.

File names on disk are fixed. The uploaded file name is never used as a path.
"""

from __future__ import annotations

import shutil
import uuid
import zipfile
from pathlib import Path
from typing import BinaryIO

DOWNLOADS = {
    "clean.csv": ("_clean.csv", "text/csv; charset=utf-8"),
    "clean.xlsx": ("_clean.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "report.html": ("_report.html", "text/html; charset=utf-8"),
    "recipe.yaml": ("_recipe.yaml", "application/yaml"),
    "changelog.csv": ("_changelog.csv", "text/csv; charset=utf-8"),
}
_CHUNK = 1024 * 1024


class TooLarge(Exception):
    pass


def is_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


class Storage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def dataset_dir(self, dataset_id: str) -> Path:
        if not is_uuid(dataset_id):          # ids are always our own UUIDs; anything else is not a path
            raise ValueError("invalid dataset id")
        return self.root / dataset_id

    def original(self, dataset_id: str, file_type: str) -> Path:
        return self.dataset_dir(dataset_id) / f"original.{file_type}"

    def file(self, dataset_id: str, name: str) -> Path:
        return self.dataset_dir(dataset_id) / name

    def run_dir(self, dataset_id: str, run_id: str) -> Path:
        """Output folder of one clean job: {dataset}/runs/{run_id}/."""
        if not is_uuid(run_id):
            raise ValueError("invalid run id")
        return self.dataset_dir(dataset_id) / "runs" / run_id

    def delete_runs_except(self, dataset_id: str, keep: set[str]) -> None:
        runs = self.dataset_dir(dataset_id) / "runs"
        if runs.is_dir():
            for folder in runs.iterdir():
                if folder.name not in keep:
                    shutil.rmtree(folder, ignore_errors=True)

    def save_upload(self, dataset_id: str, file_type: str, stream: BinaryIO, max_bytes: int) -> int:
        """Stream the upload to disk, stopping as soon as it exceeds max_bytes."""
        folder = self.dataset_dir(dataset_id)
        folder.mkdir(parents=True, exist_ok=False)
        target = self.original(dataset_id, file_type)
        size = 0
        try:
            with open(target, "wb") as out:
                while chunk := stream.read(_CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        raise TooLarge()
                    out.write(chunk)
        except BaseException:
            self.delete(dataset_id)
            raise
        return size

    def delete(self, dataset_id: str) -> None:
        shutil.rmtree(self.dataset_dir(dataset_id), ignore_errors=True)


def looks_like(path: Path, file_type: str) -> bool:
    """Content check, so a renamed file is not accepted on its extension alone."""
    with open(path, "rb") as fh:
        head = fh.read(8192)
    if file_type == "xlsx":
        if not head.startswith(b"PK\x03\x04") or not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
        return "[Content_Types].xml" in names and any(n.startswith("xl/") for n in names)
    # CSV: text. Reject known binary signatures and NUL bytes (UTF-16 text is allowed).
    if head.startswith((b"PK\x03\x04", b"%PDF", b"\xd0\xcf\x11\xe0", b"\x89PNG", b"\xff\xd8\xff", b"GIF8")):
        return False
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return True
    return b"\x00" not in head
