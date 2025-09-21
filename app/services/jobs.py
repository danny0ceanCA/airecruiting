import json
from typing import Any

from app.core.config import ACTIVITY_LOG_KEY, EMAIL_OPEN_TOKENS_KEY
from app.core.logging import get_logger
from app.db.redis_client import redis_client
from app.services.core_utils import normalize_email

logger = get_logger(__name__)

def _normalize_notes(value):
    """Return a list of note objects and the latest note text."""
    if isinstance(value, str):
        return [{"text": value}], value
    if isinstance(value, list):
        latest = value[-1].get("text") if value else None
        return value, latest
    return [], None

def _tracking_stats(student_email: str, job_code: str) -> dict:
    """Return email tracking info for a student/job pair."""
    tokens: list[dict] = []
    try:
        if hasattr(redis_client, "hscan_iter"):
            iterator = redis_client.hscan_iter(EMAIL_OPEN_TOKENS_KEY)
        else:
            iterator = redis_client.hashes.get(EMAIL_OPEN_TOKENS_KEY, {}).items()
        for token, raw in iterator:
            try:
                info = json.loads(raw)
            except Exception:
                continue
            if (
                info.get("student_email") == student_email
                and info.get("job_code") == job_code
            ):
                info["token"] = token
                tokens.append(info)
    except Exception:
        pass

    if not tokens:
        return {"email_sent": None, "first_open": None, "clicked": False}

    latest_token: dict | None = None
    latest_sent: str | None = None
    for t in tokens:
        sent = t.get("sent")
        if sent and (latest_sent is None or sent > latest_sent):
            latest_sent = sent
            latest_token = t

    token_set = {latest_token["token"]} if latest_token else set()
    email_sent = latest_sent
    first_open = None
    clicked = False
    try:
        if hasattr(redis_client, "lrange"):
            raw_entries = redis_client.lrange(ACTIVITY_LOG_KEY, 0, -1) or []
        else:
            raw_entries = redis_client.lists.get(ACTIVITY_LOG_KEY, [])
        for raw in raw_entries:
            try:
                entry = json.loads(raw)
            except Exception:
                continue
            if entry.get("token") not in token_set:
                continue
            event = entry.get("event")
            ts = entry.get("timestamp")
            if event == "email_open" and ts:
                if first_open is None or ts < first_open:
                    first_open = ts
            elif event == "email_click":
                clicked = True
    except Exception:
        pass

    return {"email_sent": email_sent, "first_open": first_open, "clicked": clicked}

def _student_job_key(email: str, status: str) -> str:
    """Return the Redis key for a student's job status set."""
    return f"student_jobs:{normalize_email(email)}:{status}"

def _add_student_job(email: str, job_code: str, status: str) -> None:
    """Add a job reference for a student under the given status."""
    try:
        redis_client.sadd(_student_job_key(email, status), job_code)
    except Exception:
        pass

def _remove_student_job(email: str, job_code: str, status: str) -> None:
    """Remove a job reference for a student under the given status."""
    try:
        redis_client.srem(_student_job_key(email, status), job_code)
    except Exception:
        pass

def _fetch_student_jobs(email: str) -> list[dict]:
    """Return job info for a student using direct job reference sets."""
    statuses = {
        "placed": redis_client.smembers(_student_job_key(email, "placed")),
        "assigned": redis_client.smembers(_student_job_key(email, "assigned")),
        "rejected": redis_client.smembers(_student_job_key(email, "rejected")),
        "uninterested": redis_client.smembers(_student_job_key(email, "uninterested")),
    }
    all_codes: set[str] = set().union(*statuses.values())
    jobs_list: list[dict] = []
    for code in all_codes:
        raw = redis_client.get(f"job:{code}")
        if not raw:
            continue
        try:
            job = json.loads(raw)
        except Exception:
            continue
        if code in statuses["placed"]:
            status = "placed"
        elif code in statuses["assigned"]:
            status = "assigned"
        elif code in statuses["rejected"]:
            status = "rejected"
        elif code in statuses["uninterested"]:
            status = "uninterested"
        else:
            status = None
        notes_raw = job.get("student_notes", {}).get(email, [])
        notes, latest_note = _normalize_notes(notes_raw)
        track = _tracking_stats(email, job.get("job_code"))
        jobs_list.append(
            {
                "job_code": job.get("job_code"),
                "job_title": job.get("job_title"),
                "source": job.get("source"),
                "min_pay": job.get("min_pay"),
                "max_pay": job.get("max_pay"),
                "job_description": job.get("job_description"),
                "status": status,
                "posted_by": job.get("posted_by"),
                "notes": notes,
                **({"note": latest_note} if latest_note is not None else {}),
                "email_sent": track["email_sent"],
                "first_open": track["first_open"],
                "clicked": track["clicked"],
            }
        )
    return jobs_list

