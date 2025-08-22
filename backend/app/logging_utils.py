"""Utilities for request-scoped logging with request IDs."""

from contextvars import ContextVar
import logging

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
