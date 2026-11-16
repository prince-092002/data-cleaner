"""Vercel Cron target (CONTRACT 8.10). Vercel calls GET with `Authorization: Bearer $CRON_SECRET`."""

from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, Request
from sqlmodel import Session, delete

from backend import errors, limits
from backend.cleanup import cleanup_expired
from backend.db import Counter, acquire_lease, counter_set, release_lease

router = APIRouter(prefix="/api")
log = logging.getLogger("data_cleaner.cron")
LEASE_KEY = "cron:cleanup"


def _authorized(request: Request) -> bool:
    secret = os.environ.get("CRON_SECRET", "")
    if not secret:                                        # unset: nobody is authorized
        return False
    given = request.headers.get("authorization", "")
    return hmac.compare_digest(given.encode(), f"Bearer {secret}".encode())


@router.get("/cron/cleanup")
def cron_cleanup(request: Request):
    if not _authorized(request):
        raise errors.ApiError(401, "unauthorized", "Not authorized.")
    ctx = request.app.state.ctx
    holder = acquire_lease(ctx.engine, LEASE_KEY, "-", seconds=600)
    if holder is None:                                    # a run is already in progress (or Vercel delivered twice)
        return {"skipped": True}
    try:
        removed = cleanup_expired(ctx)
        # TODO(Step 13, after Agent Q merges): call db.expire_stuck_jobs(ctx.engine) here and report its count.
        today = limits.utc_today().isoformat()
        with Session(ctx.engine) as session:              # yesterday's counters are no longer needed
            session.execute(delete(Counter).where(Counter.key != limits.BYTES_KEY, Counter.key.not_like(f"%:{today}%")))
            session.commit()
        stored = ctx.storage.size_under("")               # self-correct the running byte total
        counter_set(ctx.engine, limits.BYTES_KEY, stored)
        return {"skipped": False, "removed": removed, "stored_bytes": stored}
    finally:
        release_lease(ctx.engine, LEASE_KEY, holder)
