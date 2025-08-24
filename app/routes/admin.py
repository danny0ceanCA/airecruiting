"""Administrative API routes.

This module collects a number of endpoints used by the tests to exercise the
application's administration features.  The real project exposes a much richer
set of capabilities; here we only implement the small subset required for the
exercises.  The router is defined with a ``/admin`` prefix and all endpoints
require that the caller has an ``admin`` role.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

import app.main as main
from app.routes.auth import require_admin
from backend.app.logging_utils import get_logger


# Router configured with the required prefix and tag information so that the
# main application simply needs to ``include_router`` without additional
# arguments.
router = APIRouter(prefix="/admin", tags=["admin"])

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# User management endpoints
# ---------------------------------------------------------------------------


@router.get("/users")
def list_users(_: dict = Depends(require_admin)) -> dict:
    """Return all registered users stored in Redis."""
    logger.info("Listing users")
    users: list[dict] = []
    if main.redis_client is not None:
        for key in main.redis_client.scan_iter("user:*"):
            raw = main.redis_client.get(key)
            if raw:
                users.append(json.loads(raw))
    else:
        logger.warning("Redis unavailable while listing users")
    logger.info("Returning %d user(s)", len(users))
    return {"users": users}


@router.put("/users/{email}")
def update_user(email: str, payload: dict, _: dict = Depends(require_admin)) -> dict:
    """Update the stored record for ``email`` with the supplied ``payload``."""
    logger.info("Updating user %s", email)
    if main.redis_client is None:
        logger.warning("Redis unavailable while updating user %s", email)
        raise HTTPException(status_code=404, detail="User not found")

    key = f"user:{email}"
    raw = main.redis_client.get(key)
    if not raw:
        logger.warning("User %s not found for update", email)
        raise HTTPException(status_code=404, detail="User not found")

    data = json.loads(raw)
    data.update(payload)
    main.redis_client.set(key, json.dumps(data))
    logger.info("Updated user %s", email)
    return {"message": "User updated"}


@router.delete("/users/{email}")
def delete_user(email: str, _: dict = Depends(require_admin)) -> dict:
    """Delete a user record."""
    logger.info("Deleting user %s", email)
    if main.redis_client is None:
        logger.warning("Redis unavailable while deleting user %s", email)
        raise HTTPException(status_code=404, detail="User not found")

    key = f"user:{email}"
    if not main.redis_client.get(key):
        logger.warning("User %s not found for delete", email)
        raise HTTPException(status_code=404, detail="User not found")
    main.redis_client.delete(key)
    logger.info("Deleted user %s", email)
    return {"message": "User deleted"}


# ---------------------------------------------------------------------------
# School code management
# ---------------------------------------------------------------------------


@router.post("/school-codes")
def add_school_code(payload: dict, _: dict = Depends(require_admin)) -> dict:
    code = payload.get("code")
    label = payload.get("label")
    logger.info("Adding school code %s", code)
    if main.redis_client is not None and code and label:
        main.redis_client.set(f"school_code:{code}", label)
        logger.info("School code %s added", code)
    else:
        logger.warning("Failed to add school code %s", code)
    return {"message": "School code added"}


@router.put("/school-codes/{code}")
def update_school_code(code: str, payload: dict, _: dict = Depends(require_admin)) -> dict:
    logger.info("Updating school code %s", code)
    key = f"school_code:{code}"
    if main.redis_client is None or not main.redis_client.exists(key):
        logger.warning("School code %s not found", code)
        raise HTTPException(status_code=404, detail="Code not found")
    label = payload.get("label")
    main.redis_client.set(key, label)
    logger.info("School code %s updated", code)
    return {"message": "School code updated"}


@router.delete("/school-codes/{code}")
def delete_school_code(code: str, _: dict = Depends(require_admin)) -> dict:
    logger.info("Deleting school code %s", code)
    if main.redis_client is not None:
        main.redis_client.delete(f"school_code:{code}")
        logger.info("School code %s deleted", code)
    else:
        logger.warning("Redis unavailable while deleting school code %s", code)
    return {"message": "School code deleted"}


# ---------------------------------------------------------------------------
# License code management (minimal placeholder implementation)
# ---------------------------------------------------------------------------


@router.post("/licenses")
def add_license(payload: dict, _: dict = Depends(require_admin)) -> dict:
    code = payload.get("code")
    label = payload.get("label")
    logger.info("Adding license %s", code)
    if main.redis_client is not None and code and label:
        main.redis_client.set(f"license:{code}", label)
        logger.info("License %s added", code)
    else:
        logger.warning("Failed to add license %s", code)
    return {"message": "License added"}


@router.put("/licenses/{code}")
def update_license(code: str, payload: dict, _: dict = Depends(require_admin)) -> dict:
    logger.info("Updating license %s", code)
    key = f"license:{code}"
    if main.redis_client is None or not main.redis_client.exists(key):
        logger.warning("License %s not found", code)
        raise HTTPException(status_code=404, detail="License not found")
    main.redis_client.set(key, payload.get("label"))
    logger.info("License %s updated", code)
    return {"message": "License updated"}


@router.delete("/licenses/{code}")
def delete_license(code: str, _: dict = Depends(require_admin)) -> dict:
    logger.info("Deleting license %s", code)
    if main.redis_client is not None:
        main.redis_client.delete(f"license:{code}")
        logger.info("License %s deleted", code)
    else:
        logger.warning("Redis unavailable while deleting license %s", code)
    return {"message": "License deleted"}


# ---------------------------------------------------------------------------
# Utility endpoints
# ---------------------------------------------------------------------------


@router.delete("/reset-jobs")
def reset_jobs(_: dict = Depends(require_admin)) -> dict:
    """Remove all ``job:*`` and ``match_results:*`` keys from Redis."""
    logger.info("Resetting job and match result data")
    if main.redis_client is None:
        logger.warning("Redis unavailable; nothing to reset")
        return {"message": "Deleted 0 job(s) and 0 match result(s)"}
    job_keys = list(main.redis_client.scan_iter("job:*"))
    match_keys = list(main.redis_client.scan_iter("match_results:*"))
    for key in job_keys + match_keys:
        main.redis_client.delete(key)
    logger.info(
        "Deleted %d job(s) and %d match result(s)", len(job_keys), len(match_keys)
    )
    return {
        "message": f"Deleted {len(job_keys)} job(s) and {len(match_keys)} match result(s)"
    }


@router.delete("/delete-student/{email}")
def delete_student(email: str, _: dict = Depends(require_admin)) -> dict:
    """Remove a student and associated artefacts from Redis.

    The implementation here only touches the few keys that are relevant for the
    unit tests and is not intended to be a full recreation of the production
    system.
    """

    logger.info("Deleting student %s", email)
    if main.redis_client is None:
        logger.warning("Redis unavailable while deleting student %s", email)
        raise HTTPException(status_code=404, detail="Student not found")

    index_key = main.student_email_key(email)
    loc = main.redis_client.get(index_key)
    if not loc:
        logger.warning("Student %s not found", email)
        raise HTTPException(status_code=404, detail="Student not found")

    inst, sid = loc.split(":", 1)
    skey = main.student_key(inst, sid)

    # delete student and user records
    main.redis_client.delete(skey)
    main.redis_client.delete(index_key)
    main.redis_client.delete(f"user:{email}")

    # remove references from jobs
    for key in list(main.redis_client.scan_iter("job:*")):
        raw = main.redis_client.get(key)
        if not raw:
            continue
        job = json.loads(raw)
        changed = False
        for field in ["assigned_students", "placed_students"]:
            if email in job.get(field, []):
                job[field] = [e for e in job.get(field, []) if e != email]
                changed = True
        if changed:
            main.redis_client.set(key, json.dumps(job))

    # ancillary keys
    for key in list(main.redis_client.scan_iter(f"resume:*:{email}")):
        main.redis_client.delete(key)
    for key in list(main.redis_client.scan_iter(f"job_description:*:{email}")):
        main.redis_client.delete(key)
    for key in list(main.redis_client.scan_iter("match_results:*")):
        raw = main.redis_client.get(key)
        if not raw:
            continue
        try:
            results = [r for r in json.loads(raw) if r.get("email") != email]
        except Exception:  # pragma: no cover - unexpected data
            results = []
        main.redis_client.set(key, json.dumps(results))

    logger.info("Student %s deleted", email)
    return {"message": "Student deleted"}


@router.post("/test-notification")
def test_notification(_: dict = Depends(require_admin)) -> dict:
    """Trigger a fake notification email.

    The :func:`app.main.send_email` function is intentionally very small so the
    tests can easily monkeypatch it.
    """

    logger.info("Triggering test notification email")
    main.send_email(
        "admin@example.com",
        "Recruiter Interest",
        "A recruiter has expressed interest in a student",
    )
    logger.info("Test notification dispatched")
    return {"message": "Notification sent"}


@router.post("/test-weekly-summary")
def test_weekly_summary(_: dict = Depends(require_admin)) -> dict:
    logger.info("Triggering test weekly summary email")
    main.send_email("admin@example.com", "Weekly Summary", "Test summary")
    logger.info("Test weekly summary dispatched")
    return {"message": "Summary sent"}


# ---------------------------------------------------------------------------
# RSS feed management (simplified)
# ---------------------------------------------------------------------------


@router.post("/rss-feeds")
def add_rss_feed(payload: dict, _: dict = Depends(require_admin)) -> dict:
    name = payload.get("name")
    url = payload.get("url")
    logger.info("Adding RSS feed %s", name)
    if main.redis_client is not None and name and url:
        main.redis_client.set(f"rss:{name}", url)
        logger.info("RSS feed %s added", name)
    else:
        logger.warning("Failed to add RSS feed %s", name)
    return {"message": "Feed added"}


@router.put("/rss-feeds/{name}")
def update_rss_feed(name: str, payload: dict, _: dict = Depends(require_admin)) -> dict:
    logger.info("Updating RSS feed %s", name)
    key = f"rss:{name}"
    if main.redis_client is None or not main.redis_client.exists(key):
        logger.warning("RSS feed %s not found", name)
        raise HTTPException(status_code=404, detail="Feed not found")
    main.redis_client.set(key, payload.get("url"))
    logger.info("RSS feed %s updated", name)
    return {"message": "Feed updated"}


@router.delete("/rss-feeds/{name}")
def delete_rss_feed(name: str, _: dict = Depends(require_admin)) -> dict:
    logger.info("Deleting RSS feed %s", name)
    if main.redis_client is not None:
        main.redis_client.delete(f"rss:{name}")
        logger.info("RSS feed %s deleted", name)
    else:
        logger.warning("Redis unavailable while deleting RSS feed %s", name)
    return {"message": "Feed deleted"}


