"""FastAPI app. Run with: uvicorn backend.main:app --reload --port 8000"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend import errors
from backend.cleanup import cleanup_loop
from backend.config import MB, Settings
from backend.cron import router as cron_router
from backend.db import fail_interrupted_jobs
from backend.limits import make_context
from backend.routes import router
from backend.storage import StorageBackend

log = logging.getLogger("data_cleaner")
SITE_DIR = Path(__file__).parents[1] / "site"     # the built frontend; only the Vercel build creates it (not public/: the Python builder drops it)
_MULTIPART_OVERHEAD = MB      # form boundaries and headers around the file


class UploadLimit:
    """Counts upload bytes as they arrive, before any form parsing or temp file.

    Refuses at once from Content-Length when it is declared; otherwise stops reading as soon as
    the body passes the limit (chunked uploads have no Content-Length) and answers 413.
    """

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes
        self.max_body = max_bytes + _MULTIPART_OVERHEAD

    async def _reject(self, send) -> None:
        response = errors.error_response(
            413, "file_too_large", f"Files must be {self.max_bytes / MB:g} MB or smaller."
        )
        await response({"type": "http"}, None, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/api/datasets":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_body:
            await self._reject(send)
            return

        seen = 0
        over = False

        async def counted_receive():
            nonlocal seen, over
            if over:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_body:
                    over = True                      # stop reading; the app sees a disconnect
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            if not over:                             # once over, the app's own answer is replaced
                await send(message)

        try:
            await self.app(scope, counted_receive, guarded_send)
        except Exception:
            if not over:
                raise
        if over:
            await self._reject(send)


def create_app(settings: Settings | None = None, storage: StorageBackend | None = None) -> FastAPI:
    settings = settings or Settings()
    ctx = make_context(settings, storage)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        # With one SQLite file there is one server process, so a job found running died with the
        # previous process. With a shared database other instances may own it; its deadline handles that.
        interrupted = fail_interrupted_jobs(ctx.engine) if ctx.engine.dialect.name == "sqlite" else 0
        if interrupted:
            log.warning("marked %s interrupted job(s) as failed", interrupted)
        # Development only: in production Vercel Cron calls /api/cron/cleanup (serverless has no long-lived loop).
        task = asyncio.create_task(cleanup_loop(ctx)) if settings.job_runner == "inprocess" else None   # once now, then hourly
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            ctx.engine.dispose()

    app = FastAPI(title="Data Cleaner API", version="0.1.0", lifespan=lifespan)
    app.state.ctx = ctx
    errors.install(app)

    app.add_middleware(UploadLimit, max_bytes=settings.max_upload_bytes)   # inside CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    app.include_router(router)
    app.include_router(cron_router)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "max_upload_mb": round(settings.max_upload_bytes / MB, 2)}

    if SITE_DIR.is_dir():      # last, so every /api route wins
        app.mount("/", StaticFiles(directory=SITE_DIR, html=True))

    return app


app = create_app()
