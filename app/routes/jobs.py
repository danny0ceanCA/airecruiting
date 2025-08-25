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
def create_job(job: dict, user: dict = Depends(get_current_user)) -> dict:
    logger.info("Creating job")
    data = dict(job)
    code = data.get("job_code") or str(uuid.uuid4())[:8]
    data["job_code"] = code
    data.setdefault("assigned_students", [])
    data.setdefault("placed_students", [])
    data.setdefault("rejected_students", [])
    data.setdefault("uninterested_students", [])
    data.setdefault("student_notes", {})
    data["posted_by"] = user.get("email")
    rl = data.get("required_license")
    if isinstance(rl, str):
        rl_clean = rl.strip()
        if " " in rl_clean and len(rl_clean) > 3:
            data["required_license"] = "".join(w[0] for w in rl_clean.split()).lower()
        else:
            data["required_license"] = rl_clean.lower()
    if "source" not in data:
        sc = user.get("school_code")
        if sc:
            from backend.app.school_codes import SCHOOL_CODE_MAP

            label = SCHOOL_CODE_MAP.get(sc, sc)
            data["source"] = label.split("-", 1)[1] if "-" in label else label
    main.redis_client.set(f"job:{code}", json.dumps(data))
    logger.info("Job %s created", code)
    return {"message": "Job stored", "job_code": code}


@router.get("")
def list_jobs(_: dict = Depends(get_current_user)) -> dict:
    """Return all stored jobs with sensible defaults.

    Older job records may pre-date some of the fields added by the POST
    handler (e.g. ``posted_by`` or ``student_notes``).  The front-end expects
    these keys to exist, so we normalise each job before returning it.  Missing
    ``job_code`` values are derived from the redis key.
    """

    jobs = []
    for key in main.redis_client.scan_iter("job:*"):
        k = key if isinstance(key, str) else key.decode()
        raw = main.redis_client.get(k)
        if not raw:
            continue
        try:
            job = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Malformed job record for %s", k)
            continue

        if isinstance(job, dict):
            job.setdefault("job_code", k.split("job:", 1)[1])
            job.setdefault("posted_by", None)
            job.setdefault("assigned_students", [])
            job.setdefault("placed_students", [])
            job.setdefault("rejected_students", [])
            job.setdefault("uninterested_students", [])
            job.setdefault("student_notes", {})
            code = job.get("job_code")
            m_raw = main.redis_client.get(f"match_results:{code}")
            try:
                job["matches"] = json.loads(m_raw) if m_raw else []
            except json.JSONDecodeError:
                logger.error("Malformed match results for %s", code)
                job["matches"] = []
            jobs.append(job)

    return {"jobs": jobs}


@router.put("/{job_code}")
def update_job(job_code: str, data: dict, _: dict = Depends(get_current_user)) -> dict:
    """Update an existing job record."""
    logger.info("Updating job %s", job_code)
    raw = main.redis_client.get(f"job:{job_code}")
    if not raw:
        logger.warning("Job %s not found for update", job_code)
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        job = json.loads(raw)
    except json.JSONDecodeError:
        snippet = raw[:40] if isinstance(raw, (bytes, str)) else str(raw)[:40]
        logger.error("Malformed JSON for job %s: %s", job_code, snippet)
        raise HTTPException(status_code=500, detail="Malformed job record")
    job.update(data)
    main.redis_client.set(f"job:{job_code}", json.dumps(job))
    logger.info("Job %s updated", job_code)
    return {"message": "Job updated"}


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
    logger.info(
        "Job description generation %s for %s/%s",
        "skipped" if existed else "completed",
        req.job_code,
        req.student_email,
    )
    return {"status": "exists" if existed else "success"}


