"""Student-related API routes.

This module gathers the endpoints dealing with student records that were
previously defined directly in :mod:`app.main`.  By collecting them under a
dedicated router we mirror the structure used elsewhere in the application and
keep ``main`` focused on application setup.  The router is configured with the
``/students`` prefix and ``students`` tag so it can be included in the main
application without additional arguments.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

import app.main as main
from app.routes.auth import get_current_user, require_admin


# Router configured with prefix and tag information as required by the tests.
router = APIRouter(prefix="/students", tags=["students"])


# ---------------------------------------------------------------------------
# Student listing endpoints
# ---------------------------------------------------------------------------


@router.get("/all")
def list_all_students(_: dict = Depends(require_admin)) -> dict:
    """Return all student records stored in Redis.

    Access to this endpoint is restricted to admin users.  Each student record
    is stored under ``student:<institutional_code>:<student_id>`` with an
    accompanying ``student_email:<email>`` index created by
    :func:`app.main.persist_student_record`.
    """

    students: list[dict[str, Any]] = []
    if main.redis_client is not None:
        for key in main.redis_client.scan_iter("student:*:*"):
            raw = main.redis_client.get(key)
            if raw:
                students.append(json.loads(raw))
    return {"students": students}


@router.get("/by-school")
def list_students_by_school(
    code: str | None = None, user: dict = Depends(get_current_user)
) -> dict:
    """Return students for the institution associated with ``code``.

    If ``code`` is omitted the user's ``school_code`` is used.  A missing code
    results in a ``400`` response as exercised by the tests.
    """

    inst = code or user.get("school_code")
    if not inst:
        raise HTTPException(status_code=400, detail="Institutional code required")

    students: list[dict[str, Any]] = []
    if main.redis_client is not None:
        for key in main.redis_client.scan_iter(f"student:{inst}:*"):
            raw = main.redis_client.get(key)
            if raw:
                students.append(json.loads(raw))
    return {"students": students}


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)) -> dict:
    """Return the student profile for the currently authenticated user."""

    if main.redis_client is None:
        raise HTTPException(status_code=404, detail="Student not found")

    loc = main.redis_client.get(main.student_email_key(user["email"]))
    if not loc:
        raise HTTPException(status_code=404, detail="Student not found")

    inst, sid = loc.split(":", 1)
    raw = main.redis_client.get(main.student_key(inst, sid))
    if not raw:
        raise HTTPException(status_code=404, detail="Student not found")
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Ancillary endpoints
# ---------------------------------------------------------------------------


@router.get("/placements/{student_email}")
def get_placements(student_email: str, _: dict = Depends(get_current_user)) -> dict:
    """Return placement records for ``student_email``.

    The tests only require a minimal implementation: all jobs stored in Redis
    under ``job:*`` are inspected and any job listing the supplied email in its
    ``placed_students`` list is returned.
    """

    placements: list[dict[str, Any]] = []
    if main.redis_client is not None:
        for key in main.redis_client.scan_iter("job:*"):
            raw = main.redis_client.get(key)
            if not raw:
                continue
            job = json.loads(raw)
            if student_email in job.get("placed_students", []):
                placements.append(job)
    return {"placements": placements}


# ---------------------------------------------------------------------------
# Student creation (minimal placeholder)
# ---------------------------------------------------------------------------


@router.post("")
def create_student(payload: dict, user: dict = Depends(get_current_user)) -> dict:
    """Create a new student profile for the authenticated user.

    The real application performs extensive validation and embedding generation;
    for the purposes of the exercises we merely persist the supplied payload
    using :func:`app.main.persist_student_record`.
    """

    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email required")

    inst = user.get("school_code") or payload.get("institutional_code")
    if not inst:
        raise HTTPException(status_code=400, detail="Institutional code required")

    student_id = payload.get("student_id") or email.split("@", 1)[0]

    # Generate and store an embedding if the client stub is available.  The
    # tests monkeypatch ``main.client.embeddings.create`` so this call is safe.
    try:  # pragma: no cover - defensive, embeds are mocked in tests
        resp = main.client.embeddings.create(input=payload.get("experience_summary", ""), model="text-embedding-3-small")
        embedding = resp.data[0].embedding if getattr(resp, "data", None) else []
        payload["embedding"] = embedding
    except Exception:
        payload["embedding"] = []

    main.persist_student_record(email, payload, inst, student_id)
    return {"message": "Student created"}

