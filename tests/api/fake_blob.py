"""An in-memory stand-in for vercel.blob.sync (put_blob, get_blob, stream_blob, delete_blob, query_blobs)."""

import contextlib
import datetime as dt
from types import SimpleNamespace

from vercel.blob import BlobNotFoundError


class FakeBlobClient:
    BlobNotFoundError = BlobNotFoundError

    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.puts: list[str] = []

    def put_blob(self, pathname, body, *, access, allow_overwrite=False, **_):
        assert access == "private"
        data = body if isinstance(body, bytes) else b"".join(body)
        self.blobs[pathname] = data
        self.puts.append(pathname)
        return SimpleNamespace(pathname=pathname)

    def get_blob(self, pathname, *, access):
        if pathname not in self.blobs:
            raise BlobNotFoundError("missing")
        return SimpleNamespace(body=self.blobs[pathname])

    @contextlib.contextmanager
    def stream_blob(self, pathname, *, access):
        if pathname not in self.blobs:
            raise BlobNotFoundError("missing")
        data = self.blobs[pathname]
        yield iter([data[i:i + 3] for i in range(0, len(data), 3)] or [b""])

    def delete_blob(self, pathnames):
        for p in ([pathnames] if isinstance(pathnames, str) else pathnames):
            self.blobs.pop(p, None)

    def query_blobs(self, *, prefix=None, **_):
        now = dt.datetime.now(dt.timezone.utc)
        for p in sorted(self.blobs):
            if p.startswith(prefix or ""):
                yield SimpleNamespace(pathname=p, uploaded_at=now)
