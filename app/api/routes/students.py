import csv
import json
import os
from datetime import datetime, timezone
from io import StringIO
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.core.config import ADMIN_ROLES, client
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.db.redis_client import redis_client
from app.models.student import StudentRequest
from app.services.core_utils import (
    all_school_codes,
    generate_student_id,
    get_school_label,
    license_to_code,
    normalize_email,
    persist_student_record,
    resolve_student_key,
    student_email_key,
    student_key,
    user_key,
    find_user_key,
)
from app.services.embeddings import ensure_index, rebuild_vector_index, vector_emails, vector_index
from app.services.jobs import _fetch_student_jobs, _student_job_key

router = APIRouter()

logger = get_logger(__name__)

@router.post("/students")
async def create_student(request: Request, current_user: dict = Depends(get_current_user)):
    content_type = request.headers.get("content-type", "")
    resume_file: UploadFile | None = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        resume_file = form.get("resume")
        skills_field = form.get("skills", "")
        student_data = StudentRequest(
            first_name=form.get("first_name"),
            last_name=form.get("last_name"),
            email=form.get("email"),
            phone=form.get("phone"),
            license=form.get("license") or form.get("education_level"),
            skills=[s.strip() for s in skills_field.split(",") if s.strip()],
            experience_summary=form.get("experience_summary"),
            interests=form.get("interests"),
            city=form.get("city"),
            state=form.get("state"),
            lat=float(form.get("lat")),
            lng=float(form.get("lng")),
            max_travel=float(form.get("max_travel")),
        )
    else:
        body = await request.json()
        student_data = StudentRequest(**body)

    student_data.license = license_to_code(student_data.license)

    owner = current_user.get("sub")
    logger.info("POST /students attempt email=%s owner=%s", student_data.email, owner)

    if current_user.get("role") == "applicant" and student_data.email != current_user.get("sub"):
        raise HTTPException(status_code=403, detail="Applicants can only create their own profile")

    existing_key = resolve_student_key(student_data.email)
    if existing_key:
        stored = json.loads(redis_client.get(existing_key))
        created_by_in_db = stored.get("created_by")
        registered_by_in_db = stored.get("registered_by")
        owner_key = user_key(owner) if owner else None
        if owner in {created_by_in_db} or owner_key == registered_by_in_db:
            logger.info(
                "POST /students duplicate/self email=%s owner=%s",
                student_data.email,
                owner,
            )
            return {"message": "Student already exists", "student": stored}
        logger.warning(
            "POST /students duplicate/conflict email=%s owner=%s created_by_in_db=%s",
            student_data.email,
            owner,
            created_by_in_db,
        )
        raise HTTPException(status_code=400, detail="Student already exists")

    resume_text = ""
    if resume_file is not None:
        ext = os.path.splitext(resume_file.filename or "")[1].lower()
        try:
            if ext == ".pdf":
                import pdfplumber

                with pdfplumber.open(resume_file.file) as pdf:
                    pages = [page.extract_text() or "" for page in pdf.pages]
                resume_text = "\n".join(pages)
            elif ext in {".docx", ".doc"}:
                from docx import Document

                document = Document(resume_file.file)
                resume_text = "\n".join(p.text for p in document.paragraphs)
            elif ext:
                raise HTTPException(status_code=400, detail="Unsupported resume type")
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Resume parsing failed")
            raise HTTPException(status_code=400, detail=f"Failed to parse resume: {e}")

    profile_json = None
    if resume_text:
        try:
            instructions = (
                "Extract a student profile from the following resume text. "
                "Return JSON with these fields: first_name, last_name, email, phone, "
                "license, skills (as a list), experience_summary, and interests (as a list)."
            )
            completion = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": f"{instructions}\n\n{resume_text}"}],
                temperature=0.0,
            )
            profile_json = json.loads(completion.choices[0].message.content)
        except Exception:
            profile_json = None

    combined = " ".join([
        ", ".join(student_data.skills),
        student_data.experience_summary,
        student_data.interests,
    ])
    try:
        resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
        embedding = resp.data[0].embedding
    except Exception as e:
        logger.exception("Embedding generation failed")
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")

    u_key = user_key(current_user.get('sub'))
    user_raw = redis_client.get(u_key)
    institution_code = None
    school_label = None
    if user_raw:
        try:
            user_data = json.loads(user_raw)
            institution_code = user_data.get("institutional_code")
            school_label = user_data.get("school_label")
        except Exception:
            institution_code = None
            school_label = None

    student_id = generate_student_id()

    data = student_data.model_dump(mode="json")
    data["embedding"] = embedding
    data["institution_code"] = institution_code
    data["institutional_code"] = institution_code
    data["student_id"] = student_id
    if school_label is not None:
        data["school_label"] = school_label
    data["created_by"] = current_user.get("sub")
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    persist_student_record(student_data.email, data, institution_code, student_id)
    logger.info(
        "POST /students success email=%s owner=%s",
        student_data.email,
        owner,
    )
    ensure_index(len(embedding))
    if vector_index is not None:
        vector_index.add(np.array([embedding], dtype="float32"))
        vector_emails.append(student_data.email)

    if profile_json is not None:
        return {"message": "Resume parsed by GPT successfully.", "profile": profile_json}
    else:
        return {"message": "Student profile submitted without GPT parsing."}

