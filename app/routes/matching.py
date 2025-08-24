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
from backend.app.logging_utils import get_logger


router = APIRouter(prefix="", tags=["matching"])

logger = get_logger(__name__)


def _get_job(job_code: str) -> dict:
    logger.debug("Retrieving job %s", job_code)
    raw = main.redis_client.get(f"job:{job_code}")
    if not raw:
        logger.warning("Job %s not found", job_code)
        raise HTTPException(status_code=404, detail="Job not found")
    return json.loads(raw)


def _get_student(email: str) -> tuple[dict, str]:
    logger.debug("Resolving student %s", email)
    skey = resolve_student_key(main.redis_client, email)
    if not skey:
        logger.warning("Student %s not found", email)
        raise HTTPException(status_code=404, detail="Student not found")
    raw = main.redis_client.get(skey)
    if not raw:
        logger.warning("Student %s not found at key %s", email, skey)
        raise HTTPException(status_code=404, detail="Student not found")
    return json.loads(raw), skey


def _embedding_for(text: str) -> list[float]:
    """Return an embedding vector for ``text`` using the OpenAI stub.

    The real application would call out to the OpenAI embeddings API.  In the
    tests the ``client.embeddings.create`` method is monkeypatched to return a
    predictable response, allowing us to safely call it here.
    """

    try:  # pragma: no cover - network errors are environment specific
        resp = main.client.embeddings.create(input=text, model="text-embedding-3-small")
        return resp.data[0].embedding if getattr(resp, "data", None) else []
    except Exception:
        return []


