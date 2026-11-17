"""Free-tier guards (CONTRACT 8.10): stored-byte total, daily job caps, per-IP cap. Counters live in
the database so every serverless instance shares them (db.counter_add is one atomic statement)."""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import os

from fastapi import Request

from backend import errors
from backend.db import counter_add, counter_get, make_engine
from backend.jobs import Context
from backend.storage import StorageBackend, make_storage

BYTES_KEY = "stored_bytes"
STORAGE_FULL = "The demo is full right now. Please try again tomorrow."
GLOBAL_CAP = "The demo has reached today's limit. Please try again tomorrow."
IP_CAP = "You have reached today's limit for this demo. Please try again tomorrow."
UPLOAD_GLOBAL_CAP = "The demo has reached today's upload limit. Please try again tomorrow."
UPLOAD_IP_CAP = "You have reached today's upload limit for this demo. Please try again tomorrow."


def utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def client_ip(request: Request) -> str | None:
    """First entry of x-forwarded-for, which Vercel sets to the client's public IP and overwrites
    so a caller cannot spoof it. No header (local development) means no per-IP cap."""
    # shortcut: a request with no x-forwarded-for skips the per-IP cap, fine because Vercel always sets it, revisit if hosted elsewhere
    first = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return first or None


def ip_group(ip: str) -> str:
    """IPv6 clients are grouped by their /64 (one household or host owns a whole block); IPv4 is unchanged."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 4:
        return ip
    if addr.ipv4_mapped:                    # ::ffff:a.b.c.d is an IPv4 client, not a shared /64
        return str(addr.ipv4_mapped)
    return str(ipaddress.ip_network((addr, 64), strict=False).network_address)


def _take_slot(ctx: Context, request: Request, keys: tuple[str, str], global_cap: int, ip_cap: int,
               code: str, global_msg: str, ip_msg: str) -> None:
    """Take one slot of today's caps or raise 429. The IP slot is taken first and handed back if the
    global cap refuses, so a refused request uses up nothing."""
    day = utc_today().isoformat()
    ip = client_ip(request)
    ip = ip_group(ip) if ip else ip
    ip_key = None
    if ip is not None:
        # Only a hash is stored. Salted with a server secret when one is set (so the hash cannot be
        # brute-forced from the IPv4 space), and always with the date (no linking across days).
        salt = os.environ.get("DC_IP_HASH_SALT") or os.environ.get("CRON_SECRET") or ""
        ip_key = f"{keys[1]}:{day}:{hashlib.sha256(f'{salt}:{day}:{ip}'.encode()).hexdigest()[:32]}"
        if not counter_add(ctx.engine, ip_key, 1, cap=ip_cap):
            raise errors.ApiError(429, code, ip_msg)
    if not counter_add(ctx.engine, f"{keys[0]}:{day}", 1, cap=global_cap):
        if ip_key:
            counter_add(ctx.engine, ip_key, -1)
        raise errors.ApiError(429, code, global_msg)


def count_job(ctx: Context, request: Request) -> None:
    _take_slot(ctx, request, ("jobs", "ip"), ctx.settings.daily_job_cap, ctx.settings.daily_ip_cap,
               "too_many_jobs", GLOBAL_CAP, IP_CAP)


def count_upload(ctx: Context, request: Request) -> None:
    _take_slot(ctx, request, ("uploads", "upip"), ctx.settings.daily_upload_cap, ctx.settings.daily_ip_upload_cap,
               "too_many_uploads", UPLOAD_GLOBAL_CAP, UPLOAD_IP_CAP)


def check_storage_room(ctx: Context) -> None:
    if counter_get(ctx.engine, BYTES_KEY) >= ctx.settings.storage_limit_bytes:
        raise errors.ApiError(503, "storage_full", STORAGE_FULL)


class MeteredStorage(StorageBackend):
    """Wraps a StorageBackend and keeps the stored_bytes counter: +size on every write, -size on every
    delete. Overwriting a key counts it again (the cron recomputes the exact total daily)."""
    # shortcut: the stored-bytes total drifts between daily recounts, fine against an 800 MB guard on a 1 GB store, revisit if the drift blocks real uploads

    def __init__(self, inner, engine):
        self._inner, self._engine = inner, engine

    def __getattr__(self, name):            # only what is not defined here: local helpers such as run_dir and root
        return getattr(self._inner, name)

    def put_file(self, key, path):
        self._inner.put_file(key, path)
        counter_add(self._engine, BYTES_KEY, path.stat().st_size)

    def put_bytes(self, key, data):
        self._inner.put_bytes(key, data)
        counter_add(self._engine, BYTES_KEY, len(data))

    def delete_prefix(self, prefix):
        freed = self._inner.delete_prefix(prefix)
        if freed:
            counter_add(self._engine, BYTES_KEY, -freed)
        return freed

    def get_file(self, key, dest):
        self._inner.get_file(key, dest)

    def read_bytes(self, key):
        return self._inner.read_bytes(key)

    def open_stream(self, key):
        return self._inner.open_stream(key)

    def exists(self, key):
        return self._inner.exists(key)

    def list_keys(self, prefix):
        return self._inner.list_keys(prefix)

    def size_under(self, prefix):
        return self._inner.size_under(prefix)

    def download_prefix(self, prefix, dest):
        self._inner.download_prefix(prefix, dest)


def make_context(settings, storage=None) -> Context:
    """The one way to build a Context (used by the web app and the queue consumer): the database
    engine, and storage wrapped so every write and delete reaches the stored_bytes counter."""
    engine = make_engine(settings.database_url or settings.db_path)
    return Context(settings=settings, engine=engine, storage=MeteredStorage(storage or make_storage(settings), engine))
