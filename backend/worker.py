"""Vercel Queues consumer (push mode). Listed under [[tool.vercel.subscribers]] in pyproject.toml.

Delivery is at least once, so handle_message is idempotent: claim_job decides who runs a job, and a
message for a job that is done, failed, superseded, expired or running elsewhere does nothing and
returns normally (which acknowledges it, so redeliveries stop).
"""

from __future__ import annotations

import asyncio
import functools

from sqlalchemy import update
from sqlmodel import Session
from vercel.queue import Message, RetryAfter, subscribe

from backend.config import Settings
from backend.db import ACTIVE, Dataset, Job, fail_job, utcnow
from backend.jobs import Context, RetryJob, run_clean_job, run_profile_job
from backend.runner import TOPIC
from backend.limits import make_context
from backend.storage import StorageNotFound, run_key
from engine.models import ApprovedPlan

RETRY_DELAY_SECONDS = 20


@functools.cache
def get_ctx() -> Context:
    return make_context(Settings())


def handle_message(ctx: Context, job_id: str) -> None:
    """Run one job. Returns normally when there is nothing to do; raises RetryJob to ask for a redelivery."""
    with Session(ctx.engine) as session:
        job = session.get(Job, job_id)
        if job is None or job.status not in ACTIVE:
            return
        dataset = session.get(Dataset, job.dataset_id)
        if dataset is None or dataset.generation != job.generation:      # replaced by a newer run
            session.execute(update(Job).where(Job.id == job_id, Job.status.in_(ACTIVE)).values(
                status="superseded", error_code="superseded", updated_at=utcnow(),
                error_message="A newer run was started for this file, so this result was not kept."))
            session.commit()
            return
        session.expunge(dataset)
    if job.type == "profile":
        run_profile_job(ctx, job_id, dataset, retryable=True)
        return
    try:
        plan = ApprovedPlan.model_validate_json(ctx.storage.read_bytes(run_key(dataset.id, job_id, "plan.json")))
    except StorageNotFound:
        fail_job(ctx.engine, job_id, "storage_error", "The file store was not available. Please try again.")
        return
    run_clean_job(ctx, job_id, dataset, plan, retryable=True)


@subscribe(topic=TOPIC)
async def consume(message: Message[dict[str, str]]) -> None:
    try:
        await asyncio.to_thread(handle_message, get_ctx(), message.payload["job_id"])
    except RetryJob:
        raise RetryAfter(RETRY_DELAY_SECONDS)
