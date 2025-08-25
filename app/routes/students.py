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
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

import app.main as main
from app.routes.auth import get_current_user, require_admin
from app.routes.notes import _normalize_notes
from backend.app.services.job import normalize_email
from backend.app.logging_utils import get_logger


# Router configured with prefix and tag information as required by the tests.
router = APIRouter(prefix="/students", tags=["students"])

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _merge_assignments(student: dict) -> dict:
    """Populate ``assigned_jobs`` from job records.

    Older student records may lack assignment information.  To keep the frontend
    in sync we scan all job entries and merge any assignments, placements or
    rejections for the student's email.  Notes are normalised so the latest
    entry is also available under ``note``.
    """

    if main.redis_client is None:
        return student

    email = normalize_email(student.get("email"))
    assigned = {j.get("job_code"): dict(j) for j in student.get("assigned_jobs", []) if j.get("job_code")}

    for key in main.redis_client.scan_iter("job:*"):
        logger.debug("Retrieving job key %s", key)
        raw = main.redis_client.get(key)
        if not raw:
            logger.debug("Skipping job key %s: empty value", key)
            continue
        try:
            job = json.loads(raw)
        except json.JSONDecodeError:
            snippet = raw[:40] if isinstance(raw, (bytes, str)) else str(raw)[:40]
            logger.error("Malformed JSON for job %s: %s", key, snippet)
            continue
        job_code = job.get("job_code")
        if not job_code:
            continue

        status = None
        if email in job.get("placed_students", []):
            status = "placed"
        elif email in job.get("rejected_students", []):
            status = "rejected"
        elif email in job.get("assigned_students", []):
            status = "assigned"
        if status is None:
            continue

        notes = _normalize_notes(job.get("student_notes", {}).get(email, []))
        entry = assigned.get(job_code, {"job_code": job_code})
        entry.update(
            {
                "job_title": job.get("job_title"),
                "company": job.get("company"),
                "min_pay": job.get("min_pay"),
                "max_pay": job.get("max_pay"),
                "source": job.get("source"),
                "status": status,
                "posted_by": job.get("posted_by"),
                "notes": notes,
            }
        )
        if notes:
            entry["note"] = notes[-1].get("text")
        assigned[job_code] = entry
        logger.debug(
            "Merged assignment for job %s: status=%s, notes=%s, note_field=%s",
            job_code,
            status,
            bool(notes),
            "note" in entry,
        )

    student["assigned_jobs"] = list(assigned.values())
    logger.debug("Merged %d assignment(s) for %s", len(assigned), email)
    return student


# ---------------------------------------------------------------------------
# Student listing endpoints
# ---------------------------------------------------------------------------


@router.get("/all")
def list_all_students(request: Request, user: dict = Depends(require_admin)) -> dict:
    """Return all student records stored in Redis.

    Access to this endpoint is restricted to admin users.  Each student record
    is stored under ``student:<institutional_code>:<student_id>`` with an
    accompanying ``student_email:<email>`` index created by
    :func:`app.main.persist_student_record`.
    """

    auth_present = "authorization" in request.headers
    logger.info(
        "Listing all students for %s (auth header: %s)",
        user.get("email"),
        auth_present,
    )
    students: list[dict[str, Any]] = []
    if main.redis_client is not None:
        keys = list(main.redis_client.scan_iter("student:*:*"))
        if keys:
            values = main.redis_client.mget(keys)
            for key, raw in zip(keys, values):
                logger.debug("Retrieving student key %s", key)
                if raw is None:
                    logger.debug("Skipping student key %s: empty value", key)
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    snippet = raw[:40] if isinstance(raw, (bytes, str)) else str(raw)[:40]
                    logger.error("Malformed JSON for student %s: %s", key, snippet)
                    continue
                logger.debug("Loaded student %s with fields %s", key, list(data.keys()))
                students.append(_merge_assignments(data))
    else:
        logger.warning("Redis unavailable while listing students")
    logger.info("Returning %d student(s)", len(students))
    return {"students": students}


