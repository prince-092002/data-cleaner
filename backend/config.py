"""Backend settings. Override with environment variables (DC_STORAGE_DIR, DC_CORS_ORIGINS,
DC_MAX_UPLOAD_MB)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MB = 1024 * 1024


def _default_origins() -> list[str]:
    raw = os.environ.get("DC_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


@dataclass
class Settings:
    storage_dir: Path = field(default_factory=lambda: Path(os.environ.get("DC_STORAGE_DIR", "storage")))
    max_upload_bytes: int = field(default_factory=lambda: int(os.environ.get("DC_MAX_UPLOAD_MB", "50")) * MB)
    ttl_hours: int = 24
    cleanup_interval_seconds: int = 3600
    cors_origins: list[str] = field(default_factory=_default_origins)

    @property
    def db_path(self) -> Path:
        return self.storage_dir / "app.db"