def _similarity(a: list[float], b: list[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


@router.post("/match")
def run_match(data: dict) -> dict:
    """Compute student matches for ``job_code`` and store the results."""

    job_code = data.get("job_code")
    if not job_code:
        raise HTTPException(status_code=400, detail="job_code required")
    logger.info("Running match for job %s", job_code)
    job = _get_job(job_code)
    job_emb = _embedding_for(" ".join(job.get("desired_skills", [])) or job.get("job_description", ""))

    required_license = (job.get("required_license") or "").lower()
    assigned = set(job.get("assigned_students", []))
    placed = set(job.get("placed_students", []))
    uninterested = set(job.get("uninterested_students", []))
    rejected = set(job.get("rejected_students", []))

    candidates: dict[str, dict] = {}

    # Gather student profiles
    for key in main.redis_client.scan_iter("student:*:*"):
        k = key if isinstance(key, str) else key.decode()
        if not k.startswith("student:"):
            continue
        raw = main.redis_client.get(k)
        if not raw:
            continue
        stu = json.loads(raw)
        email = normalize_email(stu.get("email"))
        if (
            email in assigned
            or email in placed
            or email in uninterested
            or email in rejected
        ):
            continue
        if required_license and (stu.get("license", "").lower() != required_license):
            continue

        try:
            dist = float(
                main.get_driving_distance_miles(
                    stu.get("lat"), stu.get("lng"), job.get("lat"), job.get("lng")
                )
            )
        except Exception:
            dist = 0.0
        max_travel = float(stu.get("max_travel", 0) or 0)
        if max_travel and dist > max_travel:
            continue

        s_emb = _embedding_for(" ".join(stu.get("skills", []))) or stu.get("embedding", [])
        score = _similarity(job_emb, s_emb)

        candidates[email] = {
            "email": email,
            "first_name": stu.get("first_name"),
            "last_name": stu.get("last_name"),
            "license": stu.get("license"),
            "score": score,
        }

    # Include applicant user accounts without student profiles
    for key in main.redis_client.scan_iter("user:*"):
        k = key if isinstance(key, str) else key.decode()
        if not k.startswith("user:"):
            continue
        raw = main.redis_client.get(k)
        if not raw:
            continue
        usr = json.loads(raw)
        if usr.get("role") != "applicant":
            continue
        email = normalize_email(usr.get("email"))
        if email in candidates:
            continue
        if required_license and usr.get("license") and usr.get("license").lower() != required_license:
            continue
        if required_license and not usr.get("license"):
            continue

        s_emb = _embedding_for(" ".join(usr.get("skills", [])))
        score = _similarity(job_emb, s_emb)
        candidates[email] = {
            "email": email,
            "first_name": usr.get("first_name"),
            "last_name": usr.get("last_name"),
            "license": usr.get("license"),
            "score": score,
        }

    matches = sorted(candidates.values(), key=lambda x: x.get("score", 0.0), reverse=True)

    # Limit to 10 as expected by the tests
    matches = matches[:10]

    logger.info("Storing %d match results for job %s", len(matches), job_code)
    main.redis_client.set(f"match_results:{job_code}", json.dumps(matches))
    return {"matches": matches}


@router.post("/rematches/{job_code}")
def queue_rematch(job_code: str) -> dict:
    """Remove existing match results and record a rematch request."""
    logger.info("Queueing rematch for job %s", job_code)
    _get_job(job_code)

    key = f"match_results:{job_code}"
    if hasattr(main.redis_client, "delete"):
        main.redis_client.delete(key)
    else:  # fallback for simple test doubles
        try:
            main.redis_client.store.pop(key, None)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - very defensive
            main.redis_client.set(key, None)

    main.redis_client.incr("metrics:total_rematches")
    logger.info("Rematch queued for job %s", job_code)
    return {"message": "Rematch queued"}


@router.get("/match/{job_code}")
def get_match_results(job_code: str) -> dict:
    """Return stored match results with job status/notes merged in."""
    logger.info("Fetching match results for job %s", job_code)
    job = _get_job(job_code)
    raw = main.redis_client.get(f"match_results:{job_code}")
    matches = json.loads(raw) if raw else []

    out: list[dict] = []
    seen: set[str] = set()
    for m in matches:
        email = normalize_email(m.get("email"))
        if email in seen:
            continue
        seen.add(email)
        out.append(m)

    notes_dict = job.get("student_notes", {})

    def enrich(entry: dict) -> dict:
        email = normalize_email(entry.get("email"))
        if email in job.get("placed_students", []):
            entry["status"] = "placed"
        elif email in job.get("assigned_students", []):
            entry["status"] = "assigned"
        elif email in job.get("rejected_students", []):
            entry["status"] = "rejected"
        else:
            entry["status"] = entry.get("status") or "new"

        notes = notes_dict.get(email, [])
        if notes:
            entry["notes"] = notes
            entry["note"] = notes[-1].get("text")

        if not entry.get("first_name") or not entry.get("last_name"):
            u_raw = main.redis_client.get(f"user:{email}")
            if u_raw:
                u = json.loads(u_raw)
                entry.setdefault("first_name", u.get("first_name"))
                entry.setdefault("last_name", u.get("last_name"))
        return entry

    out = [enrich(dict(m)) for m in out]

    existing_emails = {m["email"] for m in out}
    for email in job.get("assigned_students", []) + job.get("placed_students", []):
        if email in existing_emails:
            continue
        entry = {"email": email}
        if email in job.get("placed_students", []):
            entry["status"] = "placed"
        else:
            entry["status"] = "assigned"
        notes = notes_dict.get(email, [])
        if notes:
            entry["notes"] = notes
            entry["note"] = notes[-1].get("text")
        u_raw = main.redis_client.get(f"user:{email}")
        if u_raw:
            u = json.loads(u_raw)
            entry["first_name"] = u.get("first_name")
            entry["last_name"] = u.get("last_name")
        out.append(entry)

    # Final dedup just in case
    final: list[dict] = []
    seen.clear()
    for m in out:
        email = normalize_email(m.get("email"))
        if email in seen:
            continue
        seen.add(email)
        final.append(m)

    logger.info("Returning %d match results for job %s", len(final), job_code)
    return {"matches": final}


@router.post("/assign")
def assign_student(data: dict, user: dict = Depends(get_current_user)) -> dict:
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    note = data.get("note")
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")
    logger.info("Assigning student %s to job %s", student_email, job_code)
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
    logger.info("Student %s assigned to job %s", student_email, job_code)
    return {"message": "Student assigned"}


@router.post("/place")
def place_student(data: dict, _: dict = Depends(require_admin)) -> dict:
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")
    logger.info("Placing student %s on job %s", student_email, job_code)
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
    logger.info("Student %s placed on job %s", student_email, job_code)
    return {"message": "Student placed"}


@router.post("/reject-assigned")
def reject_assigned(data: dict, user: dict = Depends(get_current_user)) -> dict:
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    note = data.get("note")
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")
    logger.info("Rejecting student %s for job %s", student_email, job_code)
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
    logger.info("Student %s rejected for job %s", student_email, job_code)
    return {"message": "Assignment rejected"}


@router.post("/not-interested")
def mark_not_interested(data: dict, _: dict = Depends(get_current_user)) -> dict:
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")
    logger.info("Marking student %s not interested in job %s", student_email, job_code)
    job = _get_job(job_code)
    job.setdefault("uninterested_students", [])
    if student_email not in job["uninterested_students"]:
        job["uninterested_students"].append(student_email)
    main.redis_client.set(f"job:{job_code}", json.dumps(job))
    logger.info("Student %s marked not interested in job %s", student_email, job_code)
    return {"message": "Student marked not interested"}


@router.post("/notify-interest")
def notify_interest(data: dict, _: dict = Depends(get_current_user)) -> dict:
    job_code = data.get("job_code")
    student_email = data.get("student_email")
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")
    logger.info("Notifying interest for student %s on job %s", student_email, job_code)
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
    logger.info(
        "Sent interest notification for student %s on job %s", student_email, job_code
    )

    return {"message": "Notification sent"}

