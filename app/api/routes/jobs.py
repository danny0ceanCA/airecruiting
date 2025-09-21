import json
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import redis
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.config import ADMIN_ROLES, EMAIL_OPEN_TOKENS_KEY, SITE_BASE_URL
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.db.redis_client import get_queue, redis_client
from app.models.job import JobCodeRequest, JobRequest
from app.services.core_utils import license_to_code, normalize_email, resolve_student_key, user_key
from app.services.description import generate_job_description_html
from app.services.jobs import (
    _add_student_job,
    _fetch_student_jobs,
    _normalize_notes,
    _remove_student_job,
)
from app.services.matching import match_worker
from app.services.email import send_email

router = APIRouter()

logger = get_logger(__name__)

@router.post("/jobs")
def create_job(job: JobRequest, current_user: dict = Depends(get_current_user)):
    generated_code = str(uuid.uuid4())[:8]
    key = f"job:{generated_code}"
    # Ensure the generated job code does not collide with an existing key
    while redis_client.exists(key):
        generated_code = str(uuid.uuid4())[:8]
        key = f"job:{generated_code}"

    data = job.model_dump(mode="json")
    data["required_license"] = license_to_code(data.get("required_license"))
    user_email = current_user.get("sub")
    user_role = current_user.get("role")
    # Autopopulate source for recruiters if missing or blank
    if user_role == "recruiter" or not data.get("source"):
        raw_user = redis_client.get(f"user:{user_email}")
        label = None
        if raw_user:
            try:
                udata = json.loads(raw_user)
                label = udata.get("school_label")
            except Exception:
                label = None
        if label:
            data["source"] = label.split("-", 1)[-1] if "-" in label else label

    if data.get("external_apply_url") and not data.get("source"):
        raise HTTPException(status_code=400, detail="Source required when external apply URL is provided")

    data["job_code"] = generated_code
    data["posted_by"] = user_email
    data["timestamp"] = datetime.now().isoformat()
    data.setdefault("assigned_students", [])
    data.setdefault("placed_students", [])
    data.setdefault("uninterested_students", [])
    data.setdefault("rejected_students", [])
    data.setdefault("student_notes", {})

    redis_client.set(key, json.dumps(data))
    logger.info("Stored job at %s: %s", key, data)
    return {"message": "Job stored", "job_code": generated_code}

