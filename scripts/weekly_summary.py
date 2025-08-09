from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from typing import Dict

from app.main import (
    ACTIVITY_LOG_KEY,
    client,
    redis_client,
    send_email,
)


def _collect_recruiters() -> Dict[str, Dict[str, object]]:
    """Return mapping of recruiter email to profile info."""
    recruiters: Dict[str, Dict[str, object]] = {}
    for key in redis_client.scan_iter("user:*"):
        try:
            raw = redis_client.get(key)
        except Exception:
            continue
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if data.get("role") != "recruiter":
            continue
        email = data.get("email") or key.split("user:", 1)[1]
        recruiters[email] = {
            "first_name": data.get("first_name", ""),
            "students_created": 0,
            "notes": [],
        }
    return recruiters


def _update_student_counts(recruiters: Dict[str, Dict[str, object]], cutoff: datetime) -> None:
    entries = redis_client.lrange(ACTIVITY_LOG_KEY, 0, -1) or []
    for raw in entries:
        try:
            entry = json.loads(raw)
        except Exception:
            continue
        ts = entry.get("timestamp")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if dt < cutoff:
            continue
        if entry.get("method") == "POST" and entry.get("path") == "/students":
            user = entry.get("user")
            if user in recruiters:
                recruiters[user]["students_created"] = recruiters[user].get("students_created", 0) + 1


def _update_notes(recruiters: Dict[str, Dict[str, object]], cutoff: datetime) -> None:
    for key in redis_client.scan_iter("job:*"):
        try:
            raw_job = redis_client.get(key)
        except Exception:
            continue
        if not raw_job:
            continue
        try:
            job = json.loads(raw_job)
        except Exception:
            continue
        notes_map = job.get("student_notes", {})
        if isinstance(notes_map, str):
            try:
                notes_map = json.loads(notes_map)
            except Exception:
                continue
        if not isinstance(notes_map, dict):
            continue
        for student_email, note_list in notes_map.items():
            if not isinstance(note_list, list):
                continue
            for note in note_list:
                author = note.get("author")
                ts = note.get("timestamp")
                text = note.get("text")
                if not author or not ts or not text:
                    continue
                try:
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if dt < cutoff:
                    continue
                rec = recruiters.get(author)
                if rec is not None:
                    rec.setdefault("notes", []).append(
                        {
                            "student": student_email,
                            "job_code": job.get("job_code"),
                            "text": text,
                        }
                    )


def gather_weekly_metrics() -> Dict[str, Dict[str, object]]:
    """Collect last week's recruiter metrics from Redis."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)
    recruiters = _collect_recruiters()
    if not recruiters:
        return {}
    _update_student_counts(recruiters, cutoff)
    _update_notes(recruiters, cutoff)
    return recruiters


def send_weekly_summaries() -> None:
    """Generate and email weekly summaries for recruiters."""
    data = gather_weekly_metrics()
    for email, info in data.items():
        payload = {
            "first_name": info.get("first_name", ""),
            "students_created": info.get("students_created", 0),
            "notes": info.get("notes", []),
        }
        messages = [
            {
                "role": "system",
                "content": "You write concise weekly activity summaries for career services recruiters.",
            },
            {
                "role": "user",
                "content": json.dumps(payload),
            },
        ]
        try:
            completion = client.chat.completions.create(
                model="gpt-5-mini",
                messages=messages,
                temperature=0,
            )
            summary = completion.choices[0].message.content
        except Exception as e:
            summary = f"Hi {payload['first_name']},

Unable to generate summary: {e}"
        send_email(
            email,
            "Weekly recruiting summary",
            summary,
        )


if __name__ == "__main__":
    send_weekly_summaries()
