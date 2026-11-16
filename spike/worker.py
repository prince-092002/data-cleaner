"""Throwaway spike: Vercel Queues push consumer. Runs the N-step job, writing progress to Postgres."""
from vercel.queue import Message, subscribe

import db


@subscribe(topic="spike-jobs", max_attempts=2)
async def run_job(message: Message[dict[str, object]]) -> None:
    job = message.payload
    tag = f"queue-delivery-{message.metadata.delivery_count}"
    print(f"consumer start job={job['job_id']} seconds={job['seconds']} {tag}")
    await db.run_steps(job["job_id"], int(job["seconds"]), tag)
    print(f"consumer done job={job['job_id']} {tag}")
