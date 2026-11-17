"""Delete uploads and everything derived from them 24 hours after upload."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time

from sqlmodel import Session, delete, select

from backend.db import Dataset, Job, Lease, utcnow
from backend.jobs import Context
from backend.storage import dataset_prefix, is_uuid

log = logging.getLogger("data_cleaner.cleanup")


def delete_dataset(ctx: Context, session: Session, dataset: Dataset) -> None:
    for job in session.exec(select(Job).where(Job.dataset_id == dataset.id)).all():
        session.delete(job)
    session.delete(dataset)
    session.execute(delete(Lease).where(Lease.dataset_id == dataset.id))
    session.commit()      # rows first and released: the storage delete also writes the byte counter (SQLite has one writer)
    ctx.storage.delete_prefix(dataset_prefix(dataset.id))


def cleanup_expired(ctx: Context, now: dt.datetime | None = None, deadline: float | None = None) -> int:
    """Remove expired datasets (files and rows) and folders with no dataset row. Returns the count.
    Stops early once time.monotonic() passes deadline; the next run resumes (every step is idempotent)."""
    now = now or utcnow()
    removed = 0
    with Session(ctx.engine) as session:
        for dataset in session.exec(select(Dataset).where(Dataset.expires_at <= now)).all():
            if deadline is not None and time.monotonic() >= deadline:
                return removed
            delete_dataset(ctx, session, dataset)
            removed += 1
        session.commit()
        known = set(session.exec(select(Dataset.id)).all())
    # Orphan folders (no database row). Young ones may be an upload still in progress.
    cutoff = now - dt.timedelta(hours=1)
    newest: dict[str, dt.datetime] = {}
    for key, modified in ctx.storage.list_keys(""):
        folder = key.split("/")[0]
        if is_uuid(folder) and folder not in known:
            newest[folder] = max(modified, newest.get(folder, modified))
    for folder, modified in newest.items():
        if deadline is not None and time.monotonic() >= deadline:
            break
        if modified < cutoff:
            ctx.storage.delete_prefix(dataset_prefix(folder))
            removed += 1
    return removed


async def cleanup_loop(ctx: Context) -> None:
    while True:
        try:
            removed = await asyncio.to_thread(cleanup_expired, ctx)
            if removed:
                log.info("cleanup removed %s expired dataset(s)", removed)
        except Exception:
            log.exception("cleanup failed")
        await asyncio.sleep(ctx.settings.cleanup_interval_seconds)