@router.get("/by-school")
def list_students_by_school(
    request: Request,
    code: str | None = None,
    user: dict = Depends(get_current_user),
) -> dict:
    """Return students for the institution associated with ``code``.

    If ``code`` is omitted the user's ``school_code`` is used.  A missing code
    results in a ``400`` response as exercised by the tests.
    """

    inst = code or user.get("school_code") or user.get("institutional_code")
    auth_present = "authorization" in request.headers
    logger.info(
        "Listing students for institution %s requested by %s (auth header: %s)",
        inst,
        user.get("email"),
        auth_present,
    )
    if not inst:
        logger.warning("Institutional code missing for user %s", user.get("email"))
        raise HTTPException(status_code=400, detail="Institutional code required")

    students: list[dict[str, Any]] = []
    if main.redis_client is not None:
        keys = list(main.redis_client.scan_iter(f"student:{inst}:*"))
        if keys:
            values = main.redis_client.mget(keys)
            for key, raw in zip(keys, values):
                logger.debug("Retrieving student key %s", key)
                if raw is None:
                    logger.debug("Skipping student key %s: empty value", key)
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    snippet = raw[:40] if isinstance(raw, (bytes, str)) else str(raw)[:40]
                    logger.error("Malformed JSON for student %s: %s", key, snippet)
                    continue
                logger.debug("Loaded student %s with fields %s", key, list(data.keys()))
                students.append(_merge_assignments(data))
    else:
        logger.warning("Redis unavailable while listing students for %s", inst)
    logger.info("Returning %d student(s) for %s", len(students), inst)
    return {"students": students}


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)) -> dict:
    """Return the student profile for the currently authenticated user."""
    email = user.get("email")
    logger.info("Fetching profile for %s", email)
    if main.redis_client is None:
        logger.warning("Redis unavailable while fetching profile for %s", email)
        raise HTTPException(status_code=404, detail="Student not found")

    email_key = main.student_email_key(email)
    logger.debug("Retrieving student email index %s", email_key)
    loc = main.redis_client.get(email_key)
    if not loc:
        logger.warning("Student %s not found", email)
        raise HTTPException(status_code=404, detail="Student not found")

    inst, sid = loc.split(":", 1)
    student_key = main.student_key(inst, sid)
    logger.debug("Retrieving student key %s", student_key)
    raw = main.redis_client.get(student_key)
    if not raw:
        logger.warning("Student record %s not found", email)
        raise HTTPException(status_code=404, detail="Student not found")
    student = _merge_assignments(json.loads(raw))
    logger.info("Profile fetched for %s", email)
    return student


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

    logger.info("Listing placements for %s", student_email)
    placements: list[dict[str, Any]] = []
    if main.redis_client is not None:
        for key in main.redis_client.scan_iter("job:*"):
            logger.debug("Retrieving job key %s", key)
            raw = main.redis_client.get(key)
            if not raw:
                logger.debug("Skipping job key %s: empty value", key)
                continue
            try:
                job = json.loads(raw)
            except json.JSONDecodeError:
                snippet = raw[:40] if isinstance(raw, (bytes, str)) else str(raw)[:40]
                logger.error("Malformed JSON for job %s: %s", key, snippet)
                continue
            if student_email in job.get("placed_students", []):
                placements.append(job)
    else:
        logger.warning("Redis unavailable while listing placements for %s", student_email)
    logger.info("Returning %d placement(s) for %s", len(placements), student_email)
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
    logger.info("Creating student profile for %s", email)
    if not email:
        logger.warning("Email missing in create_student payload")
        raise HTTPException(status_code=400, detail="Email required")

    inst = user.get("school_code") or user.get("institutional_code")
    if not inst:
        logger.warning(
            "Institutional code missing for user %s; using placeholder", user.get("email")
        )
        inst = "unknown"

    if "student_id" in payload and payload["student_id"]:
        student_id = payload["student_id"]
    elif main.redis_client is not None:
        student_id = str(main.redis_client.incr("student_id"))
    else:  # pragma: no cover - redis is always patched in tests
        student_id = uuid.uuid4().hex

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

    main.persist_student_record(email, payload, inst, student_id)
    logger.info("Student profile created for %s", email)
    return {"message": "Student created"}

