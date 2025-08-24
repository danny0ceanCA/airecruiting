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
from backend.app.logging_utils import get_logger

router = APIRouter(prefix="/jobs", tags=["jobs"])

logger = get_logger(__name__)


def find_user_key(email: str) -> str | None:
    logger.debug("Searching for user key for %s", email)
    target = normalize_email(email)
    exact = f"user:{target}"
    if main.redis_client.exists(exact):
        logger.debug("Found exact user key %s", exact)
        return exact
    for key in main.redis_client.scan_iter("user:*"):
        k = key if isinstance(key, str) else key.decode()
        if k.split("user:", 1)[1].lower() == target:
            logger.debug("Found user key %s via scan", k)
            return k
    logger.debug("User key for %s not found", email)
    return None


@router.post("")
def create_job(job: dict, _: dict = Depends(get_current_user)) -> dict:
    data = dict(job)
    code = data.get("job_code") or str(uuid.uuid4())[:8]
    logger.info("Creating job %s", code)
    data["job_code"] = code
    data.setdefault("assigned_students", [])
    data.setdefault("placed_students", [])
    rl = data.get("required_license")
    if isinstance(rl, str):
        rl_clean = rl.strip()
        if " " in rl_clean and len(rl_clean) > 3:
            data["required_license"] = "".join(w[0] for w in rl_clean.split()).lower()
        else:
            data["required_license"] = rl_clean.lower()
    main.redis_client.set(f"job:{code}", json.dumps(data))
    logger.info("Job %s stored", code)
    return {"message": "Job stored", "job_code": code}


@router.post("/generate-job-description")
def generate_job_description(req: ResumeRequest, _: dict = Depends(get_current_user)):
    logger.info(
        "Generating job description for job %s and student %s",
        req.job_code,
        req.student_email,
    )
    html, existed = generate_job_description_html(
        main.client, main.redis_client, req.job_code, req.student_email
    )
    status = "exists" if existed else "success"
    logger.info(
        "Job description generation for job %s and student %s finished with %s",
        req.job_code,
        req.student_email,
        status,
    )
    return {"status": status}


@router.get("/job-description/{job_code}/{student_email}")
def get_job_description(job_code: str, student_email: str, _: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    key = f"job_description:{job_code}:{student_email}"
    logger.info(
        "Fetching job description for job %s and student %s", job_code, student_email
    )
    description = main.redis_client.get(key)
    if not description:
        logger.warning("Job description not found for job %s and student %s", job_code, student_email)
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "success", "description": description}


@router.get("/job-description-html/{job_code}/{student_email}")
def get_job_description_html(job_code: str, student_email: str, _: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    key = f"jobdesc:{job_code}:{student_email}"
    logger.info("Fetching job description HTML for job %s and student %s", job_code, student_email)
    html = main.redis_client.get(key)
    if not html:
        logger.warning(
            "Job description HTML not found for job %s and student %s",
            job_code,
            student_email,
        )
        raise HTTPException(status_code=404, detail="Job description not found")
    return HTMLResponse(content=html, status_code=200)


@router.get("/public/job-description-html/{job_code}/{student_email}")
def get_public_job_description_html(job_code: str, student_email: str):
    student_email = normalize_email(student_email)
    key = f"jobdesc:{job_code}:{student_email}"
    logger.info(
        "Fetching public job description HTML for job %s and student %s", job_code, student_email
    )
    html = main.redis_client.get(key)
    if not html:
        logger.warning(
            "Public job description HTML not found for job %s and student %s",
            job_code,
            student_email,
        )
        raise HTTPException(status_code=404, detail="Job description not found")
    return HTMLResponse(content=html, status_code=200)


@router.post("/generate-resume")
def generate_resume(req: ResumeRequest, _: dict = Depends(get_current_user)):
    preview = getattr(req, "preview", False)
    logger.info(
        "Generating resume for job %s and student %s (preview=%s)",
        req.job_code,
        req.student_email,
        preview,
    )
    resume_key = f"resume:{req.job_code}:{req.student_email}"
    html_key = f"resumehtml:{req.job_code}:{req.student_email}"
    if not preview:
        existing = main.redis_client.get(resume_key)
        if existing:
            logger.info(
                "Existing resume found for job %s and student %s", req.job_code, req.student_email
            )
            main.redis_client.set(html_key, existing)
            return {"status": "exists"}

    job_raw = main.redis_client.get(f"job:{req.job_code}")
    profile_key = find_user_key(req.student_email)
    student_raw = main.redis_client.get(profile_key) if profile_key else None
    if not student_raw:
        skey = resolve_student_key(main.redis_client, req.student_email)
        student_raw = main.redis_client.get(skey) if skey else None
    if not job_raw or not student_raw:
        logger.warning(
            "Job or student missing when generating resume for job %s and student %s",
            req.job_code,
            req.student_email,
        )
        raise HTTPException(status_code=404, detail="Job or student not found")

    job = json.loads(job_raw)
    student = json.loads(student_raw)

    if not preview and req.student_email not in job.get("assigned_students", []) and req.student_email not in job.get("placed_students", []):
        logger.warning(
            "Student %s not assigned to job %s during resume generation",
            req.student_email,
            req.job_code,
        )
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
        logger.info(
            "Stored resume for job %s and student %s", req.job_code, req.student_email
        )
        return {"status": "success"}
    else:
        logger.info(
            "Generated preview resume for job %s and student %s",
            req.job_code,
            req.student_email,
        )
        return {"status": "preview", "html": full_html}


@router.get("/resume/{job_code}/{student_email}")
def get_resume(job_code: str, student_email: str, _: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    key = f"resume:{job_code}:{student_email}"
    logger.info("Fetching resume for job %s and student %s", job_code, student_email)

    job_raw = main.redis_client.get(f"job:{job_code}")
    if not job_raw:
        logger.warning("Job %s not found when fetching resume", job_code)
        raise HTTPException(status_code=404, detail="Job not found")
    job = json.loads(job_raw)
    if student_email not in job.get("assigned_students", []) and student_email not in job.get("placed_students", []):
        logger.warning(
            "Student %s not assigned to job %s when fetching resume",
            student_email,
            job_code,
        )
        raise HTTPException(status_code=403, detail="Student not assigned to job")

    resume = main.redis_client.get(key)
    if not resume:
        logger.warning(
            "Resume for job %s and student %s not found", job_code, student_email
        )
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
    logger.info(
        "Fetching resume HTML for job %s and student %s", job_code, student_email
    )

    job_raw = main.redis_client.get(f"job:{job_code}")
    if not job_raw:
        logger.warning("Job %s not found when fetching resume HTML", job_code)
        raise HTTPException(status_code=404, detail="Job not found")
    job = json.loads(job_raw)
    if student_email not in job.get("assigned_students", []) and student_email not in job.get("placed_students", []):
        logger.warning(
            "Student %s not assigned to job %s when fetching resume HTML",
            student_email,
            job_code,
        )
        raise HTTPException(status_code=403, detail="Student not assigned to job")

    html = main.redis_client.get(key)
    if not html:
        html = main.redis_client.get(f"resume:{job_code}:{student_email}")
    if not html:
        logger.warning(
            "Resume HTML for job %s and student %s not found", job_code, student_email
        )
        raise HTTPException(status_code=404, detail="Resume not found")
    return HTMLResponse(content=html, status_code=200)


