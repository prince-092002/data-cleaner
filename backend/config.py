"""Backend settings. Override with environment variables (DC_STORAGE_DIR, DC_CORS_ORIGINS,
DC_MAX_UPLOAD_MB), plus the two adapter switches:

- DATABASE_URL: when set, jobs and datasets live in Postgres (postgres:// and postgresql:// both
  work); when not set, SQLite at <storage dir>/app.db.
- DC_STORAGE_BACKEND: "local" (default, files under DC_STORAGE_DIR) or "blob" (Vercel Blob). Blob is
  used only when asked for explicitly, so a developer who has Vercel env vars never writes to
  Blob by accident. On Vercel, Blob authenticates through OIDC with BLOB_STORE_ID (no token).
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


def _default_origins() -> list[str]:
    raw = os.environ.get("DC_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


def _storage_backend() -> str:
    raw = os.environ.get("DC_STORAGE_BACKEND", "local").strip().lower() or "local"
    if raw not in ("local", "blob"):
        raise ValueError(f'DC_STORAGE_BACKEND must be "local" or "blob" (got {raw!r}).')
    return raw


@dataclass
class Settings:
    storage_dir: Path = field(default_factory=lambda: Path(os.environ.get("DC_STORAGE_DIR", "storage")))
    max_upload_bytes: int = field(default_factory=_max_upload_bytes)
    storage_backend: str = field(default_factory=_storage_backend)
    database_url: str | None = field(default_factory=lambda: os.environ.get("DATABASE_URL") or None)
    job_lease_seconds: int = 900       # a running job not finished by then may be claimed again
    job_max_attempts: int = 3
    ttl_hours: int = 24
    cleanup_interval_seconds: int = 3600
    cors_origins: list[str] = field(default_factory=_default_origins)

    @property
    def db_path(self) -> Path:
        return self.storage_dir / "app.db"
