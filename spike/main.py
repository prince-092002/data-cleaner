"""Throwaway spike (Vercel feasibility). Mechanism test endpoints. Never returns env values."""
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROCESS_STARTED = time.time()
INVOCATIONS = 0

from fastapi import FastAPI, HTTPException
from vercel import blob
from vercel.queue import send

import db

app = FastAPI()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/api/health")
async def health():
    return {"ok": True, "at": now()}


@app.post("/api/queue/start")
async def queue_start(seconds: int = 20):
    job_id = uuid.uuid4().hex
    await db.create_job(job_id, "queue", seconds)
    message_id = await send("spike-jobs", {"job_id": job_id, "seconds": seconds})
    return {"job_id": job_id, "message_id": message_id, "sent_at": now()}


@app.post("/api/inline/start")
async def inline_start(seconds: int = 20):
    """Fallback without a queue: the job runs inside this request."""
    job_id = uuid.uuid4().hex
    await db.create_job(job_id, "inline", seconds)
    print(f"inline start job={job_id}")
    await db.run_steps(job_id, seconds, "inline")
    print(f"inline done job={job_id}")
    return {"job_id": job_id, "finished_at": now()}


@app.get("/api/inline/latest")
async def inline_latest():
    # lets the client find the job id after it cut the connection before the response
    async with await db.connect() as conn:
        cur = await conn.execute("select job_id from jobs where mode = 'inline' order by started_at desc limit 1")
        row = await cur.fetchone()
    return {"job_id": row[0] if row else None}


@app.get("/api/status/{job_id}")
async def status(job_id: str, full: bool = False):
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "no such job")
    if not full:
        steps = job.pop("steps")
        job["steps_count"] = len(steps)
        job["steps_tail"] = steps[-3:]
    return job


@app.get("/api/blob")
async def blob_test():
    path = f"spike/{uuid.uuid4().hex}.txt"
    data = f"hello from spike {now()}".encode()
    out = {}
    try:
        put = await blob.put_blob(path, data, access="private", content_type="text/plain")
        out["put"] = {"ok": True, "pathname": put.pathname}
    except Exception as e:  # report the failure type only
        return {"put": {"ok": False, "error": type(e).__name__, "detail": str(e)[:200]}}
    try:
        got = await blob.get_blob(path, access="private")
        out["get"] = {"ok": got.body == data, "bytes": len(got.body)}
    except Exception as e:
        out["get"] = {"ok": False, "error": type(e).__name__, "detail": str(e)[:200]}
    try:
        await blob.delete_blob(path)
        out["delete"] = {"ok": True}
    except Exception as e:
        out["delete"] = {"ok": False, "error": type(e).__name__, "detail": str(e)[:200]}
    try:
        await blob.get_blob(path, access="private")
        out["get_after_delete"] = "still readable"
    except Exception as e:
        out["get_after_delete"] = f"gone ({type(e).__name__})"
    return out


@app.get("/api/db")
async def db_test(note: str = "ping"):
    """Connect + insert + read, timed inside the function (Neon cold vs warm)."""
    t0 = time.perf_counter()
    conn = await db.connect()
    t1 = time.perf_counter()
    async with conn:
        await conn.execute(db.SCHEMA)
        cur = await conn.execute("insert into pings (note) values (%s) returning id, at", (note,))
        row = await cur.fetchone()
        cur = await conn.execute("select count(*) from pings")
        count = (await cur.fetchone())[0]
    t2 = time.perf_counter()
    return {
        "connect_ms": round((t1 - t0) * 1000),
        "queries_ms": round((t2 - t1) * 1000),
        "total_ms": round((t2 - t0) * 1000),
        "inserted_id": row[0],
        "inserted_at": row[1].isoformat(),
        "pings_total": count,
        "at": now(),
    }


DATA = Path(__file__).parent / "data"
FILES = {"chicago": DATA / "chicago_cut.csv", "demo": DATA / "messy_orders_demo.csv"}


@app.get("/api/engine/run")
def engine_run_endpoint(file: str = "demo"):
    """Real engine: profile -> approve all -> clean, outputs in /tmp. Returns a small JSON summary."""
    global INVOCATIONS
    INVOCATIONS += 1
    if file not in FILES:
        raise HTTPException(404, "unknown file")
    import engine_run

    out = Path("/tmp") / uuid.uuid4().hex
    out.mkdir(parents=True)
    t = time.perf_counter()
    try:
        summary = engine_run.run(FILES[file], out)
    finally:
        shutil.rmtree(out, ignore_errors=True)
    summary["handler_total_s"] = round(time.perf_counter() - t, 3)
    summary["process_age_s"] = round(time.time() - PROCESS_STARTED, 1)
    summary["invocation_in_process"] = INVOCATIONS
    summary["input_bytes"] = FILES[file].stat().st_size
    return summary
