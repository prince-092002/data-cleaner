"""FastAPI app. Run with: uvicorn backend.main:app --reload --port 8000"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import errors
from backend.cleanup import cleanup_loop
from backend.config import MB, Settings
from backend.db import fail_interrupted_jobs, make_engine
from backend.jobs import Context
from backend.routes import router
from backend.storage import Storage

log = logging.getLogger("data_cleaner")
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
            413, "file_too_large", f"Files must be {self.max_bytes // MB} MB or smaller."
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    storage = Storage(settings.storage_dir)
    ctx = Context(settings=settings, engine=make_engine(settings.db_path), storage=storage)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        interrupted = fail_interrupted_jobs(ctx.engine)
        if interrupted:
            log.warning("marked %s interrupted job(s) as failed", interrupted)
        task = asyncio.create_task(cleanup_loop(ctx))     # runs once now, then every hour
        try:
            yield
        finally:
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

    @app.get("/api/health")
    def health():
        return {"status": "ok", "max_upload_mb": settings.max_upload_bytes // MB}

    return app


app = create_app()
