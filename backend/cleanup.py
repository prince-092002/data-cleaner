"""Delete uploads and everything derived from them 24 hours after upload."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from sqlmodel import Session, select

from backend.db import Dataset, Job, utcnow
from backend.jobs import Context
from backend.storage import is_uuid

log = logging.getLogger("data_cleaner.cleanup")


def delete_dataset(ctx: Context, session: Session, dataset: Dataset) -> None:
    for job in session.exec(select(Job).where(Job.dataset_id == dataset.id)).all():
        session.delete(job)
    session.delete(dataset)
    ctx.storage.delete(dataset.id)


def cleanup_expired(ctx: Context, now: dt.datetime | None = None) -> int:
    """Remove expired datasets (files and rows) and folders with no dataset row. Returns the count."""
    now = now or utcnow()
    removed = 0
    with Session(ctx.engine) as session:
        for dataset in session.exec(select(Dataset).where(Dataset.expires_at <= now)).all():
            delete_dataset(ctx, session, dataset)
            removed += 1
        session.commit()
        known = set(session.exec(select(Dataset.id)).all())
    # Orphan folders (no database row). Young ones may be an upload still in progress.
    cutoff = (now - dt.timedelta(hours=1)).timestamp()
    for folder in ctx.storage.root.iterdir():
        if (
            folder.is_dir()
            and is_uuid(folder.name)
            and folder.name not in known
            and folder.stat().st_mtime < cutoff
        ):
            ctx.storage.delete(folder.name)
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
