from __future__ import annotations

import json
import re
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

import app.main as main
from app.routes.auth import get_current_user
from backend.app.schemas.resume import ResumeRequest
from backend.app.services.job import generate_job_description_html, normalize_email, resolve_student_key
from backend.app.services.resume import generate_resume_text

router = APIRouter(prefix="/jobs", tags=["jobs"])


def find_user_key(email: str) -> str | None:
    target = normalize_email(email)
    exact = f"user:{target}"
    if main.redis_client.exists(exact):
        return exact
    for key in main.redis_client.scan_iter("user:*"):
        k = key if isinstance(key, str) else key.decode()
        if k.split("user:", 1)[1].lower() == target:
            return k
    return None


@router.post("")
def create_job(job: dict, _: dict = Depends(get_current_user)) -> dict:
    data = dict(job)
    code = data.get("job_code") or str(uuid.uuid4())[:8]
    data["job_code"] = code
    data.setdefault("assigned_students", [])
    data.setdefault("placed_students", [])
    main.redis_client.set(f"job:{code}", json.dumps(data))
    return {"message": "Job stored", "job_code": code}


@router.post("/generate-job-description")
def generate_job_description(req: ResumeRequest, _: dict = Depends(get_current_user)):
    html, existed = generate_job_description_html(
        main.client, main.redis_client, req.job_code, req.student_email
    )
    return {"status": "exists" if existed else "success"}


@router.get("/job-description/{job_code}/{student_email}")
def get_job_description(job_code: str, student_email: str, _: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    key = f"job_description:{job_code}:{student_email}"
    description = main.redis_client.get(key)
    if not description:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "success", "description": description}


@router.get("/job-description-html/{job_code}/{student_email}")
def get_job_description_html(job_code: str, student_email: str, _: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    key = f"jobdesc:{job_code}:{student_email}"
    html = main.redis_client.get(key)
    if not html:
        raise HTTPException(status_code=404, detail="Job description not found")
    return HTMLResponse(content=html, status_code=200)


@router.get("/public/job-description-html/{job_code}/{student_email}")
def get_public_job_description_html(job_code: str, student_email: str):
    student_email = normalize_email(student_email)
    key = f"jobdesc:{job_code}:{student_email}"
    html = main.redis_client.get(key)
    if not html:
        raise HTTPException(status_code=404, detail="Job description not found")
    return HTMLResponse(content=html, status_code=200)


@router.post("/generate-resume")
def generate_resume(req: ResumeRequest, _: dict = Depends(get_current_user)):
    preview = getattr(req, "preview", False)
    resume_key = f"resume:{req.job_code}:{req.student_email}"
    html_key = f"resumehtml:{req.job_code}:{req.student_email}"
    if not preview:
        existing = main.redis_client.get(resume_key)
        if existing:
            main.redis_client.set(html_key, existing)
            return {"status": "exists"}

    job_raw = main.redis_client.get(f"job:{req.job_code}")
    profile_key = find_user_key(req.student_email)
    student_raw = main.redis_client.get(profile_key) if profile_key else None
    if not student_raw:
        skey = resolve_student_key(main.redis_client, req.student_email)
        student_raw = main.redis_client.get(skey) if skey else None
    if not job_raw or not student_raw:
        raise HTTPException(status_code=404, detail="Job or student not found")

    job = json.loads(job_raw)
    student = json.loads(student_raw)

    if not preview and req.student_email not in job.get("assigned_students", []) and req.student_email not in job.get("placed_students", []):
        raise HTTPException(status_code=403, detail="Student not assigned to job")

    raw_html = generate_resume_text(main.client, student, job, include_contact=not preview).strip()

    if raw_html.startswith("```html"):
        raw_html = raw_html.replace("```html", "", 1).strip()
    if raw_html.endswith("```"):
        raw_html = raw_html.rsplit("```", 1)[0].strip()

    lower_html = raw_html.lower()
    if "<!doctype" in lower_html or "<html" in lower_html:
        body_match = re.search(r"<body[^>]*>(.*?)</body>", raw_html, re.IGNORECASE | re.DOTALL)
        if body_match:
            raw_html = body_match.group(1).strip()
        else:
            html_match = re.search(r"<html[^>]*>(.*?)</html>", raw_html, re.IGNORECASE | re.DOTALL)
            if html_match:
                raw_html = html_match.group(1).strip()

    full_html = (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\"><title>TalentMatch AI – Resume</title>"
        "<style>body {font-family: Arial, sans-serif; margin: 2rem; line-height: 1.6;} "
        "h2 {color: #1a1a1a; border-bottom: 2px solid #eee; padding-bottom: 0.3rem;} "
        ".section {margin-bottom: 1.5rem;}</style></head><body>"
        f"{raw_html}</body></html>"
    )

    if not preview:
        main.redis_client.set(resume_key, full_html)
        main.redis_client.set(html_key, full_html)
        return {"status": "success"}
    else:
        return {"status": "preview", "html": full_html}


@router.get("/resume/{job_code}/{student_email}")
def get_resume(job_code: str, student_email: str, _: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    key = f"resume:{job_code}:{student_email}"

    job_raw = main.redis_client.get(f"job:{job_code}")
    if not job_raw:
        raise HTTPException(status_code=404, detail="Job not found")
    job = json.loads(job_raw)
    if student_email not in job.get("assigned_students", []) and student_email not in job.get("placed_students", []):
        raise HTTPException(status_code=403, detail="Student not assigned to job")

    resume = main.redis_client.get(key)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return {
        "status": "success",
        "job_code": job_code,
        "student_email": student_email,
        "resume": resume,
    }


@router.get("/resume-html/{job_code}/{student_email}")
def get_resume_html(job_code: str, student_email: str, _: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    key = f"resumehtml:{job_code}:{student_email}"

    job_raw = main.redis_client.get(f"job:{job_code}")
    if not job_raw:
        raise HTTPException(status_code=404, detail="Job not found")
    job = json.loads(job_raw)
    if student_email not in job.get("assigned_students", []) and student_email not in job.get("placed_students", []):
        raise HTTPException(status_code=403, detail="Student not assigned to job")

    html = main.redis_client.get(key)
    if not html:
        html = main.redis_client.get(f"resume:{job_code}:{student_email}")
    if not html:
        raise HTTPException(status_code=404, detail="Resume not found")
    return HTMLResponse(content=html, status_code=200)


@router.post("/notify-interest")
def notify_interest(data: dict, _: dict = Depends(get_current_user)):
    job_code = data.get("job_code")
    student_email = data.get("student_email")
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")

    raw = main.redis_client.get(f"job:{job_code}")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")
    job = json.loads(raw)
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
