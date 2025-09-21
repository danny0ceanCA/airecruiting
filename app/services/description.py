import json
from html import escape, unescape
import re

from fastapi import HTTPException

from app.core.logging import get_logger
from app.core.config import client
from app.db.redis_client import redis_client
from app.services.core_utils import normalize_email, resolve_student_key

logger = get_logger(__name__)

def extract_benefits(job_desc: str) -> tuple[list[str], str]:
    """Split an Indeed-style description into benefits and the remaining text.

    Returns a tuple of (benefits_list, remaining_description).
    If no benefits section is detected, the first element is an empty list and
    the original description is returned unchanged.
    """

    lines = [line.strip() for line in job_desc.splitlines()]
    if not lines:
        return [], ""

    idx = 0
    # Look for the "Benefits" heading at the very start
    if lines[idx].lower() != "benefits":
        return [], job_desc.strip()

    idx += 1
    if idx < len(lines) and lines[idx].lower().startswith("pulled from"):
        idx += 1

    benefits: list[str] = []
    while idx < len(lines):
        line = lines[idx].strip()
        low = line.lower()
        if not line or low.startswith("full job description"):
            break
        benefits.append(line)
        idx += 1

    # Skip to the actual description after the "Full job description" marker
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx < len(lines) and lines[idx].lower().startswith("full job description"):
        idx += 1

    remaining = "\n".join(lines[idx:]).strip()
    return benefits, remaining

def generate_job_description_html(job_code: str, student_email: str) -> tuple[str, bool]:
    """Create or fetch an HTML job description for a student."""
    student_email = normalize_email(student_email)
    key = f"job_description:{job_code}:{student_email}"
    html_key = f"jobdesc:{job_code}:{student_email}"

    existing = redis_client.get(key)
    if existing:
        redis_client.set(html_key, existing)
        return existing, True

    job_raw = redis_client.get(f"job:{job_code}")
    skey = resolve_student_key(student_email)
    student_raw = redis_client.get(skey) if skey else None
    if not job_raw or not student_raw:
        raise HTTPException(status_code=404, detail="Job or student not found")

    job = json.loads(job_raw)
    student = json.loads(student_raw)

    prompt = f"""
You are generating a job description document for internal career services staff. The document should first summarize the position itself, then connect it with the student's background.

Use the student profile and job information below to:

- Provide a **Job Summary** that summarizes the job description to avoid copying it verbatim.
- Describe **key responsibilities** they might undertake as noted in the job description.
- List **areas of strength** with plenty of details to reinforce existing experience and how it connects with the job description, and potential **areas for growth** with plenty of insightful and targeted recommendations for training that will improve the probability of success.
- Mention **school affiliation** and any relevant compliance or readiness info.
- Offer **Interview Preparation Tips** with real, actionable advice for succeeding in an interview for this role. Include guidance for new graduates on addressing questions when they lack the required experience, such as drawing on academic projects, internships, or other relevant experiences.

Format this as a printable HTML document titled "TalentMatch AI", styled professionally but without producing binary output.

Student Info:
Name: {student.get('first_name')} {student.get('last_name')}
Email: {student.get('email')}
Skills: {', '.join(student.get('skills', []))}
Experience Summary: {student.get('experience_summary')}
Interests: {student.get('interests')}

Job Info:
Title: {job.get('job_title')}
Source: {job.get('source')}
Description: {job.get('job_description')}
Desired Skills: {', '.join(job.get('desired_skills', []))}
Location: {job.get('city')}, {job.get('state')}
Pay Range: {job.get('min_pay', '')} - {job.get('max_pay', '')}

Output only valid HTML.
"""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
    )

    raw_content = resp.choices[0].message.content.strip()

    if raw_content.startswith("```html"):
        raw_content = raw_content.replace("```html", "", 1).strip()
    if raw_content.endswith("```"):
        raw_content = raw_content.rsplit("```", 1)[0].strip()

    details_html = (
        """
    <h2>Job Details</h2>
    <ul>
      <li><strong>Source:</strong> {source}</li>
      <li><strong>Pay Range:</strong> {pay_min} - {pay_max}</li>
      <li><strong>Location:</strong> {city}, {state}</li>
    </ul>
    """.format(
            source=job.get("source", ""),
            pay_min=job.get("min_pay", ""),
            pay_max=job.get("max_pay", ""),
            city=job.get("city", ""),
            state=job.get("state", ""),
        )
    )

    apply_html = ""
    if job.get("external_apply_url"):
        apply_html = (
            f"<p><strong>Click this link to apply on the employer's site:</strong> "
            f"<a href='{job['external_apply_url']}' target='_blank' rel='noopener noreferrer'>Apply Here</a></p>"
        )

    benefits_html = ""
    job_desc = job.get("job_description", "")
    if job_desc:
        benefits, _ = extract_benefits(job_desc)
        if benefits:
            items = "\n".join(f"<li>{escape(b)}</li>" for b in benefits)
            benefits_html = (
                "<h2>Benefits</h2>\n"
                f"<ul>\n{items}\n</ul>"
            )

    full_html = f"""
<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\">
  <title>TalentMatch AI – Job Description</title>
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
<h1>TalentMatch-AI</h1>
{details_html}
{apply_html}
{benefits_html}
{raw_content}
</body>
</html>
"""

    redis_client.set(key, full_html)
    redis_client.set(html_key, full_html)
    return full_html, False

