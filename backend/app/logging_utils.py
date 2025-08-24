"""Utilities for request-scoped logging with request IDs."""

from contextvars import ContextVar
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Context variable to store the current request ID
request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Logging filter to inject request_id into log records."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        record.request_id = request_id_ctx_var.get("-")
        return True


class RequestIdAdapter(logging.LoggerAdapter):
    """Logger adapter that adds request_id from context var."""

    def process(self, msg, kwargs):  # noqa: D401
        extra = kwargs.get("extra")
        if not extra:
            extra = {}
        extra["request_id"] = request_id_ctx_var.get("-")
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name: str | None = None) -> RequestIdAdapter:
    """Return a logger adapter that includes the request ID."""

    logger = logging.getLogger(name)
    return RequestIdAdapter(logger)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that assigns a request ID and logs request/response details."""

    def __init__(self, app):
        super().__init__(app)
        self.logger = get_logger(__name__)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex)
        token = request_id_ctx_var.set(request_id)
        start = time.perf_counter()
        self.logger.info("Started %s %s", request.method, request.url.path)
        response: Response | None = None
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception:
            self.logger.exception(
                "Unhandled error for %s %s", request.method, request.url.path
            )
            raise
        finally:
            duration = (time.perf_counter() - start) * 1000
            status = response.status_code if response is not None else 500
            self.logger.info(
                "Completed %s %s with status %s in %.2fms",
                request.method,
                request.url.path,
                status,
                duration,
            )
            request_id_ctx_var.reset(token)
