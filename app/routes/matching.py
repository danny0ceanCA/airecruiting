"""Endpoints related to matching students with jobs."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

import app.main as main
from app.routes.auth import get_current_user, require_admin
from backend.app.services.job import (
    generate_job_description_html,
    normalize_email,
    resolve_student_key,
)


router = APIRouter(prefix="", tags=["matching"])


def _get_job(job_code: str) -> dict:
    raw = main.redis_client.get(f"job:{job_code}")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")
    return json.loads(raw)


def _get_student(email: str) -> tuple[dict, str]:
    skey = resolve_student_key(main.redis_client, email)
    if not skey:
        raise HTTPException(status_code=404, detail="Student not found")
    raw = main.redis_client.get(skey)
    if not raw:
        raise HTTPException(status_code=404, detail="Student not found")
    return json.loads(raw), skey


@router.post("/assign")
def assign_student(data: dict, user: dict = Depends(get_current_user)) -> dict:
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    note = data.get("note")
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")

    job = _get_job(job_code)
    job.setdefault("assigned_students", [])
    if student_email not in job["assigned_students"]:
        job["assigned_students"].append(student_email)
    if note:
        notes = job.setdefault("student_notes", {})
        notes.setdefault(student_email, [])
        notes[student_email].append({"text": note, "posted_by": user.get("email")})
    main.redis_client.set(f"job:{job_code}", json.dumps(job))

    student, skey = _get_student(student_email)
    assigned = student.setdefault("assigned_jobs", [])
    entry = next((j for j in assigned if j.get("job_code") == job_code), None)
    if not entry:
        entry = {
            "job_code": job_code,
            "status": "assigned",
            "notes": [],
            "posted_by": job.get("posted_by"),
        }
        assigned.append(entry)
    else:
        entry["status"] = "assigned"
    if note:
        entry.setdefault("notes", []).append({"text": note, "posted_by": user.get("email")})
    main.redis_client.set(skey, json.dumps(student))

    return {"message": "Student assigned"}


@router.post("/place")
def place_student(data: dict, _: dict = Depends(require_admin)) -> dict:
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")

    job = _get_job(job_code)
    job.setdefault("placed_students", [])
    if student_email not in job["placed_students"]:
        job["placed_students"].append(student_email)
    if student_email in job.get("assigned_students", []):
        job["assigned_students"].remove(student_email)
    main.redis_client.set(f"job:{job_code}", json.dumps(job))

    student, skey = _get_student(student_email)
    assigned = student.setdefault("assigned_jobs", [])
    entry = next((j for j in assigned if j.get("job_code") == job_code), None)
    if entry:
        entry["status"] = "placed"
    else:
        assigned.append(
            {
                "job_code": job_code,
                "status": "placed",
                "notes": [],
                "posted_by": job.get("posted_by"),
            }
        )
    main.redis_client.set(skey, json.dumps(student))
    return {"message": "Student placed"}


@router.post("/reject-assigned")
def reject_assigned(data: dict, user: dict = Depends(get_current_user)) -> dict:
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    note = data.get("note")
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")

    job = _get_job(job_code)
    if student_email in job.get("assigned_students", []):
        job["assigned_students"].remove(student_email)
    job.setdefault("rejected_students", [])
    if student_email not in job["rejected_students"]:
        job["rejected_students"].append(student_email)
    if note:
        notes = job.setdefault("student_notes", {})
        notes.setdefault(student_email, [])
        notes[student_email].append({"text": note, "posted_by": user.get("email")})
    main.redis_client.set(f"job:{job_code}", json.dumps(job))

    student, skey = _get_student(student_email)
    assigned = student.setdefault("assigned_jobs", [])
    entry = next((j for j in assigned if j.get("job_code") == job_code), None)
    if not entry:
        entry = {
            "job_code": job_code,
            "status": "rejected",
            "notes": [],
            "posted_by": job.get("posted_by"),
        }
        assigned.append(entry)
    else:
        entry["status"] = "rejected"
    if note:
        entry.setdefault("notes", []).append({"text": note, "posted_by": user.get("email")})
    main.redis_client.set(skey, json.dumps(student))

    return {"message": "Assignment rejected"}


@router.post("/not-interested")
def mark_not_interested(data: dict, _: dict = Depends(get_current_user)) -> dict:
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")

    job = _get_job(job_code)
    job.setdefault("uninterested_students", [])
    if student_email not in job["uninterested_students"]:
        job["uninterested_students"].append(student_email)
    main.redis_client.set(f"job:{job_code}", json.dumps(job))
    return {"message": "Student marked not interested"}


@router.post("/notify-interest")
def notify_interest(data: dict, _: dict = Depends(get_current_user)) -> dict:
    job_code = data.get("job_code")
    student_email = data.get("student_email")
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")

    job = _get_job(job_code)
    student_email = normalize_email(student_email)
    if student_email not in job.get("assigned_students", []) and student_email not in job.get("placed_students", []):
        raise HTTPException(status_code=400, detail="Student not assigned to job")

    generate_job_description_html(main.client, main.redis_client, job_code, student_email)

    skey = resolve_student_key(main.redis_client, student_email)
    student_raw = main.redis_client.get(skey) if skey else None
    first_name = ""
    if student_raw:
        try:
            student = json.loads(student_raw)
            first_name = student.get("first_name", "")
        except Exception:
            pass

    public_url = f"/jobs/public/job-description-html/{job_code}/{student_email}"
    body = (
        f"Hello {first_name},\n\n"
        "Your resume has been matched with a job and the recruiter has reviewed your resume.\n\n"
        "You are receiving this email because the Recruiter would like to notify you that you are a match "
        "and will be contacting you to discuss your resume.\n\n"
        f"Please review the job description here: {public_url}\n\n"
        "Good Luck!\n\n"
        "Support Team @ TalentMatch-AI"
    )

    main.send_email(
        student_email,
        f"Recruiter Interest: {job.get('job_title')}",
        body,
    )

    return {"message": "Notification sent"}

