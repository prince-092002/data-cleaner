"""Job runners (CONTRACT 8.9). DC_JOB_RUNNER=inprocess (default): the route hands the job to FastAPI
BackgroundTasks. DC_JOB_RUNNER=queue: the route sends one small message to Vercel Queues and the
consumer in backend/worker.py runs it. Either way the route only writes the job row."""

from __future__ import annotations

import logging

from backend.db import fail_job
from backend.jobs import Context

log = logging.getLogger("data_cleaner.runner")

TOPIC = "dc-jobs"
RETENTION_SECONDS = 15 * 60      # a poisoned message dies after 15 minutes (max_attempts is not relied on)


def send_job_message(job_id: str) -> None:
    from vercel.queue.sync import QueueClient           # imported here so development needs no queue credentials

    QueueClient().send(TOPIC, {"job_id": job_id}, retention=RETENTION_SECONDS)


def enqueue(ctx: Context, job_id: str) -> None:
    """Send the job's message. A send that fails ends the job as failed at once, so nobody polls a job that will never run."""
    try:
        send_job_message(job_id)
    except Exception:
        log.exception("could not send the message for job %s", job_id)
        fail_job(ctx.engine, job_id, "internal_error", "The job could not be started. Please try again.")
