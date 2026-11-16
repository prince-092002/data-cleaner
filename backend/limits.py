"""Free-tier guards (CONTRACT 8.10): stored-byte total, daily job caps, per-IP cap. Counters live in
the database so every serverless instance shares them (db.counter_add is one atomic statement)."""

from __future__ import annotations

import datetime as dt
import hashlib
import os

from fastapi import Request

from backend import errors
from backend.db import counter_add, counter_get
from backend.jobs import Context

BYTES_KEY = "stored_bytes"
STORAGE_FULL = "The demo is full right now. Please try again tomorrow."
GLOBAL_CAP = "The demo has reached today's limit. Please try again tomorrow."
IP_CAP = "You have reached today's limit for this demo. Please try again tomorrow."


def utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def client_ip(request: Request) -> str | None:
    """First entry of x-forwarded-for, which Vercel sets to the client's public IP and overwrites
    so a caller cannot spoof it. No header (local development) means no per-IP cap."""
    first = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return first or None


def count_job(ctx: Context, request: Request) -> None:
    """Take one slot of today's caps or raise 429. The IP slot is taken first and handed back if the
    global cap refuses, so a refused request uses up nothing."""
    day = utc_today().isoformat()
    ip = client_ip(request)
    ip_key = None
    if ip is not None:
        # Only a hash is stored. Salted with a server secret when one is set (so the hash cannot be
        # brute-forced from the IPv4 space), and always with the date (no linking across days).
        salt = os.environ.get("DC_IP_HASH_SALT") or os.environ.get("CRON_SECRET") or ""
        ip_key = f"ip:{day}:{hashlib.sha256(f'{salt}:{day}:{ip}'.encode()).hexdigest()[:32]}"
        if not counter_add(ctx.engine, ip_key, 1, cap=ctx.settings.daily_ip_cap):
            raise errors.ApiError(429, "too_many_jobs", IP_CAP)
    if not counter_add(ctx.engine, f"jobs:{day}", 1, cap=ctx.settings.daily_job_cap):
        if ip_key:
            counter_add(ctx.engine, ip_key, -1)
        raise errors.ApiError(429, "too_many_jobs", GLOBAL_CAP)


def check_storage_room(ctx: Context) -> None:
    if counter_get(ctx.engine, BYTES_KEY) >= ctx.settings.storage_limit_bytes:
        raise errors.ApiError(503, "storage_full", STORAGE_FULL)


class MeteredStorage:
    """Wraps a StorageBackend and keeps the stored_bytes counter: +size on every write, -size on every
    delete. Overwriting a key counts it again (the cron recomputes the exact total daily)."""

    def __init__(self, inner, engine):
        self._inner, self._engine = inner, engine

    def __getattr__(self, name):            # everything else (reads, listing, local helpers) passes through
        return getattr(self._inner, name)

    def put_file(self, key, path):
        self._inner.put_file(key, path)
        counter_add(self._engine, BYTES_KEY, path.stat().st_size)

    def put_bytes(self, key, data):
        self._inner.put_bytes(key, data)
        counter_add(self._engine, BYTES_KEY, len(data))

    def delete_prefix(self, prefix):
        size = self._inner.size_under(prefix)
        self._inner.delete_prefix(prefix)
        if size:
            counter_add(self._engine, BYTES_KEY, -size)

    def upload_dir(self, directory, prefix, skip=frozenset()):     # must call our put_file
        for path in sorted(directory.rglob("*")):
            rel = path.relative_to(directory).as_posix()
            if path.is_file() and rel not in skip:
                self.put_file(prefix + rel, path)

    def download_prefix(self, prefix, dest):
        self._inner.download_prefix(prefix, dest)
