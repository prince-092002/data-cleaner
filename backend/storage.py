"""Stored files behind one interface (StorageBackend): local disk (default) or Vercel Blob.
Layout in CONTRACT.md section 9. Keys are "/"-separated and start with the dataset id.

File names are fixed. The uploaded file name is never used as a key or path. The engine only
ever sees local temp files: jobs download what they need, run, upload outputs and delete the temp folder.
"""

from __future__ import annotations

import datetime as dt
import shutil
import uuid
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Iterator

DOWNLOADS = {
    "clean.csv": ("_clean.csv", "text/csv; charset=utf-8"),
    "clean.xlsx": ("_clean.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "report.html": ("_report.html", "text/html; charset=utf-8"),
    "recipe.yaml": ("_recipe.yaml", "application/yaml"),
    "changelog.csv": ("_changelog.csv", "text/csv; charset=utf-8"),
}
_CHUNK = 1024 * 1024
MAX_XLSX_UNCOMPRESSED = 60 * 1024 * 1024    # a 4 MB .xlsx must not expand into a table that exhausts memory


class TooLarge(Exception):
    pass


class StorageNotFound(Exception):
    """A key does not exist (never uploaded, expired, or deleted while a request was running)."""


def is_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _checked(value: str, what: str) -> str:
    if not is_uuid(value):          # ids are always our own UUIDs; anything else is not a key part
        raise ValueError(f"invalid {what} id")
    return value


def dataset_prefix(dataset_id: str) -> str:
    return f"{_checked(dataset_id, 'dataset')}/"


def original_key(dataset_id: str, file_type: str) -> str:
    return f"{dataset_prefix(dataset_id)}original.{file_type}"


def file_key(dataset_id: str, name: str) -> str:
    return f"{dataset_prefix(dataset_id)}{name}"


def cache_prefix(dataset_id: str) -> str:
    """The one deliberately shared entry: every profile of the dataset writes its cache files here."""
    return f"{dataset_prefix(dataset_id)}cache/"


def runs_prefix(dataset_id: str) -> str:
    return f"{dataset_prefix(dataset_id)}runs/"


def run_prefix(dataset_id: str, run_id: str) -> str:
    """Output folder of one clean job: {dataset}/runs/{run_id}/. Only that job writes here."""
    return f"{runs_prefix(dataset_id)}{_checked(run_id, 'run')}/"


def run_key(dataset_id: str, run_id: str, name: str) -> str:
    return run_prefix(dataset_id, run_id) + name


class StorageBackend(ABC):
    @abstractmethod
    def put_file(self, key: str, path: Path) -> None: ...

    @abstractmethod
    def put_bytes(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def get_file(self, key: str, dest: Path) -> None:
        """Download to dest. Raises StorageNotFound."""

    @abstractmethod
    def read_bytes(self, key: str) -> bytes: ...

    @abstractmethod
    def open_stream(self, key: str) -> Iterator[bytes]:
        """Open now (raises StorageNotFound at once), then yield chunks; closes itself when done."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def list_keys(self, prefix: str) -> list[tuple[str, dt.datetime]]:
        """(key, last modified in UTC) of everything under prefix."""

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int:
        """Delete everything under prefix; returns the bytes freed (one listing at most, for the byte counter)."""

    @abstractmethod
    def size_under(self, prefix: str) -> int:
        """Total bytes of everything under prefix ("" is the whole store)."""

    def download_prefix(self, prefix: str, dest: Path) -> None:
        """Copy every file under prefix into dest (names relative to the prefix)."""
        for key, _ in self.list_keys(prefix):
            try:
                self.get_file(key, dest / key[len(prefix):])
            except StorageNotFound:      # removed since it was listed
                pass

    def upload_dir(self, directory: Path, prefix: str, skip: set[str] = frozenset()) -> None:
        for path in sorted(directory.rglob("*")):
            rel = path.relative_to(directory).as_posix()
            if path.is_file() and rel not in skip:
                self.put_file(prefix + rel, path)


def write_limited(stream: BinaryIO, target: Path, max_bytes: int) -> int:
    """Stream an upload to a local file, stopping as soon as it exceeds max_bytes (raises TooLarge)."""
    size = 0
    with open(target, "wb") as out:
        while chunk := stream.read(_CHUNK):
            size += len(chunk)
            if size > max_bytes:
                raise TooLarge()
            out.write(chunk)
    return size


class LocalStorage(StorageBackend):
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key

    # Path helper (tests and local debugging)
    def run_dir(self, dataset_id: str, run_id: str) -> Path:
        return self._path(run_prefix(dataset_id, run_id).rstrip("/"))

    def put_file(self, key, path):
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)

    def put_bytes(self, key, data):
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def get_file(self, key, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(self._path(key), dest)
        except FileNotFoundError:
            raise StorageNotFound(key) from None

    def read_bytes(self, key):
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            raise StorageNotFound(key) from None

    def open_stream(self, key):
        try:
            fh = open(self._path(key), "rb")
        except FileNotFoundError:
            raise StorageNotFound(key) from None

        def chunks():
            with fh:
                while chunk := fh.read(_CHUNK):
                    yield chunk
        return chunks()

    def exists(self, key):
        return self._path(key).is_file()

    def list_keys(self, prefix):
        out = []
        for path in self.root.rglob("*"):
            key = path.relative_to(self.root).as_posix()
            if "/" in key and key.startswith(prefix) and path.is_file():   # top-level files (app.db) are not storage
                out.append((key, dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)))
        return out

    def size_under(self, prefix):
        return sum(self._path(key).stat().st_size for key, _ in self.list_keys(prefix) if self._path(key).exists())

    def delete_prefix(self, prefix):
        freed = self.size_under(prefix)
        folder = self._path(prefix.rstrip("/"))
        if prefix.endswith("/") and folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
        else:
            for key, _ in self.list_keys(prefix):
                self._path(key).unlink(missing_ok=True)
        return freed


class BlobStorage(StorageBackend):
    """Vercel Blob, private store. `client` is vercel.blob.sync (or a fake with the same functions);
    on Vercel it authenticates with OIDC through BLOB_STORE_ID, so no token is kept here."""

    def __init__(self, client=None):
        from vercel.blob import BlobNotFoundError
        if client is None:
            from vercel.blob import sync as client
        self.c = client
        self._missing = getattr(client, "BlobNotFoundError", BlobNotFoundError)

    def put_file(self, key, path):
        with open(path, "rb") as fh:
            # The SDK takes bytes or an iterable of chunks; a chunk iterator keeps big files out of memory.
            self.c.put_blob(key, _chunks(fh), access="private", allow_overwrite=True,
                            content_length=Path(path).stat().st_size)

    def put_bytes(self, key, data):
        self.c.put_blob(key, data, access="private", allow_overwrite=True)

    def _stream(self, key):
        cm = self.c.stream_blob(key, access="private")
        try:
            return cm, cm.__enter__()
        except self._missing:
            raise StorageNotFound(key) from None

    def get_file(self, key, dest):
        cm, body = self._stream(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(dest, "wb") as out:
                for chunk in body:
                    out.write(chunk)
        except self._missing:
            raise StorageNotFound(key) from None
        finally:
            cm.__exit__(None, None, None)

    def read_bytes(self, key):
        try:
            return self.c.get_blob(key, access="private").body
        except self._missing:
            raise StorageNotFound(key) from None

    def open_stream(self, key):
        cm, body = self._stream(key)

        def chunks():
            try:
                yield from body
            finally:
                cm.__exit__(None, None, None)
        return chunks()

    def exists(self, key):
        try:
            self.c.head_blob(key)           # one direct call, not a listing
        except self._missing:
            return False
        return True

    def list_keys(self, prefix):
        return [(b.pathname, b.uploaded_at) for b in self.c.query_blobs(prefix=prefix or None)]

    def size_under(self, prefix):
        return sum(b.size for b in self.c.query_blobs(prefix=prefix or None))

    def delete_prefix(self, prefix):
        blobs = list(self.c.query_blobs(prefix=prefix or None))        # the one listing: keys and sizes
        keys = [b.pathname for b in blobs]
        for i in range(0, len(keys), 1000):        # the API takes up to 1000 per call
            self.c.delete_blob(keys[i:i + 1000])
        return sum(b.size for b in blobs)


def _chunks(fh: BinaryIO) -> Iterator[bytes]:
    while chunk := fh.read(_CHUNK):
        yield chunk



def make_storage(settings) -> StorageBackend:
    return BlobStorage() if settings.storage_backend == "blob" else LocalStorage(settings.storage_dir)


def looks_like(path: Path, file_type: str) -> bool:
    """Content check, so a renamed file is not accepted on its extension alone."""
    with open(path, "rb") as fh:
        head = fh.read(8192)
    if file_type == "xlsx":
        if not head.startswith(b"PK\x03\x04") or not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            # shortcut: trusts the sizes the zip declares (a lying header is not checked), revisit if a profile job still runs out of memory
            if sum(i.file_size for i in zf.infolist()) > MAX_XLSX_UNCOMPRESSED:
                return False
        return "[Content_Types].xml" in names and any(n.startswith("xl/") for n in names)
    # CSV: text. Reject known binary signatures and NUL bytes (UTF-16 text is allowed).
    if head.startswith((b"PK\x03\x04", b"%PDF", b"\xd0\xcf\x11\xe0", b"\x89PNG", b"\xff\xd8\xff", b"GIF8")):
        return False
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return True
    return b"\x00" not in head
