import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx
from openai import OpenAI

from app.main import ACTIVITY_LOG_KEY, redis_client, send_email

# Reuse a single OpenAI client for efficiency
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), http_client=httpx.Client())


def compile_weekly_stats(user_email: str, now: datetime) -> Dict[str, Any]:
    """Aggregate creation and job placement stats for a career user."""
    week_ago = now - timedelta(days=7)
    student_emails: List[str] = []

    logs = redis_client.lrange(ACTIVITY_LOG_KEY, 0, -1)
    for raw in logs:
        try:
            entry = json.loads(raw)
        except Exception:
            continue
        if entry.get("user") != user_email:
            continue
        if entry.get("method") != "POST" or not entry.get("path", "").startswith("/students"):
            continue
        ts_str = entry.get("timestamp")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
        except Exception:
            continue
        if ts < week_ago or ts > now:
            continue

        email = entry.get("student_email")
        if not email:
            path = entry.get("path", "")
            if path.startswith("/students/"):
                email = path.split("/students/", 1)[1]
            elif "?email=" in path:
                email = path.split("?email=", 1)[1]
        if email:
            student_emails.append(email)

    stats_students: List[Dict[str, Any]] = []
    for email in student_emails:
        assigned = placed = 0
        latest_note: Dict[str, Any] | None = None
        for key in redis_client.scan_iter("job:*"):
            job_raw = redis_client.get(key)
            if not job_raw:
                continue
            try:
                job = json.loads(job_raw)
            except Exception:
                continue
            if email in job.get("assigned_students", []):
                assigned += 1
            if email in job.get("placed_students", []):
                placed += 1
            notes_map = job.get("student_notes", {})
            if isinstance(notes_map, str):
                try:
                    notes_map = json.loads(notes_map)
                except Exception:
                    notes_map = {}
            notes = notes_map.get(email) or []
            if notes:
                latest = notes[-1]
                ts = latest.get("timestamp")
                if not latest_note or (ts and ts > latest_note.get("timestamp")):
                    latest_note = {"text": latest.get("text", ""), "timestamp": ts}
        stats_students.append(
            {
                "email": email,
                "assigned_jobs": assigned,
                "placed_jobs": placed,
                "latest_note": latest_note,
            }
        )

    return {"created_count": len(student_emails), "students": stats_students}


def build_summary_narrative(stats: Dict[str, Any], user_name: str) -> str:
    """Generate a narrative summary of the week's activity."""
    prompt = (
        f"Provide a brief weekly activity summary for {user_name}.\n"
        f"Stats: {json.dumps(stats)}"
    )
    try:
        resp = openai_client.chat.completions.create(
            model="gpt-5-mini",
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content
    except Exception:
        return "Here is your activity summary: " + json.dumps(stats)


def send_weekly_summary(user_email: str) -> None:
    """Compile stats and email a weekly summary to the given user."""
    user_key = f"user:{user_email}"
    raw = redis_client.get(user_key)
    if not raw:
        return
    try:
        user = json.loads(raw)
    except Exception:
        return
    if user.get("role") != "career":
        return

    name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user_email
    stats = compile_weekly_stats(user_email, datetime.now(timezone.utc))
    body = build_summary_narrative(stats, name)
    send_email(user_email, "Your Weekly Activity Summary", body)
