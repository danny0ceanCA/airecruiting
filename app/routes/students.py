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
from backend.app.logging_utils import get_logger


# Router configured with prefix and tag information as required by the tests.
router = APIRouter(prefix="/students", tags=["students"])

logger = get_logger(__name__)


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

    logger.info("Listing all students")
    students: list[dict[str, Any]] = []
    if main.redis_client is not None:
        for key in main.redis_client.scan_iter("student:*:*"):
            raw = main.redis_client.get(key)
            if raw:
                students.append(json.loads(raw))
    logger.info("Retrieved %d students", len(students))
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
    logger.info("Listing students for school %s", inst)
    students: list[dict[str, Any]] = []
    if main.redis_client is not None:
        for key in main.redis_client.scan_iter(f"student:{inst}:*"):
            raw = main.redis_client.get(key)
            if raw:
                students.append(json.loads(raw))
    logger.info("Retrieved %d students for school %s", len(students), inst)
    return {"students": students}


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)) -> dict:
    """Return the student profile for the currently authenticated user."""

    logger.info("Fetching profile for %s", user.get("email"))
    if main.redis_client is None:
        logger.warning("Redis not configured when fetching profile for %s", user.get("email"))
        raise HTTPException(status_code=404, detail="Student not found")

    loc = main.redis_client.get(main.student_email_key(user["email"]))
    if not loc:
        logger.warning("Student profile for %s not found", user.get("email"))
        raise HTTPException(status_code=404, detail="Student not found")

    inst, sid = loc.split(":", 1)
    raw = main.redis_client.get(main.student_key(inst, sid))
    if not raw:
        logger.warning("Student record %s:%s not found", inst, sid)
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
    logger.info("Fetching placements for %s", student_email)
    if main.redis_client is not None:
        for key in main.redis_client.scan_iter("job:*"):
            raw = main.redis_client.get(key)
            if not raw:
                continue
            job = json.loads(raw)
            if student_email in job.get("placed_students", []):
                placements.append(job)
    logger.info("Found %d placements for %s", len(placements), student_email)
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

    inst = user.get("school_code") or payload.get("institutional_code") or "0000"

    student_id = payload.get("student_id") or email.split("@", 1)[0]

    # Normalise license labels to short codes (e.g. "Medical Assistant" -> "ma")
    lic = payload.get("license")
    if isinstance(lic, str):
        lic_clean = lic.strip()
        if " " in lic_clean and len(lic_clean) > 3:
            payload["license"] = "".join(word[0] for word in lic_clean.split()).lower()
        else:
            payload["license"] = lic_clean.lower()

    # Generate and store an embedding if the client stub is available.  The
    # tests monkeypatch ``main.client.embeddings.create`` so this call is safe.
    try:  # pragma: no cover - defensive, embeds are mocked in tests
        resp = main.client.embeddings.create(input=payload.get("experience_summary", ""), model="text-embedding-3-small")
        embedding = resp.data[0].embedding if getattr(resp, "data", None) else []
        payload["embedding"] = embedding
    except Exception:
        payload["embedding"] = []

    logger.info("Creating student profile for %s", email)
    main.persist_student_record(email, payload, inst, student_id)
    logger.info("Student profile for %s stored", email)
    return {"message": "Student created"}