@router.put("/jobs/{job_code}")
def update_job(job_code: str, updated: dict, token_data: dict = Depends(get_current_user)):
    key = f"job:{job_code}"
    raw = redis_client.get(key)

    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        job = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Malformed job record")

    if token_data.get("role") not in ADMIN_ROLES and token_data.get("sub") != job.get("posted_by"):
        raise HTTPException(status_code=403, detail="Not authorized to edit this job")

    if "min_pay" in updated or "max_pay" in updated:
        min_pay = float(updated.get("min_pay", job.get("min_pay", 0)))
        max_pay = float(updated.get("max_pay", job.get("max_pay", 0)))
        if min_pay <= 0 or max_pay <= 0 or min_pay > max_pay:
            raise HTTPException(status_code=400, detail="Invalid pay range")
    if "required_license" in updated:
        updated["required_license"] = license_to_code(updated["required_license"])
    if "external_apply_url" in updated:
        parsed = urlparse(updated["external_apply_url"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=400, detail="Invalid external_apply_url")
        if not (updated.get("source") or job.get("source")):
            raise HTTPException(status_code=400, detail="Source required when external_apply_url is provided")
    job.update(updated)
    redis_client.set(key, json.dumps(job))
    logger.info("✏️ Updated job %s", job_code)
    return {"message": "Job updated"}

@router.post("/match")
def match_job(
    req: JobCodeRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Enqueue a matching job and return immediately."""
    enq_time = datetime.now().timestamp()
    if hasattr(redis_client, "pipeline"):
        get_queue().enqueue(
            match_worker,
            req.job_code,
            False,
            enq_time,
            job_timeout=600,
            meta={"request_id": request.state.request_id},
        )
        return {"message": "Match job queued"}
    else:
        matches = match_worker(req.job_code, False, enq_time)
        return {"matches": matches}

@router.post("/rematches/{job_code}")
def rematch_job(
    job_code: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Queue a rematch computation without notifying students."""
    enq_time = datetime.now().timestamp()
    if hasattr(redis_client, "pipeline"):
        get_queue().enqueue(
            match_worker,
            job_code,
            False,
            enq_time,
            job_timeout=600,
            meta={"request_id": request.state.request_id},
        )
        return {"message": "Rematch queued"}
    else:
        matches = match_worker(job_code, False, enq_time)
        return {"matches": matches}

@router.get("/match/{job_code}")
def get_match_results(job_code: str, current_user: dict = Depends(get_current_user)):
    key = f"match_results:{job_code}"
    results_json = redis_client.get(key)

    if results_json is None:
        logger.warning("⚠️ No match results found for job %s", job_code)
        return {"matches": []}

    try:
        matches = {m["email"]: m for m in json.loads(results_json)}
        logger.info("📦 Returning %s stored matches for job %s", len(matches), job_code)

        # Ensure each match has first and last name fields
        for m in matches.values():
            if "first_name" not in m or "last_name" not in m:
                parts = m.get("name", "").split(" ", 1)
                m.setdefault("first_name", parts[0] if parts else "")
                m.setdefault("last_name", parts[1] if len(parts) > 1 else "")

        job_raw = redis_client.get(f"job:{job_code}")
        if not job_raw:
            raise HTTPException(status_code=404, detail="Job not found")

        job = json.loads(job_raw)
        assigned = set(job.get("assigned_students", []))
        placed = set(job.get("placed_students", []))
        rejected = set(job.get("rejected_students", []))

        existing = set(matches)
        for email in assigned | placed | rejected:
            if email not in existing:
                udata = json.loads(redis_client.get(f"user:{email}") or "{}")
                first = udata.get("first_name", "")
                last = udata.get("last_name", "")
                name = f"{first} {last}".strip()
                matches[email] = {
                    "name": name,
                    "first_name": first,
                    "last_name": last,
                    "email": email,
                    "score": None,
                }

        for email, m in matches.items():
            if email in placed:
                m["status"] = "placed"
            elif email in assigned:
                m["status"] = "assigned"
            elif email in rejected:
                m["status"] = "rejected"
            else:
                m["status"] = None

            notes_raw = job.get("student_notes", {}).get(email, [])
            notes, latest_note = _normalize_notes(notes_raw)
            m["notes"] = notes
            if latest_note is not None:
                m["note"] = latest_note

        return {"matches": list(matches.values())}
    except Exception as e:
        logger.error("❌ Failed to load match results for %s: %s", job_code, e)
        return {"matches": []}

@router.get("/has-match/{job_code}")
def has_match_data(job_code: str):
    key = f"match_results:{job_code}"
    results_json = redis_client.get(key)

    if results_json is not None:
        try:
            results = json.loads(results_json)
        except json.JSONDecodeError:
            results = results_json
        logger.info("✅ Returning match results from Redis for job %s", job_code)
        return {"has_match": True, "results": results}

    job = get_queue().fetch_job(job_code)
    if job is None:
        return {"has_match": False, "results": None}

    status = job.get_status(refresh=False)
    if status == "finished":
        return {"has_match": True, "results": job.result}

    return {"has_match": False, "results": None}

@router.get("/jobs")
def list_jobs(current_user: dict = Depends(get_current_user)):
    jobs = []
    for key in redis_client.scan_iter("job:*"):
        job_data = redis_client.get(key)
        if job_data:
            job = json.loads(job_data)
            job.setdefault("assigned_students", [])
            job.setdefault("placed_students", [])
            job.setdefault("uninterested_students", [])
            job.setdefault("rejected_students", [])
            job.setdefault("student_notes", {})
            jobs.append(job)
    logger.info("Returning %s jobs from Redis", len(jobs))
    return {"jobs": jobs}

@router.delete("/jobs/{job_code}")
def delete_job(job_code: str, token_data: dict = Depends(get_current_user)):
    if token_data.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    job_key = f"job:{job_code}"
    match_key = f"match_results:{job_code}"

    if not redis_client.exists(job_key):
        raise HTTPException(status_code=404, detail="Job not found")

    redis_client.delete(job_key)
    redis_client.delete(match_key)

    return {"message": f"Job {job_code} deleted successfully"}

@router.post("/place")
def place_student(data: dict, token_data: dict = Depends(get_current_user)):
    if token_data.get("role") not in {"admin", "junior_admin", "career"}:
        raise HTTPException(status_code=403, detail="Not authorized to place students")
    job_code = data["job_code"]
    student_email = normalize_email(data["student_email"])
    key = f"job:{job_code}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    job = json.loads(raw)
    job.setdefault("placed_students", [])
    job.setdefault("assigned_students", [])

    if student_email not in job["placed_students"]:
        job["placed_students"].append(student_email)
    if student_email in job["assigned_students"]:
        job["assigned_students"].remove(student_email)
        _remove_student_job(student_email, job_code, "assigned")

    _remove_student_job(student_email, job_code, "rejected")
    _remove_student_job(student_email, job_code, "uninterested")
    _add_student_job(student_email, job_code, "placed")

    redis_client.set(key, json.dumps(job))
    return {"message": f"Placed {student_email}"}

@router.post("/assign")
def assign_student(data: dict, token_data: dict = Depends(get_current_user)):
    job_code = data["job_code"]
    student_email = normalize_email(data["student_email"])
    note = data.get("note")
    key = f"job:{job_code}"
    try:
        raw = redis_client.get(key)
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        job = json.loads(raw)
        if not isinstance(job, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid student_notes format")
    role = token_data.get("role")
    if role == "recruiter" and job.get("posted_by") != token_data.get("sub"):
        raise HTTPException(status_code=403, detail="Not authorized to modify this job")
    if role not in ADMIN_ROLES | {"recruiter"}:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    job.setdefault("assigned_students", [])
    if student_email not in job["assigned_students"]:
        job["assigned_students"].append(student_email)
        _add_student_job(student_email, job_code, "assigned")
        _remove_student_job(student_email, job_code, "rejected")
        _remove_student_job(student_email, job_code, "uninterested")

    if note is not None:
        note_obj = {
            "text": note,
            "author": token_data["sub"],
            "timestamp": datetime.utcnow().isoformat(),
        }
        raw_notes = job.get("student_notes", {})
        if isinstance(raw_notes, str):
            try:
                notes_map = json.loads(raw_notes)
                if not isinstance(notes_map, dict):
                    raise ValueError
            except (json.JSONDecodeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid student_notes format")
        elif isinstance(raw_notes, dict):
            notes_map = raw_notes
        else:
            raise HTTPException(status_code=400, detail="Invalid student_notes format")

        existing = notes_map.get(student_email)
        if isinstance(existing, str):
            existing = [{"text": existing}]
        elif not isinstance(existing, list):
            existing = []
        existing.append(note_obj)
        notes_map[student_email] = existing
        job["student_notes"] = notes_map

    try:
        redis_client.set(key, json.dumps(job))
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    resp = {"message": f"Assigned {student_email}"}
    if note is not None:
        resp["notes"] = job["student_notes"][student_email]
    return resp

@router.post("/reject-assigned")
def reject_assigned_student(data: dict, token_data: dict = Depends(get_current_user)):
    """Remove an assigned student from a job and record a note."""
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    note = data.get("note")
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")

    key = f"job:{job_code}"
    try:
        raw = redis_client.get(key)
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        job = json.loads(raw)
        if not isinstance(job, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid student_notes format")
    role = token_data.get("role")
    if role == "recruiter" and job.get("posted_by") != token_data.get("sub"):
        raise HTTPException(status_code=403, detail="Not authorized to modify this job")
    if role not in ADMIN_ROLES | {"recruiter"}:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    job.setdefault("assigned_students", [])
    job.setdefault("rejected_students", [])

    if student_email in job["assigned_students"]:
        job["assigned_students"].remove(student_email)
        _remove_student_job(student_email, job_code, "assigned")
    if student_email not in job["rejected_students"]:
        job["rejected_students"].append(student_email)
        _add_student_job(student_email, job_code, "rejected")
    _remove_student_job(student_email, job_code, "placed")
    _remove_student_job(student_email, job_code, "uninterested")

    if note is not None:
        note_obj = {
            "text": note,
            "author": token_data["sub"],
            "timestamp": datetime.utcnow().isoformat(),
        }
        raw_notes = job.get("student_notes", {})
        if isinstance(raw_notes, str):
            try:
                notes_map = json.loads(raw_notes)
                if not isinstance(notes_map, dict):
                    raise ValueError
            except (json.JSONDecodeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid student_notes format")
        elif isinstance(raw_notes, dict):
            notes_map = raw_notes
        else:
            raise HTTPException(status_code=400, detail="Invalid student_notes format")

        existing = notes_map.get(student_email)
        if isinstance(existing, str):
            existing = [{"text": existing}]
        elif not isinstance(existing, list):
            existing = []
        existing.append(note_obj)
        notes_map[student_email] = existing
        job["student_notes"] = notes_map

    try:
        redis_client.set(key, json.dumps(job))
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    resp = {"message": "Student rejected"}
    if note is not None:
        resp["notes"] = job["student_notes"][student_email]
    return resp

@router.post("/student-note")
def student_note(data: dict, token_data: dict = Depends(get_current_user)):
    """Create or update a note for a student on a job."""
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    note = data.get("note")
    if not job_code or not student_email or note is None:
        raise HTTPException(status_code=400, detail="Missing job_code, student_email, or note")

    key = f"job:{job_code}"
    try:
        raw = redis_client.get(key)
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        job = json.loads(raw)
        if not isinstance(job, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid student_notes format")

    role = token_data.get("role")
    if role in ADMIN_ROLES:
        pass
    elif role == "recruiter" and (
        job.get("posted_by") == token_data.get("sub")
        and student_email in job.get("assigned_students", [])
    ):
        pass
    else:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    # Ensure student_notes is a dict; handle both dict and JSON string forms
    raw_notes = job.get("student_notes", {})
    if isinstance(raw_notes, str):
        try:
            notes_map = json.loads(raw_notes)
            if not isinstance(notes_map, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid student_notes format")
    elif isinstance(raw_notes, dict):
        notes_map = raw_notes
    else:
        raise HTTPException(status_code=400, detail="Invalid student_notes format")

    note_obj = {
        "text": note,
        "author": token_data["sub"],
        "timestamp": datetime.utcnow().isoformat(),
    }
    existing = notes_map.get(student_email)
    if isinstance(existing, str):
        existing = [{"text": existing}]
    elif not isinstance(existing, list):
        existing = []
    existing.append(note_obj)
    notes_map[student_email] = existing
    job["student_notes"] = notes_map

    try:
        redis_client.set(key, json.dumps(job))
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    return {"email": student_email, "notes": notes_map[student_email]}

@router.put("/student-note")
def update_student_note(data: dict, token_data: dict = Depends(get_current_user)):
    """Update an existing note for a student on a job."""
    if token_data.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    index = data.get("index")
    note = data.get("note")
    if not job_code or not student_email or note is None or index is None:
        raise HTTPException(
            status_code=400,
            detail="Missing job_code, student_email, index, or note",
        )
    try:
        index = int(index)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid index")

    key = f"job:{job_code}"
    try:
        raw = redis_client.get(key)
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        job = json.loads(raw)
        if not isinstance(job, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid student_notes format")

    raw_notes = job.get("student_notes", {})
    if isinstance(raw_notes, str):
        try:
            notes_map = json.loads(raw_notes)
            if not isinstance(notes_map, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid student_notes format")
    elif isinstance(raw_notes, dict):
        notes_map = raw_notes
    else:
        raise HTTPException(status_code=400, detail="Invalid student_notes format")

    existing = notes_map.get(student_email)
    if isinstance(existing, str):
        existing = [{"text": existing}]
    elif not isinstance(existing, list):
        existing = []
    if index < 0 or index >= len(existing):
        raise HTTPException(status_code=404, detail="Note not found")

    note_obj = {
        "text": note,
        "author": token_data["sub"],
        "timestamp": datetime.utcnow().isoformat(),
    }
    existing[index] = note_obj
    notes_map[student_email] = existing
    job["student_notes"] = notes_map

    try:
        redis_client.set(key, json.dumps(job))
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    return {"email": student_email, "notes": notes_map[student_email]}

@router.delete("/student-note")
def delete_student_note(data: dict, token_data: dict = Depends(get_current_user)):
    """Delete a note for a student on a job by index."""
    if token_data.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    index = data.get("index")
    if not job_code or not student_email or index is None:
        raise HTTPException(
            status_code=400, detail="Missing job_code, student_email, or index"
        )
    try:
        index = int(index)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid index")

    key = f"job:{job_code}"
    try:
        raw = redis_client.get(key)
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        job = json.loads(raw)
        if not isinstance(job, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid student_notes format")

    raw_notes = job.get("student_notes", {})
    if isinstance(raw_notes, str):
        try:
            notes_map = json.loads(raw_notes)
            if not isinstance(notes_map, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid student_notes format")
    elif isinstance(raw_notes, dict):
        notes_map = raw_notes
    else:
        raise HTTPException(status_code=400, detail="Invalid student_notes format")

    existing = notes_map.get(student_email)
    if isinstance(existing, str):
        existing = [{"text": existing}]
    elif not isinstance(existing, list):
        existing = []
    if index < 0 or index >= len(existing):
        raise HTTPException(status_code=404, detail="Note not found")

    existing.pop(index)
    notes_map[student_email] = existing
    job["student_notes"] = notes_map

    try:
        redis_client.set(key, json.dumps(job))
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    return {"email": student_email, "notes": notes_map.get(student_email, [])}

@router.post("/not-interested")
def mark_not_interested(data: dict, token_data: dict = Depends(get_current_user)):
    """Record that a student is not interested in a job."""
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")

    key = f"job:{job_code}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    job = json.loads(raw)
    job.setdefault("uninterested_students", [])
    if student_email not in job["uninterested_students"]:
        job["uninterested_students"].append(student_email)
        _add_student_job(student_email, job_code, "uninterested")

    redis_client.set(key, json.dumps(job))
    return {"message": "Not interested recorded"}

@router.post("/notify-interest")
def notify_interest(data: dict, token_data: dict = Depends(get_current_user)):
    """Notify a student that a recruiter is interested and send them a job description."""
    job_code = data.get("job_code")
    student_email = data.get("student_email")
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")

    key = f"job:{job_code}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    job = json.loads(raw)
    if student_email not in job.get("assigned_students", []) and student_email not in job.get("placed_students", []):
        raise HTTPException(status_code=400, detail="Student not assigned to job")

    desc_html, _ = generate_job_description_html(job_code, student_email)

    skey = resolve_student_key(student_email)
    student_raw = redis_client.get(skey) if skey else None
    first_name = ""
    if student_raw:
        try:
            student = json.loads(student_raw)
            first_name = student.get("first_name", "")
        except Exception:
            pass

    public_url = (
        f"{SITE_BASE_URL}/public/job-description-html/{job_code}/{student_email}"
        if SITE_BASE_URL
        else f"/public/job-description-html/{job_code}/{student_email}"
    )
    summary = (
        f"Job: {job.get('job_title')} at {job.get('source', '')} in {job.get('city', '')}, {job.get('state', '')}"
    )
    token = str(uuid.uuid4())
    external_url = job.get("external_apply_url")
    body = (
        f"Hello {first_name},\n\n"
        f"{summary}\n\n"

        "Your resume has been matched with this job.\n\n"
        f"Please review the job description here: {public_url}\n\n"
    )
    html_body = (
        f"<p>Hello {first_name},</p>"
        f"<p>{summary}</p>"
        "<p>Your resume has been matched with this job.</p>"
        f"<p>Please review the job description <a href=\"{public_url}\">here</a>.</p>"
    )
    if external_url:
        click_url = (
            f"{SITE_BASE_URL}/track/click/{token}"
            if SITE_BASE_URL
            else f"/track/click/{token}"
        )
        body += f"You must apply using the following link: {click_url}\n\n"
        html_body += (
            f"<p>You must apply using the following link: "
            f"<a href=\"{click_url}\">Apply Now</a></p>"
        )
    body += "Good Luck!\n\nSupport Team @ TalentMatch-AI"
    html_body += "<p>Good Luck!</p><p>Support Team @ TalentMatch-AI</p>"
    try:
        redis_client.hset(
            EMAIL_OPEN_TOKENS_KEY,
            token,
            json.dumps(
                {
                    "student_email": student_email,
                    "job_code": job_code,
                    "external_url": external_url,
                    "sent": datetime.now(timezone.utc).isoformat(),
                }
            ),
        )
    except Exception as e:
        logger.error("Failed to store email open token: %s", e)
    try:
        send_email(
            student_email,
            f"Job Match: {job.get('job_title')}",
            body,
            html_body=html_body,
            track_token=token,
        )
    except Exception as e:
        logger.error("Notification email failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to send notification email")

    return {"message": "Notification sent"}

@router.delete("/admin/reset-jobs")
def reset_jobs(current_user: dict = Depends(get_current_user)):
    """Delete all job postings and their stored match results."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")

    deleted = 0
    for key in list(redis_client.scan_iter("job:*")):
        redis_client.delete(key)
        deleted += 1
    for key in list(redis_client.scan_iter("match_results:*")):
        redis_client.delete(key)

    return {"message": f"Deleted {deleted} jobs and match data"}

