# backend/app/services/summary.py
"""Utilities for generating weekly summary emails."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from openai import OpenAI

ACTIVITY_LOG_KEY = "activity_logs"
redis_client = None
send_email = None

# Reuse a single OpenAI client; reads OPENAI_API_KEY from env
openai_client = OpenAI()

logger = logging.getLogger(__name__)


def _ensure_dependencies() -> None:
    """Load redis client and email sender from app.main on first use."""
    global redis_client, send_email
    if redis_client is None or send_email is None:
        try:
            from app import main as main_app

            if redis_client is None:
                redis_client = main_app.redis_client  # type: ignore[attr-defined]
            if send_email is None:
                send_email = main_app.send_email  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - import failure
            raise RuntimeError("Summary dependencies not configured") from exc


def _parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    # Handle ISO with or without 'Z'
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compile_weekly_stats(user_email: str, now: datetime) -> Dict[str, Any]:
    """Aggregate student creation and job placement stats for a career user over the last 7 days."""
    _ensure_dependencies()
    week_ago = now - timedelta(days=7)
    student_emails: set[str] = set()

    # Activity log: list of JSON entries
    logs = redis_client.lrange(ACTIVITY_LOG_KEY, 0, -1)
    for raw in logs:
        try:
            entry = json.loads(raw)
        except Exception:
            continue

        if entry.get("user") != user_email:
            continue
        if entry.get("method") != "POST" or not str(entry.get("path", "")).startswith("/students"):
            continue

        ts = _parse_ts(entry.get("timestamp"))
        if not ts or ts < week_ago or ts > now:
            continue

        # Try to discover student email from payload or path
        email = entry.get("student_email")
        if not email:
            path = str(entry.get("path", ""))
            if path.startswith("/students/"):
                email = path.split("/students/", 1)[1]
            elif "?email=" in path:
                email = path.split("?email=", 1)[1]
        if email:
            student_emails.add(email)

    stats_students: List[Dict[str, Any]] = []

    # Walk jobs and count assigned/placed per created student
    # NOTE: acceptable for small scale; index later if needed
    for email in student_emails:
        assigned = 0
        placed = 0
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

            # Optional per-job notes map: { student_email: [ {text, timestamp}, ... ] }
            notes_map = job.get("student_notes", {})
            if isinstance(notes_map, str):
                try:
                    notes_map = json.loads(notes_map)
                except Exception:
                    notes_map = {}

            notes = notes_map.get(email) or []
            if notes:
                candidate = notes[-1]
                cand_ts = _parse_ts(candidate.get("timestamp"))
                curr_ts = _parse_ts(latest_note.get("timestamp")) if latest_note else None
                if not curr_ts or (cand_ts and cand_ts > curr_ts):
                    latest_note = {"text": candidate.get("text", ""), "timestamp": candidate.get("timestamp")}

        stats_students.append(
            {
                "email": email,
                "assigned_jobs": assigned,
                "placed_jobs": placed,
                "latest_note": latest_note,
            }
        )

    return {
        "created_count": len(student_emails),
        "students": stats_students,
        "window_start": week_ago.isoformat(),
        "window_end": now.isoformat(),
        "user_email": user_email,
    }


def compile_all_weekly_stats(now: datetime) -> Dict[str, Any]:
    """Aggregate weekly stats for all career staff (for admin summaries)."""
    _ensure_dependencies()
    users: Dict[str, Any] = {}
    for key in redis_client.scan_iter("user:*"):
        raw = redis_client.get(key)
        if not raw:
            continue
        try:
            user = json.loads(raw)
        except Exception:
            continue
        if user.get("role") != "career":
            continue
        email = key.split("user:", 1)[1]
        users[email] = compile_weekly_stats(email, now)
    return {"users": users, "window_end": now.isoformat()}


def build_summary_narrative(stats: Dict[str, Any], user_name: str) -> str:
    """Generate a narrative summary of the week's activity via OpenAI (fallbacks if API fails)."""
    prompt = (
        f"Provide a concise, upbeat weekly activity summary for {user_name}.\n"
        f"Include key numbers, short insights, and 3 bullet action items if applicable.\n"
        f"Stats JSON:\n{json.dumps(stats)}"
    )
    model_name = "gpt-5-mini"
    try:
        resp = openai_client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        has_key = bool(os.getenv("OPENAI_API_KEY"))
        logger.exception(
            "OpenAI chat completion failed for model %s (OPENAI_API_KEY present: %s): %s",
            model_name,
            has_key,
            exc,
        )
        # Safe fallback
        return "Here is your activity summary:\n" + json.dumps(stats, indent=2)


def send_weekly_summary(user_email: str) -> None:
    """Compile stats and email a weekly summary to the given user (career or admin)."""
    _ensure_dependencies()
    raw = redis_client.get(f"user:{user_email}")
    if not raw:
        return

    try:
        user = json.loads(raw)
    except Exception:
        return

    role = user.get("role")
    if role not in {"career", "admin"}:
        return

    display_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user_email
    now = datetime.now(timezone.utc)

    stats = (
        compile_weekly_stats(user_email, now)
        if role == "career"
        else compile_all_weekly_stats(now)
    )

    body = build_summary_narrative(stats, display_name)
    send_email(user_email, "Your Weekly Activity Summary", body)
