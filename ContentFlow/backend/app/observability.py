"""Logging configuration and per-request IDs."""
from __future__ import annotations

import logging
import os
import re
from contextvars import ContextVar
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

logger = logging.getLogger(__name__)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


def configure_logging() -> None:
    """Send app logs to stderr with timestamps and request IDs.

    Only the `app` logger tree is configured, so uvicorn's own logging is untouched.
    """
    level = logging.getLevelName(os.environ.get("CONTENT_FLOW_LOG_LEVEL", "INFO").strip().upper())
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level if isinstance(level, int) else logging.INFO)
    if any(isinstance(h, logging.StreamHandler) and getattr(h, "_content_flow", False) for h in app_logger.handlers):
        return
    handler = logging.StreamHandler()
    handler._content_flow = True  # type: ignore[attr-defined]
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"))
    app_logger.addHandler(handler)
    app_logger.propagate = False


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a request ID to logs and responses; turn unhandled errors into a JSON 500."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid4().hex
        token = _request_id.set(request_id)
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception("Unhandled error on %s %s", request.method, request.url.path)
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "An unexpected error occurred. Please try again.", "request_id": request_id},
                )
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            _request_id.reset(token)