@router.put("/students/{email}")
def update_student(
    email: str, updated: StudentRequest, current_user: dict = Depends(get_current_user)
):
    email = normalize_email(email)
    key = resolve_student_key(email)
    raw = redis_client.get(key) if key else None
    if not raw:
        raise HTTPException(status_code=404, detail="Student not found")

    if current_user.get("role") == "applicant" and email != current_user.get("sub"):
        raise HTTPException(status_code=403, detail="Applicants can only edit their own profile")

    try:
        existing = json.loads(raw)
    except Exception:
        existing = {}

    updated.license = license_to_code(updated.license)

    combined = " ".join([
        ", ".join(updated.skills),
        updated.experience_summary,
        updated.interests,
    ])
    try:
        resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
        embedding = resp.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")

    data = updated.model_dump(mode="json")
    data["email"] = email
    data["embedding"] = embedding
    inst_code = existing.get("institution_code") or existing.get("institutional_code") or existing.get("school_code")
    student_id = existing.get("student_id") or generate_student_id()
    school_label = existing.get("school_label")
    if inst_code is not None:
        data["institution_code"] = inst_code
        data["institutional_code"] = inst_code
    if school_label is not None:
        data["school_label"] = school_label
    if "school_code" in existing:
        data["school_code"] = existing.get("school_code")
    data["student_id"] = student_id
    created_by = existing.get("created_by")
    created_at = existing.get("created_at")
    if created_by is not None:
        data["created_by"] = created_by
    if created_at is not None:
        data["created_at"] = created_at

    if key and key != student_key(inst_code, student_id):
        redis_client.delete(key)
    persist_student_record(email, data, inst_code, student_id)
    rebuild_vector_index()
    return {"message": "Student updated successfully"}

