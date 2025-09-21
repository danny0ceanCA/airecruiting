import logging
import sys

from backend.app.logging_utils import (
    RequestIdFilter,
    get_logger as _get_logger,
    request_id_ctx_var,
)

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(levelname)s [%(request_id)s] %(message)s",
)

for handler in logging.getLogger().handlers:
    handler.addFilter(RequestIdFilter())


def get_logger(name: str) -> logging.Logger:
    return _get_logger(name)

__all__ = ["get_logger", "RequestIdFilter", "request_id_ctx_var"]
