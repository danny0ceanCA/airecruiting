"""Endpoints for manipulating student notes.

These endpoints were originally defined directly in :mod:`app.main`.  They are
now collected under a dedicated router with the ``/notes`` prefix so they can be
included into the application without additional arguments.  Notes are stored on
both the job record and, when present, the student's assigned job entry.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

import app.main as main
from app.routes.auth import get_current_user, require_admin
from backend.app.services.job import normalize_email, resolve_student_key
from backend.app.logging_utils import get_logger


router = APIRouter(prefix="/notes", tags=["notes"])

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _normalize_notes(notes: Any) -> list[dict[str, Any]]:
    """Return ``notes`` as a list of ``{"text": ..., "posted_by": ...}``.

    Legacy records may store notes as plain strings or as a mix of strings and
    dictionaries.  This helper ensures a consistent structure before the
    endpoints manipulate the note list.
    """

    if isinstance(notes, str):
        return [{"text": notes}]
    out: list[dict[str, Any]] = []
    for n in notes or []:
        if isinstance(n, dict):
            out.append({"text": n.get("text", ""), "posted_by": n.get("posted_by")})
        else:
            out.append({"text": str(n)})
    return out


def _get_job(job_code: str) -> dict:
    logger.debug("Retrieving job %s for notes", job_code)
    raw = main.redis_client.get(f"job:{job_code}")
    if not raw:
        logger.warning("Job %s not found when accessing notes", job_code)
        raise HTTPException(status_code=404, detail="Job not found")
    return json.loads(raw)


def _get_student(email: str) -> tuple[dict | None, str | None]:
    logger.debug("Resolving student %s for notes", email)
    skey = resolve_student_key(main.redis_client, email)
    if not skey:
        logger.debug("No student key found for %s", email)
        return None, None
    raw = main.redis_client.get(skey)
    if not raw:
        logger.debug("Student key %s resolved for %s but no record found", skey, email)
        return None, skey
    return json.loads(raw), skey


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/student-note")
def add_student_note(data: dict, user: dict = Depends(get_current_user)) -> dict:
    """Append a note for ``student_email`` on ``job_code``."""

    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    note_text = data.get("note")
    if not job_code or not student_email or not note_text:
        raise HTTPException(status_code=400, detail="Missing job_code, student_email or note")
    logger.info("Adding note for student %s on job %s", student_email, job_code)
    job = _get_job(job_code)
    if user.get("role") != "admin":
        if job.get("posted_by") != user.get("email"):
            raise HTTPException(status_code=403, detail="Forbidden")
        if student_email not in job.get("assigned_students", []):
            raise HTTPException(status_code=403, detail="Forbidden")

    notes_dict = job.setdefault("student_notes", {})
    existing = _normalize_notes(notes_dict.get(student_email, []))
    existing.append({"text": note_text, "posted_by": user.get("email")})
    notes_dict[student_email] = existing
    main.redis_client.set(f"job:{job_code}", json.dumps(job))

    student, skey = _get_student(student_email)
    if student and skey:
        assigned = student.setdefault("assigned_jobs", [])
        entry = next((j for j in assigned if j.get("job_code") == job_code), None)
        if entry:
            entry_notes = _normalize_notes(entry.get("notes", []))
            entry_notes.append({"text": note_text, "posted_by": user.get("email")})
            entry["notes"] = entry_notes
            main.redis_client.set(skey, json.dumps(student))

    logger.info("Added note for student %s on job %s", student_email, job_code)
    return {"notes": notes_dict[student_email]}


@router.put("/student-note")
def update_student_note(data: dict, _: dict = Depends(require_admin)) -> dict:
    """Update an existing note identified by ``index``."""

    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    index = data.get("index")
    note_text = data.get("note")
    if job_code is None or student_email is None or index is None or note_text is None:
        raise HTTPException(status_code=400, detail="Missing fields")
    logger.info(
        "Updating note %s for student %s on job %s", index, student_email, job_code
    )
    job = _get_job(job_code)
    notes_dict = job.setdefault("student_notes", {})
    notes = _normalize_notes(notes_dict.get(student_email, []))
    if index < 0 or index >= len(notes):
        raise HTTPException(status_code=404, detail="Note not found")
    notes[index]["text"] = note_text
    notes_dict[student_email] = notes
    main.redis_client.set(f"job:{job_code}", json.dumps(job))

    student, skey = _get_student(student_email)
    if student and skey:
        assigned = student.setdefault("assigned_jobs", [])
        entry = next((j for j in assigned if j.get("job_code") == job_code), None)
        if entry:
            entry_notes = _normalize_notes(entry.get("notes", []))
            if 0 <= index < len(entry_notes):
                entry_notes[index]["text"] = note_text
                entry["notes"] = entry_notes
                main.redis_client.set(skey, json.dumps(student))

    logger.info(
        "Updated note %s for student %s on job %s", index, student_email, job_code
    )
    return {"notes": notes}


@router.delete("/student-note")
def delete_student_note(data: dict, _: dict = Depends(require_admin)) -> dict:
    """Remove a note identified by ``index``."""

    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    index = data.get("index")
    if job_code is None or student_email is None or index is None:
        raise HTTPException(status_code=400, detail="Missing fields")
    logger.info(
        "Deleting note %s for student %s on job %s", index, student_email, job_code
    )
    job = _get_job(job_code)
    notes_dict = job.setdefault("student_notes", {})
    notes = _normalize_notes(notes_dict.get(student_email, []))
    if index < 0 or index >= len(notes):
        raise HTTPException(status_code=404, detail="Note not found")
    notes.pop(index)
    if notes:
        notes_dict[student_email] = notes
    else:
        notes_dict.pop(student_email, None)
    main.redis_client.set(f"job:{job_code}", json.dumps(job))

    student, skey = _get_student(student_email)
    if student and skey:
        assigned = student.setdefault("assigned_jobs", [])
        entry = next((j for j in assigned if j.get("job_code") == job_code), None)
        if entry:
            entry_notes = _normalize_notes(entry.get("notes", []))
            if 0 <= index < len(entry_notes):
                entry_notes.pop(index)
            if entry_notes:
                entry["notes"] = entry_notes
            else:
                entry.pop("notes", None)
            main.redis_client.set(skey, json.dumps(student))

    logger.info(
        "Deleted note %s for student %s on job %s", index, student_email, job_code
    )
    return {"notes": notes_dict.get(student_email, [])}

