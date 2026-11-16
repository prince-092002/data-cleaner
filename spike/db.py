"""Throwaway spike: Postgres helpers shared by the API and the queue consumer.
The connection string is read from the env and never returned or logged."""
import asyncio
import json
import os
import time

import psycopg

SCHEMA = """
create table if not exists jobs (
  job_id text primary key,
  mode text not null,
  seconds int not null,
  step int not null default 0,
  steps jsonb not null default '[]'::jsonb,
  started_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  finished_at timestamptz,
  note text
);
create table if not exists pings (id serial primary key, at timestamptz not null default now(), note text);
"""


async def connect() -> psycopg.AsyncConnection:
    # prepare_threshold=None: the pooled URL goes through PgBouncer, which dislikes prepared statements
    return await psycopg.AsyncConnection.connect(
        os.environ["DATABASE_URL"], autocommit=True, prepare_threshold=None
    )


async def ensure_schema() -> None:
    async with await connect() as conn:
        await conn.execute(SCHEMA)


async def create_job(job_id: str, mode: str, seconds: int) -> None:
    async with await connect() as conn:
        await conn.execute(SCHEMA)
        await conn.execute(
            "insert into jobs (job_id, mode, seconds) values (%s, %s, %s)", (job_id, mode, seconds)
        )


async def run_steps(job_id: str, seconds: int, tag: str) -> None:
    """One step per second, each written to Postgres with a timestamp. Nothing kept in memory."""
    t0 = time.monotonic()
    async with await connect() as conn:
        for step in range(1, seconds + 1):
            # sleep until the step's wall-clock slot so DB latency does not drift the cadence
            delay = t0 + step - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            entry = json.dumps([{"step": step, "tag": tag}])
            await conn.execute(
                "update jobs set step = %s, updated_at = now(),"
                " steps = steps || jsonb_set(%s::jsonb, '{0,at}', to_jsonb(now()))"
                " where job_id = %s",
                (step, entry, job_id),
            )
        await conn.execute(
            "update jobs set finished_at = now(), note = coalesce(note || ' ', '') || %s where job_id = %s",
            (f"finished:{tag}", job_id),
        )


async def get_job(job_id: str) -> dict | None:
    async with await connect() as conn:
        cur = await conn.execute(
            "select job_id, mode, seconds, step, steps, started_at, updated_at, finished_at, note, now()"
            " from jobs where job_id = %s",
            (job_id,),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    keys = ["job_id", "mode", "seconds", "step", "steps", "started_at", "updated_at", "finished_at", "note", "db_now"]
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in zip(keys, row)}
