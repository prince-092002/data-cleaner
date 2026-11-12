"""FastAPI app. Run with: uvicorn backend.main:app --reload --port 8000"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI, Request
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

    @app.middleware("http")
    async def reject_oversized_uploads(request: Request, call_next):
        """Refuse a too-large upload from its Content-Length, before reading the body."""
        if request.method == "POST" and request.url.path == "/api/datasets":
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > settings.max_upload_bytes + _MULTIPART_OVERHEAD:
                return errors.error_response(
                    413, "file_too_large", f"Files must be {settings.max_upload_bytes // MB} MB or smaller."
                )
        return await call_next(request)

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
        return {"status": "ok"}

    return app


app = create_app()
