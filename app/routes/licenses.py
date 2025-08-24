"""License listing API routes.

This module provides a simple endpoint for retrieving license codes and their
labels from the Redis data store.  It mirrors other lightweight route modules
by exposing an ``APIRouter`` that can be included in the main application
without special permissions.
"""

from __future__ import annotations

from fastapi import APIRouter

import app.main as main


router = APIRouter()


@router.get("/licenses")
def list_licenses() -> dict:
    """Return all license entries stored in Redis.

    Each license is stored under ``license:<code>`` with its human readable
    label as the value.  The endpoint returns a structure compatible with the
    expectations of the frontend tests: ``{"licenses": [{"code": ..., "label": ...}, ...]}``.
    """

    licenses: list[dict[str, str]] = []
    if main.redis_client is not None:
        for key in main.redis_client.scan_iter("license:*"):
            code = key.split(":", 1)[1]
            label = main.redis_client.get(key)
            licenses.append({"code": code, "label": label})
    return {"licenses": licenses}