@router.get("/job-description/{job_code}/{student_email}")
def get_job_description(job_code: str, student_email: str, _: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    logger.info(
        "Retrieving job description for job %s and student %s",
        job_code,
        student_email,
    )
    key = f"job_description:{job_code}:{student_email}"
    description = main.redis_client.get(key)
    if not description:
        logger.warning("Job description missing for %s/%s", job_code, student_email)
        raise HTTPException(status_code=404, detail="Not found")
    logger.info("Job description found for %s/%s", job_code, student_email)
    return {"status": "success", "description": description}


@router.get("/job-description-html/{job_code}/{student_email}")
def get_job_description_html(job_code: str, student_email: str, _: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    logger.info(
        "Retrieving job description HTML for job %s and student %s",
        job_code,
        student_email,
    )
    key = f"jobdesc:{job_code}:{student_email}"
    html = main.redis_client.get(key)
    if not html:
        logger.warning("Job description HTML missing for %s/%s", job_code, student_email)
        raise HTTPException(status_code=404, detail="Job description not found")
    logger.info("Job description HTML served for %s/%s", job_code, student_email)
    return HTMLResponse(content=html, status_code=200)


@router.get("/public/job-description-html/{job_code}/{student_email}")
def get_public_job_description_html(job_code: str, student_email: str):
    student_email = normalize_email(student_email)
    logger.info(
        "Retrieving public job description HTML for job %s and student %s",
        job_code,
        student_email,
    )
    key = f"jobdesc:{job_code}:{student_email}"
    html = main.redis_client.get(key)
    if not html:
        logger.warning(
            "Public job description HTML missing for %s/%s", job_code, student_email
        )
        raise HTTPException(status_code=404, detail="Job description not found")
    logger.info("Public job description HTML served for %s/%s", job_code, student_email)
    return HTMLResponse(content=html, status_code=200)


@router.post("/generate-resume")
def generate_resume(req: ResumeRequest, _: dict = Depends(get_current_user)):
    logger.info(
        "Generating resume for job %s and student %s",
        req.job_code,
        req.student_email,
    )
    preview = getattr(req, "preview", False)
    resume_key = f"resume:{req.job_code}:{req.student_email}"
    html_key = f"resumehtml:{req.job_code}:{req.student_email}"
    if not preview:
        existing = main.redis_client.get(resume_key)
        if existing:
            main.redis_client.set(html_key, existing)
            logger.info(
                "Resume already exists for %s/%s", req.job_code, req.student_email
            )
            return {"status": "exists"}

    job_raw = main.redis_client.get(f"job:{req.job_code}")
    profile_key = find_user_key(req.student_email)
    student_raw = main.redis_client.get(profile_key) if profile_key else None
    if not student_raw:
        skey = resolve_student_key(main.redis_client, req.student_email)
        student_raw = main.redis_client.get(skey) if skey else None
    if not job_raw or not student_raw:
        logger.warning("Job or student not found for resume %s/%s", req.job_code, req.student_email)
        raise HTTPException(status_code=404, detail="Job or student not found")

    job = json.loads(job_raw)
    student = json.loads(student_raw)

    if not preview and req.student_email not in job.get("assigned_students", []) and req.student_email not in job.get("placed_students", []):
        logger.warning("Student %s not assigned to job %s", req.student_email, req.job_code)
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
        logger.info("Resume generated for %s/%s", req.job_code, req.student_email)
        return {"status": "success"}
    else:
        logger.info("Preview resume generated for %s/%s", req.job_code, req.student_email)
        return {"status": "preview", "html": full_html}


@router.get("/resume/{job_code}/{student_email}")
def get_resume(job_code: str, student_email: str, _: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    logger.info("Retrieving resume for %s/%s", job_code, student_email)
    key = f"resume:{job_code}:{student_email}"

    job_raw = main.redis_client.get(f"job:{job_code}")
    if not job_raw:
        logger.warning("Job %s not found for resume", job_code)
        raise HTTPException(status_code=404, detail="Job not found")
    job = json.loads(job_raw)
    if student_email not in job.get("assigned_students", []) and student_email not in job.get("placed_students", []):
        logger.warning("Student %s not assigned to job %s", student_email, job_code)
        raise HTTPException(status_code=403, detail="Student not assigned to job")

    resume = main.redis_client.get(key)
    if not resume:
        logger.warning("Resume not found for %s/%s", job_code, student_email)
        raise HTTPException(status_code=404, detail="Resume not found")
    logger.info("Resume served for %s/%s", job_code, student_email)
    return {
        "status": "success",
        "job_code": job_code,
        "student_email": student_email,
        "resume": resume,
    }


@router.get("/resume-html/{job_code}/{student_email}")
def get_resume_html(job_code: str, student_email: str, _: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    logger.info("Retrieving resume HTML for %s/%s", job_code, student_email)
    key = f"resumehtml:{job_code}:{student_email}"

    job_raw = main.redis_client.get(f"job:{job_code}")
    if not job_raw:
        logger.warning("Job %s not found for resume HTML", job_code)
        raise HTTPException(status_code=404, detail="Job not found")
    job = json.loads(job_raw)
    if student_email not in job.get("assigned_students", []) and student_email not in job.get("placed_students", []):
        logger.warning("Student %s not assigned to job %s", student_email, job_code)
        raise HTTPException(status_code=403, detail="Student not assigned to job")

    html = main.redis_client.get(key)
    if not html:
        html = main.redis_client.get(f"resume:{job_code}:{student_email}")
    if not html:
        logger.warning("Resume HTML not found for %s/%s", job_code, student_email)
        raise HTTPException(status_code=404, detail="Resume not found")
    logger.info("Resume HTML served for %s/%s", job_code, student_email)
    return HTMLResponse(content=html, status_code=200)


