"""Backend settings. Override with environment variables (DC_STORAGE_DIR, DC_CORS_ORIGINS,
DC_MAX_UPLOAD_MB, DC_JOB_RUNNER, DC_STORAGE_LIMIT_MB, DC_DAILY_JOB_CAP, DC_DAILY_IP_CAP, DC_DAILY_UPLOAD_CAP, DC_DAILY_IP_UPLOAD_CAP, DC_IP_HASH_SALT),
plus the adapter switches:

- DATABASE_URL: when set, jobs and datasets live in Postgres (postgres:// and postgresql:// both
  work); when not set, SQLite at <storage dir>/app.db.
- DC_JOB_RUNNER: "inprocess" (default, BackgroundTasks) or "queue" (Vercel Queues consumer in backend/worker.py).
- DC_STORAGE_BACKEND: "local" (default, files under DC_STORAGE_DIR) or "blob" (Vercel Blob). Blob is
  used only when asked for explicitly, so a developer who has Vercel env vars never writes to
  Blob by accident. On Vercel, Blob authenticates through OIDC with BLOB_STORE_ID (no token).

CRON_SECRET (never kept in Settings) is read from the environment by backend/cron.py on each call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MB = 1024 * 1024


def _max_upload_bytes() -> int:
    raw = os.environ.get("DC_MAX_UPLOAD_MB", "50")
    try:
        mb = float(raw)
    except ValueError:
        mb = 0.0
    if mb <= 0:
        raise ValueError(f"DC_MAX_UPLOAD_MB must be a positive number of megabytes, for example 4 or 4.5 (got {raw!r}).")
    return int(mb * MB)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        raise ValueError(f"{name} must be a whole number, 0 or more (got {raw!r}).")
    return value


def _default_origins() -> list[str]:
    raw = os.environ.get("DC_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


def _storage_backend() -> str:
    raw = os.environ.get("DC_STORAGE_BACKEND", "local").strip().lower() or "local"
    if raw not in ("local", "blob"):
        raise ValueError(f'DC_STORAGE_BACKEND must be "local" or "blob" (got {raw!r}).')
    return raw


def _job_runner() -> str:
    raw = os.environ.get("DC_JOB_RUNNER", "inprocess").strip().lower() or "inprocess"
    if raw not in ("inprocess", "queue"):
        raise ValueError(f'DC_JOB_RUNNER must be "inprocess" or "queue" (got {raw!r}).')
    return raw


@dataclass
class Settings:
    storage_dir: Path = field(default_factory=lambda: Path(os.environ.get("DC_STORAGE_DIR", "storage")))
    max_upload_bytes: int = field(default_factory=_max_upload_bytes)
    storage_backend: str = field(default_factory=_storage_backend)
    database_url: str | None = field(default_factory=lambda: os.environ.get("DATABASE_URL") or None)
    storage_limit_bytes: int = field(default_factory=lambda: _int_env("DC_STORAGE_LIMIT_MB", 800) * MB)
    daily_job_cap: int = field(default_factory=lambda: _int_env("DC_DAILY_JOB_CAP", 200))
    daily_ip_cap: int = field(default_factory=lambda: _int_env("DC_DAILY_IP_CAP", 10))
    daily_upload_cap: int = field(default_factory=lambda: _int_env("DC_DAILY_UPLOAD_CAP", 300))
    daily_ip_upload_cap: int = field(default_factory=lambda: _int_env("DC_DAILY_IP_UPLOAD_CAP", 20))
    # "queue" (Vercel Queues, production) only when DC_JOB_RUNNER=queue; Vercel variables alone never select it.
    job_runner: str = field(default_factory=_job_runner)
    job_deadline_seconds: float = 240  # hard limit per attempt, inside the 300 s function limit
    job_lease_seconds: int = 270       # deadline + 30 s: a running job not finished by then is stuck
    job_queue_wait_seconds: int = 300  # a queued job nobody picked up by then is failed (lost message)
    job_max_attempts: int = 3
    ttl_hours: int = 24
    cleanup_interval_seconds: int = 3600
    cors_origins: list[str] = field(default_factory=_default_origins)

    @property
    def db_path(self) -> Path:
        return self.storage_dir / "app.db"
