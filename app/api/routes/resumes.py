import json
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from backend.app.schemas.description import DescriptionRequest
from backend.app.schemas.resume import ResumeRequest
from backend.app.services.description import generate_description_text
from backend.app.services.resume import generate_resume_text

from app.core.config import SITE_BASE_URL, client
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.db.redis_client import redis_client
from app.services.description import generate_job_description_html
from app.services.core_utils import find_user_key, normalize_email, resolve_student_key, user_key

router = APIRouter()

logger = get_logger(__name__)

@router.post("/generate-resume")
def generate_resume(req: ResumeRequest, current_user: dict = Depends(get_current_user)):
    """Generate an HTML resume using OpenAI and store it in Redis."""
    logger.info("📄 Generating resume for %s - %s", req.student_email, req.job_code)
    preview = getattr(req, "preview", False)
    resume_key = f"resume:{req.job_code}:{req.student_email}"
    html_key = f"resumehtml:{req.job_code}:{req.student_email}"
    if not preview:
        existing = redis_client.get(resume_key)
        if existing:
            redis_client.set(html_key, existing)
            logger.info("📄 Resume already exists for %s - %s", req.student_email, req.job_code)
            return {"status": "exists"}

    job_raw = redis_client.get(f"job:{req.job_code}")
    # Prefer profile stored under "user:" key, falling back to student profile
    profile_key = find_user_key(req.student_email) or user_key(req.student_email)
    student_raw = redis_client.get(profile_key)
    if not student_raw:
        skey = resolve_student_key(req.student_email)
        student_raw = redis_client.get(skey) if skey else None
    if not job_raw or not student_raw:
        logger.warning("❌ Job or student not found")
        raise HTTPException(status_code=404, detail="Job or student not found")

    job = json.loads(job_raw)
    student = json.loads(student_raw)

    if not preview and req.student_email not in job.get("assigned_students", []) \
        and req.student_email not in job.get("placed_students", []):
        raise HTTPException(status_code=403, detail="Student not assigned to job")

    raw_html = generate_resume_text(client, student, job, include_contact=not preview).strip()

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

    full_html = f"""
<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\">
  <title>TalentMatch AI – Resume</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      margin: 2rem;
      line-height: 1.6;
    }}
    h2 {{
      color: #1a1a1a;
      border-bottom: 2px solid #eee;
      padding-bottom: 0.3rem;
    }}
    .section {{
      margin-bottom: 1.5rem;
    }}
  </style>
</head>
<body>
{raw_html}
</body>
</html>
"""

    if not preview:
        redis_client.set(resume_key, full_html)
        redis_client.set(html_key, full_html)
        logger.info("✅ Resume saved for %s - %s", req.student_email, req.job_code)
        return {"status": "success"}
    else:
        return {"status": "preview", "html": full_html}

@router.get("/resume/{job_code}/{student_email}")
def get_resume(job_code: str, student_email: str, current_user: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    key = f"resume:{job_code}:{student_email}"
    logger.info("📥 Download request for resume: %s - %s", job_code, student_email)

    job_raw = redis_client.get(f"job:{job_code}")
    if not job_raw:
        raise HTTPException(status_code=404, detail="Job not found")
    job = json.loads(job_raw)
    if student_email not in job.get("assigned_students", []) and student_email not in job.get("placed_students", []):
        raise HTTPException(status_code=403, detail="Student not assigned to job")

    resume = redis_client.get(key)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    logger.info("✅ Resume found and returned as plain text")
    return {
        "status": "success",
        "job_code": job_code,
        "student_email": student_email,
        "resume": resume if isinstance(resume, str) else resume.decode("utf-8"),
    }

@router.get("/resume-html/{job_code}/{student_email}")
def get_resume_html(job_code: str, student_email: str, current_user: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    key = f"resumehtml:{job_code}:{student_email}"

    job_raw = redis_client.get(f"job:{job_code}")
    if not job_raw:
        raise HTTPException(status_code=404, detail="Job not found")
    job = json.loads(job_raw)
    if student_email not in job.get("assigned_students", []) and student_email not in job.get("placed_students", []):
        raise HTTPException(status_code=403, detail="Student not assigned to job")

    html = redis_client.get(key)
    if not html:
        html = redis_client.get(f"resume:{job_code}:{student_email}")
    if not html:
        raise HTTPException(status_code=404, detail="Resume not found")
    return HTMLResponse(content=html, status_code=200)

@router.post("/generate-description")
def generate_description(req: DescriptionRequest, current_user: dict = Depends(get_current_user)):
    """Generate a short job description tailored to a student."""
    logger.info("📝 Generating description for %s - %s", req.student_email, req.job_code)
    desc_key = f"description:{req.job_code}:{req.student_email}"
    existing = redis_client.get(desc_key)
    if existing:
        logger.info("📝 Description already exists")
        return {"status": "exists", "description": existing}

    job_raw = redis_client.get(f"job:{req.job_code}")
    skey = resolve_student_key(req.student_email)
    student_raw = redis_client.get(skey) if skey else None
    if not job_raw or not student_raw:
        raise HTTPException(status_code=404, detail="Job or student not found")

    job = json.loads(job_raw)
    student = json.loads(student_raw)

    generated_desc = generate_description_text(client, student, job)
    redis_client.set(desc_key, generated_desc)
    logger.info("✅ Description stored")
    return {"status": "success", "description": generated_desc}

@router.post("/generate-job-description")
def generate_job_description(req: ResumeRequest, current_user: dict = Depends(get_current_user)):
    html, existed = generate_job_description_html(req.job_code, req.student_email)
    return {"status": "exists"} if existed else {"status": "success"}

@router.get("/job-description/{job_code}/{student_email}")
def get_job_description(job_code: str, student_email: str, current_user: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    key = f"job_description:{job_code}:{student_email}"
    description = redis_client.get(key)
    if not description:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "success", "description": description}

@router.get("/job-description-html/{job_code}/{student_email}")
def get_job_description_html(job_code: str, student_email: str, current_user: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    key = f"jobdesc:{job_code}:{student_email}"
    html = redis_client.get(key)
    if not html:
        raise HTTPException(status_code=404, detail="Job description not found")
    return HTMLResponse(content=html, status_code=200)

@router.get("/public/job-description-html/{job_code}/{student_email}")
def get_public_job_description_html(job_code: str, student_email: str):
    student_email = normalize_email(student_email)
    key = f"jobdesc:{job_code}:{student_email}"
    html = redis_client.get(key)
    if not html:
        raise HTTPException(status_code=404, detail="Job description not found")
    return HTMLResponse(content=html, status_code=200)

