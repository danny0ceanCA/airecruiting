# backend/app/services/summary.py
"""Utilities for generating weekly summary emails."""
from __future__ import annotations

import json
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from openai import OpenAI

from backend.app.logging_utils import get_logger

ACTIVITY_LOG_KEY = "activity_logs"
EMAIL_OPEN_TOKENS_KEY = "email_open_tokens"
redis_client = None
send_email = None

# Reuse a single OpenAI client; reads OPENAI_API_KEY from env
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
logger = get_logger(__name__)


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
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _decode(raw):
    if isinstance(raw, (bytes, bytearray)):
        return raw.decode("utf-8", "ignore")
    return raw


def _day_start(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)


def _day_end(d: datetime) -> datetime:
    return d.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)


def _week_window(now: datetime) -> Tuple[datetime, datetime]:
    """
    Return Monday–Friday window ending on the most recent Friday, normalized to full days (UTC):
      start: Monday 00:00:00
      end:   Friday 23:59:59.999999
    Example: run on Mon 2025-08-11 -> Mon 2025-08-04 00:00 to Fri 2025-08-08 23:59:59.999999.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    # Most recent Friday (weekday: Mon=0 ... Fri=4)
    days_since_friday = (now.weekday() - 4) % 7
    last_friday = (now - timedelta(days=days_since_friday)).astimezone(timezone.utc)
    monday_of_that_week = last_friday - timedelta(days=4)
    return _day_start(monday_of_that_week), _day_end(last_friday)


def _in_window(ts_str: str | None, start: datetime, end: datetime) -> bool:
    ts = _parse_ts(ts_str)
    return bool(ts and (start <= ts <= end))


def compile_weekly_stats(user_email: str, now: datetime) -> Dict[str, Any]:
    """
    Aggregate stats for a career user over the last Mon–Fri window:
      - created_count: # students created in-window
      - engaged_count: # students with >=1 assignment (across all of the user's students)
      - assignment_count: total assignments across those students
      - placement_count: total placements across those students
      - notes_count: # students with a note in-window
      - students: per-student breakdown (assigned, placed, notes list, latest_note)
    """
    _ensure_dependencies()
    window_start, window_end = _week_window(now)
    user_lc = (user_email or "").strip().lower()

    # ---- Discover all students owned by this user & track creations in-window ----
    created_emails: set[str] = set()
    user_students: set[str] = set()

    # Scan student:* objects (schema: created_by, created_at, email)
    for key in redis_client.scan_iter("student:*"):
        raw = _decode(redis_client.get(key))
        if not raw:
            continue
        try:
            student = json.loads(raw)
        except Exception:
            continue

        if (student.get("created_by") or "").strip().lower() != user_lc:
            continue

        email = student.get("email") or key.split("student:", 1)[1]
        if not email:
            continue
        user_students.add(email)
        if _in_window(student.get("created_at"), window_start, window_end):
            created_emails.add(email)

    # From activity logs (POST/PUT /students*) to catch any creations not captured above
    raw_logs = redis_client.lrange(ACTIVITY_LOG_KEY, 0, -1) or []
    activity_entries: List[Dict[str, Any]] = []
    for raw in raw_logs:
        decoded = _decode(raw)
        try:
            entry = json.loads(decoded)
        except Exception:
            continue

        activity_entries.append(entry)

        if (entry.get("user") or "").strip().lower() != user_lc:
            continue

        method = (entry.get("method") or "").upper()
        if method not in {"POST", "PUT"}:
            continue

        path = str(entry.get("path", ""))
        if not path.startswith("/students"):
            continue

        email = entry.get("student_email")
        if not email:
            if path.startswith("/students/"):
                email = path.split("/students/", 1)[1]
            elif "?email=" in path:
                email = path.split("?email=", 1)[1]
        if not email:
            continue

        user_students.add(email)
        if _in_window(entry.get("timestamp"), window_start, window_end):
            created_emails.add(email)

    # ---- Build per-student stats across all user students ----
    stats_per_student: Dict[str, Dict[str, Any]] = {
        email: {
            "assigned_jobs": 0,
            "placed_jobs": 0,
            "latest_note": None,
            "notes": [],
            "note_in_window": False,
        }
        for email in user_students
    }

    for key in redis_client.scan_iter("job:*"):
        job_raw = _decode(redis_client.get(key))
        if not job_raw:
            continue
        try:
            job = json.loads(job_raw)
        except Exception:
            continue

        for email in job.get("assigned_students", []) or []:
            if email in stats_per_student:
                stats_per_student[email]["assigned_jobs"] += 1

        for email in job.get("placed_students", []) or []:
            if email in stats_per_student:
                stats_per_student[email]["placed_jobs"] += 1

        # Optional per-job notes: { student_email: [ {text, timestamp}, ... ] }
        notes_map = job.get("student_notes", {})
        if isinstance(notes_map, str):
            try:
                notes_map = json.loads(notes_map)
            except Exception:
                notes_map = {}

        for email, raw_notes in notes_map.items():
            if email not in stats_per_student:
                continue

            if isinstance(raw_notes, str):
                raw_notes = [{"text": raw_notes, "timestamp": None}]
            elif isinstance(raw_notes, list):
                normalized = []
                for n in raw_notes:
                    if isinstance(n, dict):
                        normalized.append({"text": n.get("text", ""), "timestamp": n.get("timestamp")})
                    else:
                        normalized.append({"text": str(n), "timestamp": None})
                raw_notes = normalized
            else:
                raw_notes = []

            if raw_notes:
                stats_per_student[email]["notes"].extend(raw_notes)
                candidate = raw_notes[-1]
                cand_ts = _parse_ts(candidate.get("timestamp"))
                curr_ts = _parse_ts(
                    stats_per_student[email]["latest_note"].get("timestamp")
                ) if stats_per_student[email]["latest_note"] else None
                if not curr_ts or (cand_ts and cand_ts > curr_ts):
                    stats_per_student[email]["latest_note"] = {
                        "text": candidate.get("text", ""),
                        "timestamp": candidate.get("timestamp"),
                    }
                if any(
                    _in_window(n.get("timestamp"), window_start, window_end)
                    for n in raw_notes
                ):
                    stats_per_student[email]["note_in_window"] = True

    # ---- Email analytics for the week ----
    email_tokens: Dict[str, Dict[str, Any]] = {}
    per_student_email: Dict[str, Dict[str, Any]] = {
        email: {"sent": 0, "opened": False, "clicked": False}
        for email in user_students
    }
    sent_count = 0
    opened_students: set[str] = set()
    clicked_students: set[str] = set()

    try:
        if hasattr(redis_client, "hscan_iter"):
            iterator = redis_client.hscan_iter(EMAIL_OPEN_TOKENS_KEY)
        else:
            iterator = redis_client.hashes.get(EMAIL_OPEN_TOKENS_KEY, {}).items()  # type: ignore[attr-defined]
    except Exception:
        iterator = []

    for token, raw in iterator:
        decoded = _decode(raw)
        try:
            info = json.loads(decoded)
        except Exception:
            continue

        email = (info.get("student_email") or "").strip()
        if not email:
            continue
        if email not in user_students:
            user_students.add(email)
            stats_per_student.setdefault(
                email,
                {
                    "assigned_jobs": 0,
                    "placed_jobs": 0,
                    "latest_note": None,
                    "notes": [],
                    "note_in_window": False,
                },
            )
            per_student_email[email] = {"sent": 0, "opened": False, "clicked": False}

        email_tokens[token] = {
            "student_email": email,
            "sent": info.get("sent"),
            "job_code": info.get("job_code"),
        }

        if _in_window(info.get("sent"), window_start, window_end):
            sent_count += 1
            per_student_email[email]["sent"] += 1

    for entry in activity_entries:
        token = entry.get("token")
        if not token or token not in email_tokens:
            continue

        timestamp = entry.get("timestamp")
        if not _in_window(timestamp, window_start, window_end):
            continue

        email = email_tokens[token]["student_email"]
        per_student_email.setdefault(email, {"sent": 0, "opened": False, "clicked": False})

        event = entry.get("event")
        if event == "email_open":
            per_student_email[email]["opened"] = True
            opened_students.add(email)
        elif event == "email_click":
            per_student_email[email]["clicked"] = True
            clicked_students.add(email)

    for email in stats_per_student.keys():
        per_student_email.setdefault(email, {"sent": 0, "opened": False, "clicked": False})

    stats_students: List[Dict[str, Any]] = []
    engaged_count = 0
    assignment_count = 0
    placement_count = 0
    notes_count = 0

    for email in sorted(stats_per_student.keys()):
        data = stats_per_student[email]
        assigned = data["assigned_jobs"]
        placed = data["placed_jobs"]
        all_notes = data["notes"]
        latest_note = data["latest_note"]
        note_in_window = data["note_in_window"]

        if assigned > 0:
            engaged_count += 1
        assignment_count += assigned
        placement_count += placed
        if note_in_window:
            notes_count += 1

        all_notes.sort(
            key=lambda n: _parse_ts(n.get("timestamp"))
            or datetime.min.replace(tzinfo=timezone.utc)
        )

        email_metrics = per_student_email.get(email, {"sent": 0, "opened": False, "clicked": False})
        stats_students.append(
            {
                "email": email,
                "assigned_jobs": assigned,
                "placed_jobs": placed,
                "latest_note": latest_note,
                "notes": all_notes,
                "email_metrics": email_metrics,
            }
        )

    email_analytics = {
        "sent_count": sent_count,
        "unique_open_count": len(opened_students),
        "unique_click_count": len(clicked_students),
        "click_students": sorted(clicked_students),
        "open_students": sorted(opened_students),
        "per_student": [
            {
                "email": student["email"],
                "sent": student["email_metrics"]["sent"],
                "opened": student["email_metrics"]["opened"],
                "clicked": student["email_metrics"]["clicked"],
            }
            for student in stats_students
        ],
    }

    return {
        "created_count": len(created_emails),
        "engaged_count": engaged_count,
        "assignment_count": assignment_count,
        "placement_count": placement_count,
        "notes_count": notes_count,
        "students": stats_students,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "user_email": user_email,
        "email_analytics": email_analytics,
    }


def compile_all_weekly_stats(now: datetime) -> Dict[str, Any]:
    """Aggregate weekly stats for all career staff (for admin summaries)."""
    _ensure_dependencies()
    users: Dict[str, Any] = {}
    agg_email = {
        "sent_count": 0,
        "unique_open_count": 0,
        "unique_click_count": 0,
        "click_students": set(),
        "open_students": set(),
    }
    for key in redis_client.scan_iter("user:*"):
        raw = _decode(redis_client.get(key))
        if not raw:
            continue
        try:
            user = json.loads(raw)
        except Exception:
            continue
        if user.get("role") != "career":
            continue
        email = key.split("user:", 1)[1]
        stats = compile_weekly_stats(email, now)
        users[email] = stats
        email_stats = stats.get("email_analytics", {})
        agg_email["sent_count"] += email_stats.get("sent_count", 0)
        agg_email["unique_open_count"] += email_stats.get("unique_open_count", 0)
        agg_email["unique_click_count"] += email_stats.get("unique_click_count", 0)
        agg_email["click_students"].update(email_stats.get("click_students", []))
        agg_email["open_students"].update(email_stats.get("open_students", []))

    agg_email_summary = {
        "sent_count": agg_email["sent_count"],
        "unique_open_count": agg_email["unique_open_count"],
        "unique_click_count": agg_email["unique_click_count"],
        "click_students": sorted(agg_email["click_students"]),
        "open_students": sorted(agg_email["open_students"]),
    }
    return {
        "users": users,
        "window_end": now.isoformat(),
        "email_analytics": agg_email_summary,
    }


def build_summary_narrative(stats: Dict[str, Any], user_name: str) -> str:
    """Generate a narrative summary of the week's activity via OpenAI."""
    # Use the computed Friday in the subject
    now = _parse_ts(stats.get("window_end")) or datetime.now(timezone.utc)
    # Recompute for safety; but window_end already reflects Fri 23:59:59.999999
    week_ending_str = now.strftime("%Y-%m-%d")

    # Concrete numbers for the “Key Numbers” section (no guessing)
    created_count = stats.get("created_count", 0)
    engaged_count = stats.get("engaged_count", 0)
    assignment_count = stats.get("assignment_count", 0)
    placement_count = stats.get("placement_count", 0)
    notes_count = stats.get("notes_count", 0)

    email_stats = stats.get("email_analytics", {}) or {}
    sent_count = email_stats.get("sent_count", 0)
    open_count = email_stats.get("unique_open_count", 0)
    click_count = email_stats.get("unique_click_count", 0)
    click_students = email_stats.get("click_students") or []
    click_line = (
        f"• Apply link clicks: {click_count} ({', '.join(click_students)})"
        if click_students
        else f"• Apply link clicks: {click_count}"
    )

    prompt = f"""
You are generating a concise, upbeat weekly activity summary email for {user_name}.
Do NOT ask for replies, follow-ups, or include any calls to action other than the provided action items.
Return ONLY the formatted summary. Tone: professional and encouraging.

Subject: Weekly Activity Summary — {week_ending_str}

Hello,

Here’s your snapshot for the week ending {week_ending_str}:

Key Numbers
• {created_count} new student profiles created
• {engaged_count} students currently engaged
• {assignment_count} job assignments
• {placement_count} job placements
• Notes recorded for {notes_count} students this week

Email Analytics
• {sent_count} outreach emails sent
• {open_count} unique opens
{click_line}

Short Insights
• 1–3 short bullet points highlighting notable trends or outcomes based on the Stats JSON.

Student Notes Summary
• For each student in the stats, list their email and a one-line summary of their entire note history,
  mentioning any new notes from this week in context. If the student has no notes, write: “No note activity recorded.”

Action Items
• 1–3 concrete actions based on the Stats JSON. Do not invite replies.

Stats JSON:
{json.dumps(stats)}
""".strip()

    model = os.getenv("SUMMARY_MODEL", "gpt-4o")
    logger.info("Generating weekly summary with model %s", model)
    try:
        no_temp_models = {"gpt-5-mini", "gpt-5-preview"}
        params = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if model not in no_temp_models:
            params["temperature"] = 0.4
        resp = openai_client.chat.completions.create(**params)
        usage = getattr(resp, "usage", None)
        if usage:
            logger.info(
                "Summary tokens used (model=%s): prompt=%s, completion=%s, total=%s",
                model,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
                getattr(usage, "total_tokens", None),
            )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        api_key_present = bool(os.getenv("OPENAI_API_KEY"))
        status = getattr(getattr(exc, "response", None), "status_code", None) or getattr(
            exc, "status", None
        )
        if status:
            logger.warning("OpenAI summary HTTP error status=%s", status)
        logger.exception(
            "OpenAI summary generation failed (model=%s, api_key=%s)",
            model,
            "present" if api_key_present else "missing",
        )
        return "Here is your activity summary:\n" + json.dumps(stats, indent=2)


def send_weekly_summary(user_email: str) -> bool:
    """Compile stats and email a weekly summary to the given user (career or admin).

    Returns True if an email was sent, otherwise False.
    """
    _ensure_dependencies()
    user_email = (user_email or "").strip().lower()
    raw = _decode(redis_client.get(f"user:{user_email}"))
    if not raw:
        return False

    try:
        user = json.loads(raw)
    except Exception:
        return False

    role = user.get("role")
    if role not in {"career", "admin", "junior_admin"}:
        return False

    display_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user_email
    now = datetime.now(timezone.utc)

    stats = (
        compile_weekly_stats(user_email, now)
        if role == "career"
        else compile_all_weekly_stats(now)
    )

    body = build_summary_narrative(stats, display_name)
    send_email(user_email, "Your Weekly Activity Summary", body)
    return True