@router.post("/students/upload")
def upload_students(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    content = file.file.read().decode("utf-8").splitlines()
    reader = csv.DictReader(content)
    u_key = user_key(current_user.get('sub'))
    user_raw = redis_client.get(u_key)
    institution_code = None
    if user_raw:
        try:
            user_data = json.loads(user_raw)
            institution_code = user_data.get("institutional_code")
        except Exception:
            institution_code = None
    count = 0
    for row in reader:
        try:
            skills = [s.strip() for s in row.get("skills", "").split(",") if s.strip()]
            student = StudentRequest(
                first_name=row["first_name"],
                last_name=row["last_name"],
                email=row["email"],
                phone=row["phone"],
                license=row.get("license") or row.get("education_level"),
                skills=skills,
                experience_summary=row["experience_summary"],
                interests=row["interests"],
                city=row["city"],
                state=row["state"],
                lat=float(row["lat"]),
                lng=float(row["lng"]),
                max_travel=float(row["max_travel"]),
            )
        except KeyError:
            continue

        student.license = license_to_code(student.license)

        existing_key = resolve_student_key(student.email)
        if existing_key:
            redis_client.delete(existing_key)
        redis_client.delete(f"student:{student.email}")
        redis_client.delete(student_email_key(student.email))

        combined = " ".join([
            ", ".join(student.skills),
            student.experience_summary,
            student.interests
        ])
        try:
            resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
            embedding = resp.data[0].embedding
        except Exception:
            continue

        student_id = generate_student_id()
        data = student.model_dump(mode="json")
        data["embedding"] = embedding
        data["created_by"] = current_user.get("sub")
        data["created_at"] = datetime.now(timezone.utc).isoformat()
        data["institution_code"] = institution_code
        data["institutional_code"] = institution_code
        data["student_id"] = student_id
        persist_student_record(student.email, data, institution_code, student_id)
        ensure_index(len(embedding))
        if vector_index is not None:
            vector_index.add(np.array([embedding], dtype="float32"))
            vector_emails.append(student.email)

        count += 1

    return {"message": f"Processed {count} students", "count": count}

@router.get("/students/all")
def get_all_students(
    limit: int = 50,
    cursor: Optional[str] = None,
    license: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    cur = int(cursor or 0)
    students: list[dict] = []
    while len(students) < limit:
        cur, keys = redis_client.scan(cur, match="student:*", count=limit)
        for key in keys:
            raw = redis_client.get(key)
            if not raw:
                continue
            try:
                student = json.loads(raw)
            except Exception:
                continue

            email = student.get("email")
            st_license = student.get("license") or student.get("education_level")
            if license and (st_license or "").lower() != license.lower():
                continue

            assigned_codes = redis_client.smembers(
                _student_job_key(email, "assigned")
            )

            info = {
                "first_name": student.get("first_name"),
                "last_name": student.get("last_name"),
                "email": email,
                "phone": student.get("phone"),
                "city": student.get("city"),
                "state": student.get("state"),
                "license": st_license,
                "skills": student.get("skills"),
                "experience_summary": student.get("experience_summary"),
                "interests": student.get("interests"),
                "institutional_code": student.get("institutional_code")
                or student.get("school_code"),
                "assigned_job_code": next(iter(assigned_codes), None),
            }
            students.append(info)
            if len(students) >= limit:
                break
        if cur == 0:
            break
    next_cursor = None if cur == 0 else str(cur)
    return {"students": students, "next_cursor": next_cursor}

@router.get("/students/by-school")
def students_by_school(
    limit: int = 50,
    cursor: Optional[str] = None,
    license: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Return student profiles for the current user's school.

    Career service users only see profiles they created themselves.
    """
    u_key = user_key(current_user.get('sub'))
    raw_user = redis_client.get(u_key)
    if not raw_user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        user = json.loads(raw_user)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupted user data")

    institutional_code = user.get("institutional_code") or user.get("school_code")
    if not institutional_code:
        raise HTTPException(status_code=400, detail="Institutional code required")

    cur = int(cursor or 0)
    students: list[dict] = []
    while len(students) < limit:
        cur, keys = redis_client.scan(cur, match="student:*", count=limit)
        for key in keys:
            raw = redis_client.get(key)
            if not raw:
                continue
            try:
                student = json.loads(raw)
            except Exception:
                continue

            if (student.get("institutional_code") or student.get("school_code")) != institutional_code:
                continue

            if current_user.get("role") == "career" and student.get("created_by") != current_user.get("sub"):
                continue

            email = student.get("email")
            st_license = student.get("license") or student.get("education_level")
            if license and (st_license or "").lower() != license.lower():
                continue
            info = {
                "first_name": student.get("first_name"),
                "last_name": student.get("last_name"),
                "email": email,
                "phone": student.get("phone"),
                "city": student.get("city"),
                "state": student.get("state"),
                "license": st_license,
                "skills": student.get("skills"),
                "experience_summary": student.get("experience_summary"),
                "interests": student.get("interests"),
                "institutional_code": student.get("institutional_code")
                or student.get("school_code"),
            }
            students.append(info)
            if len(students) >= limit:
                break
        if cur == 0:
            break

    next_cursor = None if cur == 0 else str(cur)
    return {"students": students, "next_cursor": next_cursor}

@router.get("/students/{email}/job-stats")
def student_job_stats(email: str, current_user: dict = Depends(get_current_user)):
    """Return job status sets for a given student."""
    norm = normalize_email(email)
    key = resolve_student_key(norm)
    raw = redis_client.get(key) if key else None
    if not raw:
        raise HTTPException(status_code=404, detail="Student not found")

    if current_user.get("role") not in ADMIN_ROLES:
        try:
            student = json.loads(raw)
        except Exception:
            raise HTTPException(status_code=500, detail="Corrupted profile data")
        user_raw = redis_client.get(user_key(current_user.get("sub")))
        user = json.loads(user_raw) if user_raw else {}
        st_code = student.get("institutional_code") or student.get("school_code")
        u_code = user.get("institutional_code") or user.get("school_code")
        if st_code != u_code:
            raise HTTPException(status_code=403, detail="Not authorized")
        if current_user.get("role") == "career" and student.get("created_by") != current_user.get("sub"):
            raise HTTPException(status_code=403, detail="Not authorized")

    return {
        "assigned": list(redis_client.smembers(_student_job_key(norm, "assigned"))),
        "placed": list(redis_client.smembers(_student_job_key(norm, "placed"))),
        "rejected": list(redis_client.smembers(_student_job_key(norm, "rejected"))),
        "uninterested": list(
            redis_client.smembers(_student_job_key(norm, "uninterested"))
        ),
    }

@router.get("/students/{email}/jobs")
def student_jobs(email: str, current_user: dict = Depends(get_current_user)):
    """Return the job list for a given student."""
    norm = normalize_email(email)
    key = resolve_student_key(norm)
    raw = redis_client.get(key) if key else None
    if not raw:
        raise HTTPException(status_code=404, detail="Student not found")

    if current_user.get("role") not in ADMIN_ROLES:
        try:
            student = json.loads(raw)
        except Exception:
            raise HTTPException(status_code=500, detail="Corrupted profile data")
        user_raw = redis_client.get(user_key(current_user.get("sub")))
        user = json.loads(user_raw) if user_raw else {}
        st_code = student.get("institutional_code") or student.get("school_code")
        u_code = user.get("institutional_code") or user.get("school_code")
        if st_code != u_code:
            raise HTTPException(status_code=403, detail="Not authorized")
        if current_user.get("role") == "career" and student.get("created_by") != current_user.get("sub"):
            raise HTTPException(status_code=403, detail="Not authorized")

    return {"jobs": _fetch_student_jobs(norm)}

@router.get("/students/me")
def student_me(current_user: dict = Depends(get_current_user)):
    """Return the logged-in applicant's student profile."""
    email = current_user.get("sub")
    key = resolve_student_key(email)
    raw = redis_client.get(key) if key else None
    if not raw:
        raise HTTPException(status_code=404, detail="Profile not found")

    try:
        student = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupted profile data")

    claimed_by = student.get("claimed_by")
    current_sub = current_user.get("sub")
    if claimed_by and claimed_by != current_sub:
        raise HTTPException(status_code=403, detail="Profile not claimed by current user")

    # Summaries of job status are stored in Redis sets keyed by status
    assigned_job_code = None
    placed = 0
    if email:
        assigned = redis_client.smembers(f"student_jobs:{email}:assigned") or []
        assigned_job_code = next(iter(assigned), None)
        if isinstance(assigned_job_code, bytes):
            assigned_job_code = assigned_job_code.decode("utf-8")
        placed = len(redis_client.smembers(f"student_jobs:{email}:placed") or [])

    info = {
        "first_name": student.get("first_name"),
        "last_name": student.get("last_name"),
        "email": student.get("email"),
        "phone": student.get("phone"),
        "city": student.get("city"),
        "state": student.get("state"),
        "license": student.get("license") or student.get("education_level"),
        "skills": student.get("skills"),
        "experience_summary": student.get("experience_summary"),
        "interests": student.get("interests"),
        "institutional_code": student.get("institutional_code"),
        "placed_jobs": placed,
        "assigned_job_code": assigned_job_code,
    }
    return info

@router.get("/placements/{student_email}")
def get_placements(
    student_email: str, current_user: dict = Depends(get_current_user)
):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    student_email = normalize_email(student_email)
    key = resolve_student_key(student_email)
    if not key or not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Student not found")

    raw = redis_client.get(key)
    student = json.loads(raw) if raw else {}
    return student.get("placement_history", [])

@router.delete("/admin/student-claims/{email}")
def clear_student_claim(email: str, current_user: dict = Depends(get_current_user)):
    """Clear the claimed_by field and related claim tokens for a student."""
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    email = normalize_email(email)
    key = resolve_student_key(email)
    if not key or not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Student not found")

    raw = redis_client.get(key)
    student = json.loads(raw) if raw else {}
    student.pop("claimed_by", None)
    payload = json.dumps(student)
    redis_client.set(key, payload)
    redis_client.set(f"student:{email}", payload)

    for token_key in redis_client.scan_iter("student_claim:*"):
        k = token_key if isinstance(token_key, str) else token_key.decode()
        val = redis_client.get(k)
        if email in k or (isinstance(val, str) and normalize_email(val) == email):
            redis_client.delete(k)

    return {"message": f"Cleared claim for {email}"}

@router.delete("/admin/delete-student/{email}")
def delete_student(email: str, current_user: dict = Depends(get_current_user)):
    """Remove a student profile and any associated user record."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    email = normalize_email(email)
    skey = resolve_student_key(email)
    if not skey or not redis_client.exists(skey):
        raise HTTPException(status_code=404, detail="Student not found")

    # Delete student profile
    redis_client.delete(skey)
    redis_client.delete(student_email_key(email))

    # Remove any lingering user record to avoid bogus admin entries
    ukey = find_user_key(email)
    if ukey:
        redis_client.delete(ukey)

    # Clean up from job assignments/placements
    for job_key in redis_client.scan_iter("job:*"):
        raw = redis_client.get(job_key)
        if not raw:
            continue
        try:
            job = json.loads(raw)
        except Exception:
            continue

        assigned = job.get("assigned_students", [])
        placed = job.get("placed_students", [])

        updated = False
        if email in assigned:
            job["assigned_students"] = [e for e in assigned if e != email]
            updated = True
        if email in placed:
            job["placed_students"] = [e for e in placed if e != email]
            updated = True

        if updated:
            redis_client.set(job_key, json.dumps(job))

    # Remove resume if it exists
    for key in redis_client.scan_iter(f"resume:*:{email}"):
        redis_client.delete(key)

    # Remove job descriptions if any
    for key in redis_client.scan_iter(f"job_description:*:{email}"):
        redis_client.delete(key)

    # (Optional) Clean match results if student appears
    for match_key in redis_client.scan_iter("match_results:*"):
        raw = redis_client.get(match_key)
        if not raw:
            continue
        try:
            matches = json.loads(raw)
            new_matches = [m for m in matches if m.get("email") != email]
            if len(new_matches) != len(matches):
                redis_client.set(match_key, json.dumps(new_matches))
        except Exception:
            continue

    return {"message": f"Student {email} and related data deleted successfully"}

