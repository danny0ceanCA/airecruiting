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


# Router configured with the required prefix and tag information so that the
# main application simply needs to ``include_router`` without additional
# arguments.
router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# User management endpoints
# ---------------------------------------------------------------------------


@router.get("/users")
def list_users(_: dict = Depends(require_admin)) -> dict:
    """Return all registered users stored in Redis."""

    users: list[dict] = []
    if main.redis_client is not None:
        for key in main.redis_client.scan_iter("user:*"):
            raw = main.redis_client.get(key)
            if raw:
                users.append(json.loads(raw))
    return {"users": users}


@router.put("/users/{email}")
def update_user(email: str, payload: dict, _: dict = Depends(require_admin)) -> dict:
    """Update the stored record for ``email`` with the supplied ``payload``."""

    if main.redis_client is None:
        raise HTTPException(status_code=404, detail="User not found")

    key = f"user:{email}"
    raw = main.redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="User not found")

    data = json.loads(raw)
    data.update(payload)
    main.redis_client.set(key, json.dumps(data))
    return {"message": "User updated"}


@router.delete("/users/{email}")
def delete_user(email: str, _: dict = Depends(require_admin)) -> dict:
    """Delete a user record."""

    if main.redis_client is None:
        raise HTTPException(status_code=404, detail="User not found")

    key = f"user:{email}"
    if not main.redis_client.get(key):
        raise HTTPException(status_code=404, detail="User not found")
    main.redis_client.delete(key)
    return {"message": "User deleted"}


# ---------------------------------------------------------------------------
# School code management
# ---------------------------------------------------------------------------


@router.post("/school-codes")
def add_school_code(payload: dict, _: dict = Depends(require_admin)) -> dict:
    code = payload.get("code")
    label = payload.get("label")
    if main.redis_client is not None and code and label:
        main.redis_client.set(f"school_code:{code}", label)
    return {"message": "School code added"}


@router.put("/school-codes/{code}")
def update_school_code(code: str, payload: dict, _: dict = Depends(require_admin)) -> dict:
    key = f"school_code:{code}"
    if main.redis_client is None or not main.redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Code not found")
    label = payload.get("label")
    main.redis_client.set(key, label)
    return {"message": "School code updated"}


@router.delete("/school-codes/{code}")
def delete_school_code(code: str, _: dict = Depends(require_admin)) -> dict:
    if main.redis_client is not None:
        main.redis_client.delete(f"school_code:{code}")
    return {"message": "School code deleted"}


# ---------------------------------------------------------------------------
# License code management (minimal placeholder implementation)
# ---------------------------------------------------------------------------


@router.post("/licenses")
def add_license(payload: dict, _: dict = Depends(require_admin)) -> dict:
    code = payload.get("code")
    label = payload.get("label")
    if main.redis_client is not None and code and label:
        main.redis_client.set(f"license:{code}", label)
    return {"message": "License added"}


@router.put("/licenses/{code}")
def update_license(code: str, payload: dict, _: dict = Depends(require_admin)) -> dict:
    key = f"license:{code}"
    if main.redis_client is None or not main.redis_client.exists(key):
        raise HTTPException(status_code=404, detail="License not found")
    main.redis_client.set(key, payload.get("label"))
    return {"message": "License updated"}


@router.delete("/licenses/{code}")
def delete_license(code: str, _: dict = Depends(require_admin)) -> dict:
    if main.redis_client is not None:
        main.redis_client.delete(f"license:{code}")
    return {"message": "License deleted"}


# ---------------------------------------------------------------------------
# Utility endpoints
# ---------------------------------------------------------------------------


@router.delete("/reset-jobs")
def reset_jobs(_: dict = Depends(require_admin)) -> dict:
    """Remove all ``job:*`` and ``match_results:*`` keys from Redis."""

    if main.redis_client is None:
        return {"message": "Deleted 0 job(s) and 0 match result(s)"}

    job_keys = list(main.redis_client.scan_iter("job:*"))
    match_keys = list(main.redis_client.scan_iter("match_results:*"))
    for key in job_keys + match_keys:
        main.redis_client.delete(key)
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

    if main.redis_client is None:
        raise HTTPException(status_code=404, detail="Student not found")

    index_key = main.student_email_key(email)
    loc = main.redis_client.get(index_key)
    if not loc:
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

    return {"message": "Student deleted"}


@router.post("/test-notification")
def test_notification(_: dict = Depends(require_admin)) -> dict:
    """Trigger a fake notification email.

    The :func:`app.main.send_email` function is intentionally very small so the
    tests can easily monkeypatch it.
    """

    main.send_email(
        "admin@example.com",
        "Recruiter Interest",
        "A recruiter has expressed interest in a student",
    )
    return {"message": "Notification sent"}


@router.post("/test-weekly-summary")
def test_weekly_summary(_: dict = Depends(require_admin)) -> dict:
    main.send_email("admin@example.com", "Weekly Summary", "Test summary")
    return {"message": "Summary sent"}


# ---------------------------------------------------------------------------
# RSS feed management (simplified)
# ---------------------------------------------------------------------------


@router.post("/rss-feeds")
def add_rss_feed(payload: dict, _: dict = Depends(require_admin)) -> dict:
    name = payload.get("name")
    url = payload.get("url")
    if main.redis_client is not None and name and url:
        main.redis_client.set(f"rss:{name}", url)
    return {"message": "Feed added"}


@router.put("/rss-feeds/{name}")
def update_rss_feed(name: str, payload: dict, _: dict = Depends(require_admin)) -> dict:
    key = f"rss:{name}"
    if main.redis_client is None or not main.redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Feed not found")
    main.redis_client.set(key, payload.get("url"))
    return {"message": "Feed updated"}


@router.delete("/rss-feeds/{name}")
def delete_rss_feed(name: str, _: dict = Depends(require_admin)) -> dict:
    if main.redis_client is not None:
        main.redis_client.delete(f"rss:{name}")
    return {"message": "Feed deleted"}


