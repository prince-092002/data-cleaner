"""API errors. Every non-2xx response has the body {"error": {"code", "message"}} (CONTRACT.md section 8)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def invalid_request(message: str) -> ApiError:
    return ApiError(400, "invalid_request", message)


def not_found(what: str = "This item") -> ApiError:
    return ApiError(404, "not_found", f"{what} was not found. Files are deleted 24 hours after upload.")


def not_ready(message: str) -> ApiError:
    return ApiError(409, "not_ready", message)


_HTTP_CODES = {404: "not_found", 405: "invalid_request", 413: "file_too_large", 415: "unsupported_file_type"}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        detail = first.get("msg", "Invalid request")
        return error_response(400, "invalid_request", f"{where}: {detail}" if where else detail)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, "invalid_request" if exc.status_code < 500 else "internal_error")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        return error_response(500, "internal_error", "Something went wrong on the server.")
