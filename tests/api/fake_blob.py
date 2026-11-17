"""An in-memory stand-in for vercel.blob.sync (put_blob, get_blob, stream_blob, delete_blob, query_blobs)."""

import collections
import contextlib
import datetime as dt
from types import SimpleNamespace

from vercel.blob import BlobNotFoundError


class FakeBlobClient:
    BlobNotFoundError = BlobNotFoundError

    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.calls = collections.Counter()      # client calls by operation (put, get, stream, head, list, delete)

    def put_blob(self, pathname, body, *, access, allow_overwrite=False, content_length=None, **_):
        self.calls["put"] += 1
        if not isinstance(body, bytes) and content_length is None:     # mirrors vercel/blob/_internal/validation.py:117
            raise TypeError("content_length is required for streaming bodies")
        assert access == "private"
        data = body if isinstance(body, bytes) else b"".join(body)
        self.blobs[pathname] = data
        self.puts.append(pathname)
        return SimpleNamespace(pathname=pathname)

    def get_blob(self, pathname, *, access):
        self.calls["get"] += 1
        if pathname not in self.blobs:
            raise BlobNotFoundError("missing")
        return SimpleNamespace(body=self.blobs[pathname])

    @contextlib.contextmanager
    def stream_blob(self, pathname, *, access):
        self.calls["get"] += 1
        if pathname not in self.blobs:
            raise BlobNotFoundError("missing")
        data = self.blobs[pathname]
        yield iter([data[i:i + 3] for i in range(0, len(data), 3)] or [b""])

    def head_blob(self, pathname):
        self.calls["head"] += 1
        if pathname not in self.blobs:
            raise BlobNotFoundError("missing")
        return SimpleNamespace(pathname=pathname, size=len(self.blobs[pathname]))

    def delete_blob(self, pathnames):
        self.calls["delete"] += 1
        for p in ([pathnames] if isinstance(pathnames, str) else pathnames):
            self.blobs.pop(p, None)

    def query_blobs(self, *, prefix=None, **_):
        self.calls["list"] += 1
        return self._query(prefix)

    def _query(self, prefix):
        now = dt.datetime.now(dt.timezone.utc)
        for p in sorted(self.blobs):
            if p.startswith(prefix or ""):
                yield SimpleNamespace(pathname=p, uploaded_at=now, size=len(self.blobs[p]))
