from dotenv import load_dotenv

load_dotenv()

from datetime import datetime, timedelta, timezone
import json
import csv
import os
import uuid
from typing import Optional, Callable, Any
import smtplib
import logging
import sys
from email.message import EmailMessage
from fastapi import (
    BackgroundTasks,
    Body,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator, model_validator, HttpUrl
from jose import jwt, JWTError
import bcrypt
for _p in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
    os.environ.pop(_p, None)
import httpx
from openai import OpenAI
import redis
import base64
import asyncio
import time
import re
import numpy as np
import faiss
from rq import Queue
from html import unescape, escape
import random
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
import secrets
import hashlib
from backend.app.schemas.resume import ResumeRequest
from backend.app.schemas.description import DescriptionRequest
from backend.app.services.resume import generate_resume_text
from backend.app.services.description import generate_description_text
from backend.app.school_codes import SCHOOL_CODE_MAP
from backend.app.services.summary import send_weekly_summary
from backend.app.logging_utils import (
    RequestIdFilter,
    get_logger,
    request_id_ctx_var,
)

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(levelname)s [%(request_id)s] %(message)s",
)
for handler in logging.getLogger().handlers:
    handler.addFilter(RequestIdFilter())


logger = get_logger(__name__)

ADMIN_ROLES = {"admin", "junior_admin"}
CAREER_DIRECTOR_ROLE = "career_director"
CAREER_STAFF_ROLES = {"career", CAREER_DIRECTOR_ROLE}

REFRESH_TOKEN_TTL_SECONDS = int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", str(60 * 60 * 24 * 7)))
REFRESH_TOKEN_LOOKUP_PREFIX = "refresh_token_lookup"
REFRESH_TOKEN_USER_PREFIX = "refresh_token_user"
ACCESS_TOKEN_TTL = timedelta(hours=1)


def init_default_school_codes():
    """Ensure Redis contains the default school codes with current labels."""
    for code, label in SCHOOL_CODE_MAP.items():
        key = f"school_code:{code}"
        existing = redis_client.get(key)
        if existing != label:
            redis_client.set(key, label)


DEFAULT_LICENSES: dict[str, str] = {
    "lvn": "Licensed Vocational Nurse",
    "ma": "Medical Assistant",
}


def init_default_licenses() -> None:
    """Seed Redis with default license codes."""
    for code, label in DEFAULT_LICENSES.items():
        key = f"license:{code}"
        existing = redis_client.get(key)
        if existing != label:
            redis_client.set(key, label)


def all_licenses() -> dict[str, str]:
    """Return mapping of all configured licenses."""
    licenses: dict[str, str] = {}
    for key in redis_client.scan_iter("license:*"):
        if not isinstance(key, str) or not key.startswith("license:"):
            continue
        label = redis_client.get(key)
        if label is not None:
            code = key.split("license:", 1)[1]
            licenses[code] = label
    for c, l in DEFAULT_LICENSES.items():
        licenses.setdefault(c, l)
    return licenses


def license_to_code(value: str | None) -> str | None:
    """Return the license code for a given code or label."""
    if not value:
        return value
    val = value.strip()
    licenses = all_licenses()
    low = val.lower()
    if low in licenses:
        return low
    for code, label in licenses.items():
        if low == label.lower():
            return code
    return low


def get_school_label(code: str) -> str | None:
    """Return label for a school code from redis or defaults."""
    label = redis_client.get(f"school_code:{code}")
    if label:
        return label
    return SCHOOL_CODE_MAP.get(code)


def all_school_codes() -> dict[str, str]:
    """Return mapping of all known school codes."""
    codes = {}
    for key in redis_client.scan_iter("school_code:*"):
        val = redis_client.get(key)
        if val is not None:
            c = key.split("school_code:", 1)[1]
            codes[c] = val
    for c, l in SCHOOL_CODE_MAP.items():
        codes.setdefault(c, l)
    return codes

# Load environment variables
# (Handled at top of file)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), http_client=httpx.Client())
redis_url = os.getenv("REDIS_URL")

# Email configuration
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
# Optional base URL for links in notification emails
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "").rstrip("/")

if not redis_url:
    raise RuntimeError("Missing REDIS_URL in .env")

# Redis connection for general app data (strings/JSON)
redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
# Separate connection for RQ that returns bytes
rq_redis_client = redis.Redis.from_url(redis_url)

# Background task queue helper
def get_queue() -> Queue:
    """Return an RQ queue using a raw-redis connection."""
    return Queue(connection=rq_redis_client)

# In-memory vector search index for student embeddings
EMBEDDING_DIM: int | None = None
vector_index: faiss.Index | None = None
vector_emails: list[str] = []


def normalize_email(email: str | None) -> str:
    """Return a lowercase, stripped version of an email."""
    return (email or "").strip().lower()


def user_key(email: str) -> str:
    """Return the redis key for a user."""
    return f"user:{normalize_email(email)}"


USER_INDEX_PREFIX = "user_index"


def _normalize_institution_code(code: str | None) -> str | None:
    """Normalize an institutional code for consistent redis indexing."""

    if not code:
        return None
    return code.strip().lower()


def user_index_key(code: str) -> str:
    """Return the redis key for an institutional-code user index."""

    return f"{USER_INDEX_PREFIX}:{code}"


def _extract_institutional_codes(user: dict | None) -> list[str]:
    """Return a de-duplicated list of institutional codes for a user."""

    if not isinstance(user, dict):
        return []

    codes: list[str] = []
    raw_codes = user.get("institutional_codes")
    if isinstance(raw_codes, (list, tuple)):
        for code in raw_codes:
            if not isinstance(code, str):
                continue
            normalized = code.strip()
            if normalized and normalized not in codes:
                codes.append(normalized)
    else:
        single = user.get("institutional_code") or user.get("school_code")
        if isinstance(single, str):
            normalized = single.strip()
            if normalized:
                codes.append(normalized)
    return codes


def _student_institutional_code(student: dict | None) -> str | None:
    """Extract the institutional code from a stored student profile."""

    if not isinstance(student, dict):
        return None
    code = student.get("institutional_code") or student.get("school_code")
    if isinstance(code, str):
        stripped = code.strip()
        return stripped or None
    return None


def sync_applicant_index(
    email: str,
    previous: dict[str, Any] | None,
    updated: dict[str, Any] | None,
) -> None:
    """Ensure the applicant institutional-code index reflects the latest state."""

    prev = previous or {}
    new = updated or {}
    prev_role = prev.get("role")
    new_role = new.get("role")
    prev_code = _normalize_institution_code(
        prev.get("institutional_code") or prev.get("school_code")
    )
    new_code = _normalize_institution_code(
        new.get("institutional_code") or new.get("school_code")
    )

    if prev_role == "applicant" and prev_code:
        if new_role != "applicant" or new_code != prev_code:
            redis_client.srem(user_index_key(prev_code), normalize_email(email))

    if new_role == "applicant" and new_code:
        redis_client.sadd(user_index_key(new_code), normalize_email(email))


def _hash_refresh_token(token: str) -> str:
    """Return a deterministic hash for a refresh token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _set_with_ttl(key: str, ttl: int, value: str) -> None:
    """Set a redis key with an optional TTL, falling back to set."""
    if hasattr(redis_client, "setex"):
        redis_client.setex(key, ttl, value)
    else:
        redis_client.set(key, value)


def redis_delete(key: str) -> None:
    """Delete a key from redis, tolerating simplified test doubles."""

    if hasattr(redis_client, "delete"):
        redis_client.delete(key)
        return
    for attr in ("store", "sets", "hashes", "lists"):
        container = getattr(redis_client, attr, None)
        if isinstance(container, dict):
            container.pop(key, None)


def issue_refresh_token(email: str) -> str:
    """Generate and persist a refresh token for a user, rotating old values."""
    normalized = normalize_email(email)
    raw_token = secrets.token_urlsafe(48)
    hashed = _hash_refresh_token(raw_token)
    current = redis_client.get(f"{REFRESH_TOKEN_USER_PREFIX}:{normalized}")
    if current:
        redis_delete(f"{REFRESH_TOKEN_LOOKUP_PREFIX}:{current}")
    _set_with_ttl(f"{REFRESH_TOKEN_USER_PREFIX}:{normalized}", REFRESH_TOKEN_TTL_SECONDS, hashed)
    _set_with_ttl(f"{REFRESH_TOKEN_LOOKUP_PREFIX}:{hashed}", REFRESH_TOKEN_TTL_SECONDS, normalized)
    return raw_token


def revoke_refresh_token(email: str, hashed: str | None = None) -> None:
    """Remove refresh token mappings for a user."""
    normalized = normalize_email(email)
    stored_hash = hashed or redis_client.get(f"{REFRESH_TOKEN_USER_PREFIX}:{normalized}")
    if stored_hash:
        redis_delete(f"{REFRESH_TOKEN_LOOKUP_PREFIX}:{stored_hash}")
    redis_delete(f"{REFRESH_TOKEN_USER_PREFIX}:{normalized}")


def generate_access_token(email: str, role: str) -> str:
    """Create a signed JWT access token for the given user."""
    now = datetime.utcnow()
    payload = {
        "sub": normalize_email(email),
        "role": role,
        "exp": now + ACCESS_TOKEN_TTL,
        "iat": now,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def student_key(institution_code: str, student_id: str) -> str:
    """Return the canonical redis key for a student."""
    return f"student:{institution_code}:{student_id}"


def student_email_key(email: str) -> str:
    """Return the secondary index key for a student email."""
    return f"student_email:{normalize_email(email)}"


def resolve_student_key(email: str) -> str | None:
    """Resolve a student's canonical key from their email."""
    idx = redis_client.get(student_email_key(email))
    if idx:
        inst, sid = idx.split(":", 1)
        return student_key(inst, sid)
    legacy = f"student:{normalize_email(email)}"
    if redis_client.exists(legacy):
        return legacy
    return None


def generate_student_id() -> str:
    """Generate a unique student identifier."""
    return str(redis_client.incr("student_id"))


def persist_student_record(email: str, data: dict, institution_code: str, student_id: str) -> None:
    """Persist the student record under canonical, legacy, and index keys."""
    payload = json.dumps(data)
    key = student_key(institution_code, student_id)
    redis_client.set(key, payload)
    if hasattr(redis_client, "store") and getattr(redis_client.get, "__qualname__", "").endswith("DummyRedis.get"):
        redis_client.store[key] = payload
        redis_client.store[student_email_key(email)] = f"{institution_code}:{student_id}"
        redis_client.store[f"student:{email}"] = payload
    else:
        redis_client.set(student_email_key(email), f"{institution_code}:{student_id}")
        redis_client.set(f"student:{email}", payload)


def find_user_key(email: str) -> str | None:
    """Return existing user key matching email case-insensitively."""
    target = normalize_email(email)
    exact = user_key(target)
    if redis_client.exists(exact):
        return exact
    for key in redis_client.scan_iter("user:*"):
        k = key if isinstance(key, str) else key.decode()
        if k.split("user:", 1)[1].lower() == target:
            return k
    return None


def ensure_index(dim: int) -> None:
    """Ensure the FAISS index exists with the correct dimension."""
    global EMBEDDING_DIM, vector_index
    if EMBEDDING_DIM != dim:
        EMBEDDING_DIM = dim
        vector_index = faiss.IndexFlatIP(dim)
        vector_emails.clear()


def rebuild_vector_index() -> None:
    """Populate the FAISS index with existing student embeddings."""
    global vector_index, vector_emails
    vector_emails = []
    if EMBEDDING_DIM is None:
        return
    vector_index = faiss.IndexFlatIP(EMBEDDING_DIM)
    for key in redis_client.scan_iter("student:*"):
        raw = redis_client.get(key)
        if not raw:
            continue
        try:
            student = json.loads(raw)
            emb = student.get("embedding")
            if emb:
                ensure_index(len(emb))
                if vector_index is not None:
                    vector_index.add(np.array([emb], dtype="float32"))
                    vector_emails.append(student.get("email"))
        except Exception:
            continue

# Key used to store activity log entries
ACTIVITY_LOG_KEY = "activity_logs"
# Mapping of email tracking tokens to metadata
EMAIL_OPEN_TOKENS_KEY = "email_open_tokens"
EMAIL_BLAST_META_KEY = "email_blast:meta"
EMAIL_BLAST_INDEX_KEY = "email_blast:index"
EMAIL_BLAST_STATS_PREFIX = "email_blast:stats:"
EMAIL_BLAST_RECIPIENTS_PREFIX = "email_blast:recipients:"
# List key for student load time metrics
STUDENT_LOAD_TIME_KEY = "metrics:student_load_time"
# 1x1 transparent PNG
TRANSPARENT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMBAc8o/QkAAAAASUVORK5CYII="
)

def send_email(
    recipient: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    attachments: list[tuple[str, bytes | str, str]] | None = None,
    track_token: str | None = None,
) -> None:
    """Send an email with optional attachments.

    Raises a RuntimeError if SMTP settings are missing or if sending fails so
    callers can surface the failure to the user."""
    if not SMTP_HOST or not EMAIL_SENDER:
        raise RuntimeError("SMTP configuration is missing")

    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_SENDER
        msg["To"] = recipient
        msg["Subject"] = subject

        text_body = body
        html_part = html_body or body
        if track_token:
            pixel_url = (
                f"{SITE_BASE_URL}/track/open/{track_token}.png"
                if SITE_BASE_URL
                else f"/track/open/{track_token}.png"
            )
            html_part += f"\n<img src=\"{pixel_url}\" width=\"1\" height=\"1\" />"

        msg.set_content(text_body)
        if html_part != text_body:
            msg.add_alternative(html_part, subtype="html")

        if attachments:
            for filename, content, mime in attachments:
                if isinstance(content, str):
                    content = content.encode("utf-8")
                maintype, subtype = mime.split("/", 1)
                msg.add_attachment(
                    content,
                    maintype=maintype,
                    subtype=subtype,
                    filename=filename,
                )

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            if SMTP_USER and SMTP_PASSWORD:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
        logger.info("[email] Sent notification to %s", recipient)
    except Exception as e:
        logger.error("[email] Failed to send email to %s: %s", recipient, e)
        raise



def _blast_stats_key(blast_id: str) -> str:
    return f"{EMAIL_BLAST_STATS_PREFIX}{blast_id}"


def _blast_recipients_key(blast_id: str) -> str:
    return f"{EMAIL_BLAST_RECIPIENTS_PREFIX}{blast_id}"


_URL_PATTERN = re.compile(r"(?P<url>(?:https?://|mailto:)[^\s<>\"']+)")


def _plain_text_to_html(body: str) -> str:
    def linkify(text: str) -> str:
        parts: list[str] = []
        last_index = 0
        for match in _URL_PATTERN.finditer(text):
            start, end = match.span()
            parts.append(escape(text[last_index:start]))
            url = match.group("url")
            escaped_url = escape(url, quote=True)
            parts.append(f'<a href="{escaped_url}">{escaped_url}</a>')
            last_index = end
        parts.append(escape(text[last_index:]))
        return "".join(parts)

    lines = body.splitlines()
    linkified_lines = [linkify(line) for line in lines]
    return "<br />".join(linkified_lines)


def _safe_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _hash_set_mapping(name: str, mapping: dict[str, Any]) -> None:
    try:
        redis_client.hset(name, mapping=mapping)
    except TypeError:
        for field, value in mapping.items():
            redis_client.hset(name, field, value)
    except AttributeError:
        if hasattr(redis_client, "hashes"):
            redis_client.hashes.setdefault(name, {}).update(mapping)  # type: ignore[attr-defined]
        else:
            for field, value in mapping.items():
                redis_client.hset(name, field, value)


def _hash_incr(name: str, field: str, amount: int = 1) -> None:
    try:
        redis_client.hincrby(name, field, amount)
    except AttributeError:
        current = _safe_int(redis_client.hget(name, field))
        redis_client.hset(name, field, current + amount)


def _hash_getall(name: str) -> dict[str, Any]:
    try:
        data = redis_client.hgetall(name) or {}
        return data
    except AttributeError:
        if hasattr(redis_client, "hashes"):
            stored = redis_client.hashes.get(name, {})  # type: ignore[attr-defined]
            return dict(stored)
        return {}


def _list_range(name: str, start: int, end: int) -> list[Any]:
    try:
        return redis_client.lrange(name, start, end) or []
    except AttributeError:
        if hasattr(redis_client, "lists"):
            items = redis_client.lists.get(name, [])  # type: ignore[attr-defined]
            if not items:
                return []
            length = len(items)
            start_idx = start if start >= 0 else max(length + start, 0)
            end_idx = end if end >= 0 else length + end
            if end == -1:
                end_idx = length - 1
            end_idx = min(end_idx, length - 1)
            if start_idx > end_idx:
                return []
            return items[start_idx : end_idx + 1]
        return []

def _clean_institution_label(label: str | None) -> str | None:
    """Remove leading code prefixes from school labels."""

    if not label:
        return None
    cleaned = label.strip()
    if not cleaned:
        return None
    parts = cleaned.split("-", 1)
    if len(parts) == 2 and parts[0].strip().isdigit():
        return parts[1].strip()
    return cleaned


def build_welcome_email(
    first_name: str | None,
    institution_label: str | None,
    *,
    staff_created: bool = False,
) -> tuple[str, str]:
    """Return the subject and body for the student welcome email."""

    name = (first_name or "").strip()
    if name:
        name = name.split()[0]
    else:
        name = "there"

    institution = _clean_institution_label(institution_label)
    if not institution:
        institution = "your academic institution"

    subject = "Welcome to TalentMatch-AI 🎉"

    if staff_created:
        intro_line = (
            f"The Career Services team at {institution} has already created your "
            "TalentMatch-AI profile to help you take the next step in your healthcare career.\n\n"
        )
    else:
        intro_line = (
            f"We're excited to share that TalentMatch-AI has partnered with {institution} "
            "to support you in taking the next step in your healthcare career.\n\n"
        )

    body = (
        f"Hi {name},\n\n"
        f"{intro_line}"
        "As part of this partnership, you'll have access to:\n\n"
        "✅ Personalized Job Matches – opportunities tailored to your profile.\n\n"
        "🔔 Job Alerts – stay informed as soon as new positions open up in your area.\n\n"
        "📚 Career Resources – resume tips, webinars, and guidance to help you succeed.\n\n"
        "👩‍⚕️ Support from Experienced RNs and LVNs – professional insight and mentorship "
        "to help you prepare with confidence.\n\n"
        "We're here to support you every step of the way, alongside your Career Services team.\n\n"
        "Wishing you success,\n"
        "The TalentMatch-AI Team"
    )
    return subject, body


def send_student_welcome_email(
    student: dict,
    *,
    institution_code: str | None = None,
) -> bool:
    """Send the configured welcome email to a student if possible."""

    if not isinstance(student, dict):
        return False

    email = student.get("email")
    if not email:
        return False

    label = student.get("school_label")
    label_from_code = False
    if not label:
        code = student.get("institutional_code") or student.get("institution_code") or institution_code
        if code:
            label = get_school_label(str(code))
            label_from_code = True

    normalized_student_email = normalize_email(email)

    def _normalize_owner(value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        owner_value = value
        if owner_value.startswith("user:"):
            owner_value = owner_value.split("user:", 1)[1]
        return normalize_email(owner_value)

    owner_emails = [
        _normalize_owner(student.get("created_by")),
        _normalize_owner(student.get("registered_by")),
    ]
    owner_emails = [email for email in owner_emails if email]

    staff_created = False
    if normalized_student_email and owner_emails:
        staff_created = any(owner_email != normalized_student_email for owner_email in owner_emails)

    subject, body = build_welcome_email(
        student.get("first_name"),
        None if label_from_code else label,
        staff_created=staff_created,
    )
    send_email(email, subject, body)
    student["welcome_email_sent_at"] = datetime.now(timezone.utc).isoformat()
    return True


def send_welcome_email_for_key(student_key_value: str, *, force: bool = False) -> str:
    """Send (or skip) the welcome email for a stored student record."""

    raw = redis_client.get(student_key_value)
    if not raw:
        return "missing"

    try:
        student = json.loads(raw)
    except Exception:
        logger.exception("Failed to decode student record for %s", student_key_value)
        return "failed"

    email = student.get("email")
    if not email:
        logger.info("Skipping welcome email for %s: missing email", student_key_value)
        return "skipped"

    if not force and student.get("welcome_email_sent_at"):
        return "skipped"

    inst_code: str | None = None
    student_id: str | None = None
    parts = student_key_value.split(":", 2)
    if len(parts) == 3:
        _, inst_raw, student_id = parts
        inst_code = None if inst_raw == "None" else inst_raw
    else:
        idx = redis_client.get(student_email_key(email))
        if idx:
            inst_raw, student_id = idx.split(":", 1)
            inst_code = None if inst_raw == "None" else inst_raw

    try:
        sent = send_student_welcome_email(student, institution_code=inst_code)
    except Exception:
        logger.exception("Failed to send welcome email to %s", email)
        return "failed"

    if sent and student_id is not None:
        persist_student_record(email, student, inst_code, student_id)

    return "sent" if sent else "skipped"


def queue_welcome_email(student_key_value: str) -> None:
    """Background task wrapper for sending welcome emails."""

    try:
        status = send_welcome_email_for_key(student_key_value)
        logger.info("Welcome email status for %s: %s", student_key_value, status)
    except Exception:
        logger.exception("Unexpected error sending welcome email for %s", student_key_value)

async def get_driving_distance_miles(
    orig_lat: float | list[tuple[float, float]],
    orig_lng: float | None = None,
    dest_lat: float | None = None,
    dest_lng: float | None = None,
    *,
    job_code: str | None = None,
    job_id: str | None = None,
) -> float | dict[tuple[float, float], float]:
    """Return driving distance(s) in miles using Google Distance Matrix.

    The function accepts a list of origin coordinates and batches requests to
    respect the Google API limit of 25 origins per call. Results are cached in
    Redis for 24 hours to avoid excessive API calls. When provided a single
    origin via the legacy signature, the return value remains the distance in
    miles for backward compatibility.
    """

    key = os.getenv("GOOGLE_KEY")
    if not key:
        raise RuntimeError("Missing GOOGLE_KEY")

    provided_list = isinstance(orig_lat, list)
    invalid_origins = 0
    if provided_list:
        valid_origins: list[tuple[float, float]] = []
        for lat, lng in orig_lat:
            if lat is None or lng is None:
                invalid_origins += 1
                continue
            try:
                lat_f = float(lat)
                lng_f = float(lng)
            except (TypeError, ValueError):
                invalid_origins += 1
                continue
            if lat_f == 0.0 and lng_f == 0.0:
                invalid_origins += 1
                continue
            valid_origins.append((lat_f, lng_f))
        origins = valid_origins
        if dest_lat is not None and dest_lng is not None:
            dest_latitude = float(dest_lat)
            dest_longitude = float(dest_lng)
        elif isinstance(orig_lng, (int, float)) and isinstance(dest_lat, (int, float)):
            dest_latitude = float(orig_lng)
            dest_longitude = float(dest_lat)
        else:
            raise ValueError("When passing a list of origins, provide destination coordinates")
    else:
        if not all(isinstance(v, (int, float)) for v in [orig_lat, orig_lng, dest_lat, dest_lng]):
            raise ValueError("Invalid coordinates provided")
        origins = [(float(orig_lat), float(orig_lng))]  # type: ignore[arg-type]
        dest_latitude = float(dest_lat)  # type: ignore[arg-type]
        dest_longitude = float(dest_lng)  # type: ignore[arg-type]

    results: dict[tuple[float, float], float] = {}
    missing: list[tuple[float, float]] = []
    ttl_seconds = int(timedelta(hours=24).total_seconds())

    if invalid_origins:
        logger.info("Skipping %s invalid origins before distance lookup", invalid_origins)

    for lat, lng in origins:
        cache_key = f"distance:{lat}:{lng}:{dest_latitude}:{dest_longitude}"
        cached = redis_client.get(cache_key)
        if cached is not None:
            try:
                miles = float(cached)
                logger.info("Distance cache hit for %s", cache_key)
                results[(lat, lng)] = miles
                continue
            except ValueError:
                logger.exception("Invalid cached distance for %s", cache_key)
        logger.info("Distance cache miss for %s", cache_key)
        missing.append((lat, lng))

    if missing:
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        async with httpx.AsyncClient() as client:
            logger.info(
                f"🛠️ Preparing distance batches for job {job_code} ({len(origins)} origins)"
            )
            if len(missing) > 25:
                batches = [missing[i : i + 25] for i in range(0, len(missing), 25)]
            else:
                batches = [missing]

            logger.info(
                f"🌍 Starting distance lookups for {len(origins)} origins across {len(batches)} batches (job={job_code}, job_id={job_id})"
            )
            elapsed_total = 0.0
            for idx, batch in enumerate(batches):
                if not batch:
                    continue
                origins_param = "|".join(f"{lat},{lng}" for lat, lng in batch)
                params = {
                    "origins": origins_param,
                    "destinations": f"{dest_latitude},{dest_longitude}",
                    "units": "imperial",
                    "key": key,
                }
                try:
                    logger.info(
                        f"   🌐 Sending batch {idx + 1}/{len(batches)} with {len(batch)} origins to Google (job={job_code}, job_id={job_id})"
                    )
                    t0 = time.perf_counter()
                    resp = await client.get(url, params=params)
                    elapsed = time.perf_counter() - t0
                    elapsed_total += elapsed
                    logger.info(
                        f"   ✅ Batch {idx + 1}/{len(batches)} completed in {elapsed:.2f}s (job={job_code}, job_id={job_id})"
                    )
                except Exception:
                    logger.exception("Error requesting distance matrix")
                    raise

                if resp.status_code != 200:
                    logger.warning(
                        "Distance matrix non-200 response %s: %s", resp.status_code, resp.text
                    )
                    resp.raise_for_status()

                try:
                    data = resp.json()
                    rows = data["rows"]
                except Exception:
                    logger.exception("Error parsing distance matrix response")
                    raise

                if len(rows) != len(batch):
                    raise ValueError("Distance matrix response row count mismatch")

                for origin, row in zip(batch, rows):
                    try:
                        element = row["elements"][0]
                        value_meters = element["distance"]["value"]
                    except Exception:
                        logger.exception("Error parsing distance for origin %s", origin)
                        raise

                    miles = value_meters / 1609.34
                    cache_key = f"distance:{origin[0]}:{origin[1]}:{dest_latitude}:{dest_longitude}"
                    redis_client.setex(cache_key, ttl_seconds, miles)
                    results[origin] = miles

            logger.info(
                "⏱️ Distance lookups completed in %.2fs for job %s (job_id=%s)",
                elapsed_total,
                job_code or "n/a",
                job_id or "n/a",
            )
            logger.info(
                f"⏱️ All distance lookups completed for job {job_code} (job_id={job_id})"
            )

    if provided_list:
        return results
    return results[origins[0]]

JWT_SECRET = "secret"
ALGORITHM = "HS256"

app = FastAPI()

# Simple request logging and activity tracking
@app.middleware("http")
async def log_requests(request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    token = request_id_ctx_var.set(request_id)
    try:
        client_host = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        if client_host:
            client_host = client_host.replace("\n", " ").replace("\r", " ")[:100]
        if user_agent:
            user_agent = user_agent.replace("\n", " ").replace("\r", " ")[:200]

        logger.info(
            "Incoming %s %s from %s UA %s",
            request.method,
            request.url,
            client_host or "-",
            user_agent or "-",
        )
        user = None
        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            token_val = auth.split(" ", 1)[1]
            try:
                payload = jwt.decode(token_val, JWT_SECRET, algorithms=[ALGORITHM])
                user = payload.get("sub")
            except JWTError:
                user = "invalid_token"

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": request.method,
            "path": request.url.path,
            "user": user,
            "request_id": request_id,
            "client_host": client_host,
            "user_agent": user_agent,
        }
        start = datetime.now()
        response = await call_next(request)
        duration = (datetime.now() - start).total_seconds()
        logger.info("Response %s in %.3fs", response.status_code, duration)
        log_entry["status"] = response.status_code
        log_entry["duration"] = duration
        try:
            redis_client.rpush(ACTIVITY_LOG_KEY, json.dumps(log_entry))
        except Exception as e:
            logger.error("Failed to store activity log: %s", e)
        return response
    finally:
        request_id_ctx_var.reset(token)

@app.get("/routes")
def list_routes():
    return [route.path for route in app.routes]

# Add CORS middleware BEFORE defining routes
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:3002",
    "https://airecruiting-frontend.onrender.com",
    "https://talentmatch-frontend-nacw.onrender.com",
    "https://talentmatch-ai.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional: Preflight catch-all
@app.options("/{rest_of_path:path}")
async def preflight_handler(rest_of_path: str):
    return {}

@app.get("/track/open/{token}.png")
def track_open(token: str):
    """Log an email open event and return a 1x1 transparent PNG."""
    info_raw = redis_client.hget(EMAIL_OPEN_TOKENS_KEY, token)
    info: dict[str, str] = {}
    if info_raw:
        try:
            info = json.loads(info_raw)
        except Exception:
            info = {}

    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()

    blast_id = info.get("blast_id") if isinstance(info, dict) else None
    recipient = info.get("recipient") if isinstance(info, dict) else None
    if blast_id and recipient:
        stats_key = _blast_stats_key(blast_id)
        recipients_key = _blast_recipients_key(blast_id)
        try:
            raw_state = redis_client.hget(recipients_key, recipient)
            state = json.loads(raw_state) if raw_state else {"email": recipient}
        except Exception:
            state = {"email": recipient}
        opens_val = state.get("opens")
        try:
            opens_count = int(opens_val)
        except (TypeError, ValueError):
            opens_count = 0
        opens_count += 1
        state["opens"] = opens_count
        if not state.get("first_open"):
            state["first_open"] = timestamp
            try:
                _hash_incr(stats_key, "unique_opens", 1)
            except Exception as e:
                logger.error("Failed to increment blast unique opens: %s", e)
        state["last_open"] = timestamp
        if state.get("status") != "opened":
            state["status"] = "opened"
        try:
            redis_client.hset(recipients_key, recipient, json.dumps(state))
        except Exception as e:
            logger.error("Failed to persist blast recipient open state: %s", e)
        try:
            _hash_incr(stats_key, "total_opens", 1)
        except Exception as e:
            logger.error("Failed to increment blast total opens: %s", e)

    log_entry = {
        "timestamp": timestamp,
        "event": "email_open",
        "token": token,
        **info,
    }
    try:
        redis_client.rpush(ACTIVITY_LOG_KEY, json.dumps(log_entry))
    except Exception as e:
        logger.error("Failed to log email open: %s", e)
    return Response(content=TRANSPARENT_PNG, media_type="image/png")


@app.get("/track/click/{token}")
def track_click(token: str):
    """Redirect to the external URL while logging an email click event."""
    info_raw = redis_client.hget(EMAIL_OPEN_TOKENS_KEY, token)
    info: dict[str, str] = {}
    if info_raw:
        try:
            info = json.loads(info_raw)
        except Exception:
            info = {}
    external_url = info.get("external_url")
    if not external_url:
        raise HTTPException(status_code=404, detail="Unknown token")
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "email_click",
        "token": token,
        **info,
    }
    try:
        redis_client.rpush(ACTIVITY_LOG_KEY, json.dumps(log_entry))
    except Exception as e:
        logger.error("Failed to log email click: %s", e)
    return RedirectResponse(url=external_url)

@app.get("/school-codes")
def school_codes():
    """Return available institutional codes."""
    codes = [{"code": c, "label": l} for c, l in all_school_codes().items()]
    return {"codes": codes}


# ----- User Utilities ----- #


def _validate_admin_password(password: str) -> None:
    """Basic validation for admin passwords."""
    if (
        len(password) < 8
        or not re.search(r"[A-Za-z]", password)
        or not re.search(r"\d", password)
    ):
        raise RuntimeError(
            "Admin passwords must be at least 8 characters and include letters and numbers"
        )


def _seed_admin_user(email: str, password: str, first: str, last: str, role: str) -> None:
    key = f"user:{email}"
    if redis_client.exists(key):
        return
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    payload = {
        "first_name": first,
        "last_name": last,
        "institutional_code": "Admin School",
        "password": hashed,
        "active": True,
        "role": role,
        "approved": True,
        "rejected": False,
    }
    redis_client.set(key, json.dumps(payload))
    sync_applicant_index(email, None, payload)
    logger.info("%s user %s created", role, email)


def init_default_admin():
    """Seed the default admin users if they do not already exist."""
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError("ADMIN_EMAIL and ADMIN_PASSWORD must be set")
    _validate_admin_password(password)
    _seed_admin_user(email, password, "Admin", "User", "admin")

    j_email = os.getenv("JUNIOR_ADMIN_EMAIL")
    j_password = os.getenv("JUNIOR_ADMIN_PASSWORD")
    if j_email and j_password:
        _validate_admin_password(j_password)
        _seed_admin_user(j_email, j_password, "Junior", "Admin", "junior_admin")
    elif j_email or j_password:
        raise RuntimeError(
            "JUNIOR_ADMIN_EMAIL and JUNIOR_ADMIN_PASSWORD must both be set"
        )

    init_default_school_codes()
    init_default_licenses()


def init_career_directors() -> None:
    """Seed configured career director accounts from environment variables."""

    raw = os.getenv("CAREER_DIRECTOR_ACCOUNTS")
    if not raw:
        return

    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("CAREER_DIRECTOR_ACCOUNTS must contain valid JSON") from exc

    if not isinstance(entries, list):
        raise RuntimeError("CAREER_DIRECTOR_ACCOUNTS must be a JSON array of accounts")

    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError("Each career director entry must be an object")

        email_raw = entry.get("email")
        password = entry.get("password")
        codes_raw = entry.get("institutional_codes")

        if not isinstance(email_raw, str) or not email_raw.strip():
            raise RuntimeError("Career director entries require an email")
        if not isinstance(password, str) or not password:
            raise RuntimeError("Career director entries require a password")
        if not isinstance(codes_raw, list) or not codes_raw:
            raise RuntimeError(
                "Career director entries require an institutional_codes list"
            )

        codes: list[str] = []
        for code in codes_raw:
            if not isinstance(code, str):
                continue
            cleaned = code.strip()
            if cleaned and cleaned not in codes:
                codes.append(cleaned)

        if not codes:
            raise RuntimeError(
                "Career director institutional_codes entries must include at least one code"
            )

        email = normalize_email(email_raw)
        _validate_admin_password(password)
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        first_code = codes[0]
        first_name = (entry.get("first_name") or "Career").strip() or "Career"
        last_name = (entry.get("last_name") or "Director").strip() or "Director"
        label = get_school_label(first_code)

        key = user_key(email)
        previous_raw = redis_client.get(key)
        previous: dict[str, Any] | None = None
        if previous_raw:
            try:
                previous = json.loads(previous_raw)
            except Exception:
                previous = None

        payload: dict[str, Any] = previous.copy() if isinstance(previous, dict) else {}
        payload.update(
            {
                "first_name": first_name,
                "last_name": last_name,
                "institutional_code": first_code,
                "institutional_codes": codes,
                "school_label": label,
                "password": hashed,
                "active": True,
                "role": CAREER_DIRECTOR_ROLE,
                "approved": True,
                "rejected": False,
            }
        )

        redis_client.set(key, json.dumps(payload))
        sync_applicant_index(email, previous, payload)
        logger.info("career_director user %s configured for codes %s", email, codes)

@app.on_event("startup")
def on_startup():
    # Verify Redis connection and seed the default admin
    try:
        redis_client.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.error("Redis connection failed: %s", e)
        raise
    if not SITE_BASE_URL:
        logger.warning("[startup] Warning: SITE_BASE_URL is empty; links in notification emails may be incorrect")
    else:
        logger.info("[startup] Using SITE_BASE_URL=%s", SITE_BASE_URL)
    init_default_admin()
    init_default_school_codes()
    init_default_licenses()
    init_career_directors()
    init_default_rss_feeds()
    keys = redis_client.keys("match_job:*")
    logger.info("🔎 Found %s saved match sets at startup.", len(keys))

# -------- Models -------- #
class RegisterRequest(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    institutional_code: str | None = Field(default=None, alias="school_code")
    password: str
    role: str = "applicant"

    model_config = ConfigDict(populate_by_name=True)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class VerifyTokenRequest(BaseModel):
    token: str

class ApproveRequest(BaseModel):
    email: EmailStr
    role: str | None = None  # optional new role

class RejectRequest(BaseModel):
    email: EmailStr

class UpdateUserRequest(BaseModel):
    role: str | None = None
    institutional_code: str | None = Field(default=None, alias="school_code")
    active: bool | None = None

class StudentRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    phone: str
    license: str = Field(alias="education_level")
    skills: list[str]
    experience_summary: str
    interests: str
    city: str
    state: str
    lat: float
    lng: float
    max_travel: float

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("max_travel")
    @classmethod
    def check_travel(cls, v):
        if v <= 0:
            raise ValueError("max_travel must be positive")
        return v

class JobRequest(BaseModel):
    job_title: str
    job_description: str
    desired_skills: list[str]
    job_code: Optional[str] = None
    source: str | None = None
    external_apply_url: HttpUrl | None = None
    required_license: str | None = None
    min_pay: float
    max_pay: float
    city: str
    state: str
    lat: float
    lng: float

    @field_validator("min_pay", "max_pay")
    @classmethod
    def check_positive(cls, v):
        if v <= 0:
            raise ValueError("Pay must be positive")
        return v

    @model_validator(mode="after")
    def validate_range(self):
        if self.min_pay > self.max_pay:
            raise ValueError("Minimum pay cannot exceed maximum pay")
        return self

class JobCodeRequest(BaseModel):
    job_code: str


class EmailBlastRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1)
    institutional_codes: list[str] = Field(default_factory=list)
    license: str | None = None
    source: str | None = None

    @field_validator("subject", "body", mode="before")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("institutional_codes", mode="before")
    @classmethod
    def _normalize_codes(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if isinstance(value, (list, tuple, set)):
            normalized: list[str] = []
            for item in value:
                if not isinstance(item, str):
                    continue
                stripped = item.strip()
                if stripped:
                    normalized.append(stripped)
            return normalized
        raise TypeError("institutional_codes must be a string or list of strings")

    @field_validator("license", "source", mode="before")
    @classmethod
    def _normalize_optional(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        raise TypeError("license/source must be strings")

    @model_validator(mode="after")
    def _ensure_filters(self):
        if (
            not self.institutional_codes
            and not self.license
            and not self.source
        ):
            raise ValueError("At least one recipient filter must be provided")
        return self


# -------- Auth -------- #
def get_current_user(authorization: str = Header(..., alias="Authorization")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload

# -------- Routes -------- #
@app.get("/")
def read_root():
    return {"message": "Hello, World"}

@app.post("/register")
def register(req: RegisterRequest):
    raw_email = req.email
    email = normalize_email(raw_email)
    logger.info("POST /register attempt email=%s normalized=%s", raw_email, email)
    existing = find_user_key(email)
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")
    student_key_existing = resolve_student_key(email)
    key = user_key(email)

    if req.role in CAREER_STAFF_ROLES.union({"recruiter"}) and not req.institutional_code:
        raise HTTPException(
            status_code=400,
            detail="Institutional code required for career staff, directors, and recruiters",
        )

    label = None
    if req.institutional_code:
        label = get_school_label(req.institutional_code)
        if not label:
            raise HTTPException(
                status_code=400,
                detail="Invalid school code. Please contact your administrator.",
            )

    hashed = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    payload = {
        "first_name": req.first_name,
        "last_name": req.last_name,
        "institutional_code": req.institutional_code,
        "school_label": label,
        "password": hashed,
        "active": True,
        "role": req.role,
        "approved": False,
        "rejected": False,
    }
    redis_client.set(key, json.dumps(payload))
    sync_applicant_index(email, None, payload)
    if student_key_existing:
        raw = redis_client.get(student_key_existing)
        try:
            student = json.loads(raw) if raw else {}
        except Exception:
            student = {}
        student["registered_by"] = key
        redis_client.set(student_key_existing, json.dumps(student))
        send_email(
            email,
            "Student profile claimed",
            "Your account has been linked to an existing student profile.",
        )
        creator = student.get("created_by")
        if creator and creator != email:
            send_email(
                creator,
                "Student profile claimed",
                f"{email} has claimed the student profile you created.",
            )
        logger.info(
            "Linked user %s to existing student profile %s",
            email,
            student_key_existing,
        )
    logger.info("POST /register success email=%s", email)
    return {"message": "Registration submitted. Awaiting admin approval"}

@app.post("/login")
def login(req: LoginRequest, request: Request):
    raw_email = req.email
    email = normalize_email(raw_email)
    client_ip = request.client.host if request.client else "unknown"
    request_id = request_id_ctx_var.get("-")
    logger.info(
        "POST /login attempt email=%s normalized=%s ip=%s ts=%s request_id=%s",
        raw_email,
        email,
        client_ip,
        datetime.utcnow().isoformat(),
        request_id,
    )
    key = find_user_key(email)
    raw = redis_client.get(key) if key else None
    if not raw:
        logger.warning(
            "POST /login failure email=%s reason=not_found ip=%s ts=%s request_id=%s",
            email,
            client_ip,
            datetime.utcnow().isoformat(),
            request_id,
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = json.loads(raw)
    stored_pw = user.get("password", "").encode()
    if not bcrypt.checkpw(req.password.encode(), stored_pw):
        logger.warning(
            "POST /login failure email=%s reason=password_mismatch ip=%s ts=%s request_id=%s",
            email,
            client_ip,
            datetime.utcnow().isoformat(),
            request_id,
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("approved"):
        logger.warning(
            "POST /login failure email=%s reason=not_approved ip=%s ts=%s request_id=%s",
            email,
            client_ip,
            datetime.utcnow().isoformat(),
            request_id,
        )
        raise HTTPException(status_code=403, detail="User not approved")
    if not user.get("active", True):
        logger.warning(
            "POST /login failure email=%s reason=deactivated ip=%s ts=%s request_id=%s",
            email,
            client_ip,
            datetime.utcnow().isoformat(),
            request_id,
        )
        raise HTTPException(status_code=403, detail="User deactivated")

    token = generate_access_token(email, user["role"])
    refresh_token = issue_refresh_token(email)
    logger.info(
        "POST /login success email=%s ip=%s ts=%s request_id=%s",
        email,
        client_ip,
        datetime.utcnow().isoformat(),
        request_id,
    )
    try:
        redis_client.rpush(
            ACTIVITY_LOG_KEY,
            json.dumps(
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "user": email,
                    "action": "login",
                }
            ),
        )
    except Exception as e:
        logger.error("Failed to store login log for %s: %s", email, e)
    return {"token": token, "refresh_token": refresh_token}


@app.post("/refresh")
def refresh(req: RefreshRequest):
    token_value = (req.refresh_token or "").strip()
    if not token_value:
        raise HTTPException(status_code=400, detail="Refresh token required")

    hashed = _hash_refresh_token(token_value)
    lookup_key = f"{REFRESH_TOKEN_LOOKUP_PREFIX}:{hashed}"
    email = redis_client.get(lookup_key)
    if not email:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    stored_hash = redis_client.get(f"{REFRESH_TOKEN_USER_PREFIX}:{normalize_email(email)}")
    if stored_hash != hashed:
        revoke_refresh_token(email, hashed)
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    key = find_user_key(email)
    raw = redis_client.get(key) if key else None
    if not raw:
        revoke_refresh_token(email, hashed)
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    try:
        user = json.loads(raw)
    except json.JSONDecodeError:
        revoke_refresh_token(email, hashed)
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if not user.get("approved") or not user.get("active", True):
        revoke_refresh_token(email, hashed)
        raise HTTPException(status_code=403, detail="User not authorized")

    revoke_refresh_token(email, hashed)
    new_refresh_token = issue_refresh_token(email)
    access_token = generate_access_token(email, user["role"])
    return {"token": access_token, "refresh_token": new_refresh_token}


@app.post("/verify-token")
def verify_token(req: VerifyTokenRequest, current_user: dict = Depends(get_current_user)):
    """Verify a student token and claim the profile for the current user."""
    try:
        payload = jwt.decode(req.token, JWT_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid token")

    student_data = payload.get("student") or payload
    email = normalize_email(student_data.get("email"))
    inst = student_data.get("institutional_code")
    sid = student_data.get("student_id")
    if not email or not inst or not sid:
        raise HTTPException(status_code=400, detail="Invalid token payload")

    key = student_key(inst, sid)
    raw = redis_client.get(key)
    existing = json.loads(raw) if raw else {}

    # Preserve existing created_by if present
    created_by = existing.get("created_by") or student_data.get("created_by")

    updated = existing.copy()
    updated.update(student_data)
    if created_by is not None:
        updated["created_by"] = created_by
    updated["claimed_by"] = current_user["sub"]

    payload_json = json.dumps(updated)
    redis_client.set(key, payload_json)
    redis_client.set(f"student:{email}", payload_json)

    idx_key = student_email_key(email)
    if not redis_client.exists(idx_key):
        redis_client.set(idx_key, f"{inst}:{sid}")

    return {"student": updated}

@app.post("/approve")
def approve(req: ApproveRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    raw_email = req.email
    email = normalize_email(raw_email)
    logger.info("POST /approve request email=%s normalized=%s", raw_email, email)
    key = find_user_key(email)
    raw = redis_client.get(key) if key else None
    if not raw:
        raise HTTPException(status_code=404, detail="User not found")
    user = json.loads(raw)
    previous = dict(user)
    user["approved"] = True
    if req.role is not None:
        user["role"] = req.role
    redis_client.set(key, json.dumps(user))
    sync_applicant_index(email, previous, user)
    return {"message": f"{email} approved as {user['role']}"}

@app.post("/reject")
def reject(req: RejectRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    raw_email = req.email
    email = normalize_email(raw_email)
    logger.info("POST /reject request email=%s normalized=%s", raw_email, email)
    key = find_user_key(email)
    raw = redis_client.get(key) if key else None
    if not raw:
        raise HTTPException(status_code=404, detail="User not found")
    user = json.loads(raw)
    user["rejected"] = True
    redis_client.set(key, json.dumps(user))
    return {"message": f"{email} rejected"}

@app.get("/pending-users")
def pending_users(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    pending = []
    for key in redis_client.scan_iter("user:*"):
        raw = redis_client.get(key)
        if not raw:
            continue
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            sample = raw[:200] + ("..." if len(raw) > 200 else "")
            logger.error(
                "Malformed JSON for Redis key %s (len=%d) sample=%r: %s",
                key,
                len(raw),
                sample,
                exc,
                exc_info=True,
            )
            continue
        if info.get("approved") or info.get("rejected"):
            continue
        email = key.split("user:", 1)[1]
        pending.append({"email": email, **{k: v for k, v in info.items() if k != "password"}})
    return pending


@app.get("/admin/users")
def list_users(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    users = []
    for key in redis_client.scan_iter("user:*"):
        raw = redis_client.get(key)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            sample = raw[:200] + ("..." if len(raw) > 200 else "")
            logger.error(
                "Malformed JSON for Redis key %s (len=%d) sample=%r: %s",
                key,
                len(raw),
                sample,
                exc,
                exc_info=True,
            )
            continue
        email = key.split("user:", 1)[1]
        data.pop("password", None)
        users.append({"email": email, **data})
    return {"users": users}


@app.put("/admin/users/{email}")
def update_user(email: str, req: UpdateUserRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    raw_email = email
    email = normalize_email(raw_email)
    logger.info("PUT /admin/users update email=%s normalized=%s", raw_email, email)
    key = find_user_key(email)
    raw = redis_client.get(key) if key else None
    if not raw:
        raise HTTPException(status_code=404, detail="User not found")
    user = json.loads(raw)
    previous = dict(user)
    if req.role is not None:
        user["role"] = req.role
    if req.institutional_code is not None:
        label = get_school_label(req.institutional_code)
        if not label:
            raise HTTPException(status_code=400, detail="Invalid school code")
        user["institutional_code"] = req.institutional_code
        user["school_label"] = label
    if req.active is not None:
        user["active"] = req.active
    redis_client.set(key, json.dumps(user))
    sync_applicant_index(email, previous, user)
    return {"message": "User updated"}


@app.delete("/admin/users/{email}")
def delete_user(email: str, current_user: dict = Depends(get_current_user)):
    """Delete a user account."""
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    raw_email = email
    email = normalize_email(raw_email)
    logger.info("DELETE /admin/users request email=%s normalized=%s", raw_email, email)
    key = find_user_key(email)
    if not key or not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="User not found")

    raw = redis_client.get(key)
    if raw:
        try:
            user = json.loads(raw)
        except Exception:
            user = None
        if user:
            sync_applicant_index(email, user, {})
    redis_delete(key)
    return {"message": f"Deleted {email}"}


class SchoolCodeRequest(BaseModel):
    code: str
    label: str


class UpdateSchoolCodeRequest(BaseModel):
    label: str


class WelcomeEmailRequest(BaseModel):
    resend: bool = False
    limit: int | None = None


@app.post("/admin/school-codes")
def add_school_code(
    req: SchoolCodeRequest, current_user: dict = Depends(get_current_user)
):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"school_code:{req.code}"
    if redis_client.exists(key):
        raise HTTPException(status_code=400, detail="Code already exists")
    redis_client.set(key, req.label)
    return {"message": "School code added"}


@app.put("/admin/school-codes/{code}")
def update_school_code(
    code: str, req: UpdateSchoolCodeRequest, current_user: dict = Depends(get_current_user)
):
    """Update the label for an existing school code."""
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"school_code:{code}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Code not found")
    redis_client.set(key, req.label)
    return {"message": "School code updated"}


@app.delete("/admin/school-codes/{code}")
def delete_school_code(code: str, current_user: dict = Depends(get_current_user)):
    """Delete a school code."""
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"school_code:{code}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Code not found")
    redis_delete(key)
    return {"message": "School code deleted"}


class LicenseRequest(BaseModel):
    code: str
    label: str


class UpdateLicenseRequest(BaseModel):
    label: str


@app.get("/licenses")
def list_licenses():
    licenses = [{"code": c, "label": l} for c, l in all_licenses().items()]
    return {"licenses": licenses}


@app.post("/admin/licenses")
def add_license(req: LicenseRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"license:{req.code}"
    if redis_client.exists(key):
        raise HTTPException(status_code=400, detail="License already exists")
    redis_client.set(key, req.label)
    return {"message": "License added"}


@app.put("/admin/licenses/{code}")
def update_license(code: str, req: UpdateLicenseRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"license:{code}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="License not found")
    redis_client.set(key, req.label)
    return {"message": "License updated"}


@app.delete("/admin/licenses/{code}")
def delete_license(code: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"license:{code}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="License not found")
    redis_delete(key)
    return {"message": "License deleted"}


class RSSFeedRequest(BaseModel):
    name: str
    url: str


class UpdateRSSFeedRequest(BaseModel):
    url: str


@app.get("/rss-feeds")
def list_rss_feeds():
    feeds = [{"name": n, "url": u} for n, u in all_rss_feeds().items()]
    return {"feeds": feeds}


@app.post("/admin/rss-feeds")
def add_rss_feed(req: RSSFeedRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"rss_feed:{req.name}"
    if redis_client.exists(key):
        raise HTTPException(status_code=400, detail="Feed already exists")
    redis_client.set(key, req.url)
    return {"message": "Feed added"}


@app.put("/admin/rss-feeds/{name}")
def update_rss_feed(name: str, req: UpdateRSSFeedRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"rss_feed:{name}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Feed not found")
    redis_client.set(key, req.url)
    return {"message": "Feed updated"}


@app.delete("/admin/rss-feeds/{name}")
def delete_rss_feed(name: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"rss_feed:{name}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Feed not found")
    redis_delete(key)
    return {"message": "Feed deleted"}

@app.post("/students")
async def create_student(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    content_type = request.headers.get("content-type", "")
    resume_file: UploadFile | None = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        resume_file = form.get("resume")
        skills_field = form.get("skills", "")
        student_data = StudentRequest(
            first_name=form.get("first_name"),
            last_name=form.get("last_name"),
            email=form.get("email"),
            phone=form.get("phone"),
            license=form.get("license") or form.get("education_level"),
            skills=[s.strip() for s in skills_field.split(",") if s.strip()],
            experience_summary=form.get("experience_summary"),
            interests=form.get("interests"),
            city=form.get("city"),
            state=form.get("state"),
            lat=float(form.get("lat")),
            lng=float(form.get("lng")),
            max_travel=float(form.get("max_travel")),
        )
    else:
        body = await request.json()
        student_data = StudentRequest(**body)

    student_data.license = license_to_code(student_data.license)

    owner = current_user.get("sub")
    logger.info("POST /students attempt email=%s owner=%s", student_data.email, owner)

    if current_user.get("role") == "applicant" and student_data.email != current_user.get("sub"):
        raise HTTPException(status_code=403, detail="Applicants can only create their own profile")

    existing_key = resolve_student_key(student_data.email)
    if existing_key:
        stored = json.loads(redis_client.get(existing_key))
        created_by_in_db = stored.get("created_by")
        registered_by_in_db = stored.get("registered_by")
        owner_key = user_key(owner) if owner else None
        if owner in {created_by_in_db} or owner_key == registered_by_in_db:
            logger.info(
                "POST /students duplicate/self email=%s owner=%s",
                student_data.email,
                owner,
            )
            return {"message": "Student already exists", "student": stored}
        logger.warning(
            "POST /students duplicate/conflict email=%s owner=%s created_by_in_db=%s",
            student_data.email,
            owner,
            created_by_in_db,
        )
        raise HTTPException(status_code=400, detail="Student already exists")

    resume_text = ""
    if resume_file is not None:
        ext = os.path.splitext(resume_file.filename or "")[1].lower()
        try:
            if ext == ".pdf":
                import pdfplumber

                with pdfplumber.open(resume_file.file) as pdf:
                    pages = [page.extract_text() or "" for page in pdf.pages]
                resume_text = "\n".join(pages)
            elif ext in {".docx", ".doc"}:
                from docx import Document

                document = Document(resume_file.file)
                resume_text = "\n".join(p.text for p in document.paragraphs)
            elif ext:
                raise HTTPException(status_code=400, detail="Unsupported resume type")
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Resume parsing failed")
            raise HTTPException(status_code=400, detail=f"Failed to parse resume: {e}")

    profile_json = None
    if resume_text:
        try:
            instructions = (
                "Extract a student profile from the following resume text. "
                "Return JSON with these fields: first_name, last_name, email, phone, "
                "license, skills (as a list), experience_summary, and interests (as a list)."
            )
            completion = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": f"{instructions}\n\n{resume_text}"}],
                temperature=0.0,
            )
            profile_json = json.loads(completion.choices[0].message.content)
        except Exception:
            profile_json = None

    combined = " ".join([
        ", ".join(student_data.skills),
        student_data.experience_summary,
        student_data.interests,
    ])
    try:
        resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
        embedding = resp.data[0].embedding
    except Exception as e:
        logger.exception("Embedding generation failed")
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")

    u_key = user_key(current_user.get('sub'))
    user_raw = redis_client.get(u_key)
    institution_code = None
    school_label = None
    if user_raw:
        try:
            user_data = json.loads(user_raw)
            institution_code = user_data.get("institutional_code")
            school_label = user_data.get("school_label")
        except Exception:
            institution_code = None
            school_label = None

    student_id = generate_student_id()

    data = student_data.model_dump(mode="json")
    data["embedding"] = embedding
    data["institution_code"] = institution_code
    data["institutional_code"] = institution_code
    data["student_id"] = student_id
    if school_label is not None:
        data["school_label"] = school_label
    data["created_by"] = current_user.get("sub")
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    persist_student_record(student_data.email, data, institution_code, student_id)
    canonical_key = student_key(institution_code, student_id)
    background_tasks.add_task(queue_welcome_email, canonical_key)
    logger.info(
        "POST /students success email=%s owner=%s",
        student_data.email,
        owner,
    )
    ensure_index(len(embedding))
    if vector_index is not None:
        vector_index.add(np.array([embedding], dtype="float32"))
        vector_emails.append(student_data.email)

    if profile_json is not None:
        return {"message": "Resume parsed by GPT successfully.", "profile": profile_json}
    else:
        return {"message": "Student profile submitted without GPT parsing."}


@app.put("/students/{email}")
def update_student(
    email: str, updated: StudentRequest, current_user: dict = Depends(get_current_user)
):
    email = normalize_email(email)
    key = resolve_student_key(email)
    raw = redis_client.get(key) if key else None
    if not raw:
        raise HTTPException(status_code=404, detail="Student not found")

    if current_user.get("role") == "applicant" and email != current_user.get("sub"):
        raise HTTPException(status_code=403, detail="Applicants can only edit their own profile")

    try:
        existing = json.loads(raw)
    except Exception:
        existing = {}

    updated.license = license_to_code(updated.license)

    combined = " ".join([
        ", ".join(updated.skills),
        updated.experience_summary,
        updated.interests,
    ])
    try:
        resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
        embedding = resp.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")

    data = updated.model_dump(mode="json")
    data["email"] = email
    data["embedding"] = embedding
    inst_code = existing.get("institution_code") or existing.get("institutional_code") or existing.get("school_code")
    student_id = existing.get("student_id") or generate_student_id()
    school_label = existing.get("school_label")
    if inst_code is not None:
        data["institution_code"] = inst_code
        data["institutional_code"] = inst_code
    if school_label is not None:
        data["school_label"] = school_label
    if "school_code" in existing:
        data["school_code"] = existing.get("school_code")
    data["student_id"] = student_id
    created_by = existing.get("created_by")
    created_at = existing.get("created_at")
    if created_by is not None:
        data["created_by"] = created_by
    if created_at is not None:
        data["created_at"] = created_at

    if key and key != student_key(inst_code, student_id):
        redis_delete(key)
    persist_student_record(email, data, inst_code, student_id)
    rebuild_vector_index()
    return {"message": "Student updated successfully"}

@app.post("/students/upload")
def upload_students(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    content = file.file.read().decode("utf-8").splitlines()
    reader = csv.DictReader(content)
    u_key = user_key(current_user.get('sub'))
    user_raw = redis_client.get(u_key)
    institution_code = None
    if user_raw:
        try:
            user_data = json.loads(user_raw)
            institution_code = user_data.get("institutional_code")
        except Exception:
            institution_code = None
    count = 0
    for row in reader:
        try:
            skills = [s.strip() for s in row.get("skills", "").split(",") if s.strip()]
            student = StudentRequest(
                first_name=row["first_name"],
                last_name=row["last_name"],
                email=row["email"],
                phone=row["phone"],
                license=row.get("license") or row.get("education_level"),
                skills=skills,
                experience_summary=row["experience_summary"],
                interests=row["interests"],
                city=row["city"],
                state=row["state"],
                lat=float(row["lat"]),
                lng=float(row["lng"]),
                max_travel=float(row["max_travel"]),
            )
        except KeyError:
            continue

        student.license = license_to_code(student.license)

        existing_key = resolve_student_key(student.email)
        if existing_key:
            redis_delete(existing_key)
        redis_delete(f"student:{student.email}")
        redis_delete(student_email_key(student.email))

        combined = " ".join([
            ", ".join(student.skills),
            student.experience_summary,
            student.interests
        ])
        try:
            resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
            embedding = resp.data[0].embedding
        except Exception:
            continue

        student_id = generate_student_id()
        data = student.model_dump(mode="json")
        data["embedding"] = embedding
        data["created_by"] = current_user.get("sub")
        data["created_at"] = datetime.now(timezone.utc).isoformat()
        data["institution_code"] = institution_code
        data["institutional_code"] = institution_code
        data["student_id"] = student_id
        persist_student_record(student.email, data, institution_code, student_id)
        ensure_index(len(embedding))
        if vector_index is not None:
            vector_index.add(np.array([embedding], dtype="float32"))
            vector_emails.append(student.email)

        count += 1

    return {"message": f"Processed {count} students", "count": count}

@app.post("/jobs")
def create_job(job: JobRequest, current_user: dict = Depends(get_current_user)):
    generated_code = str(uuid.uuid4())[:8]
    key = f"job:{generated_code}"
    # Ensure the generated job code does not collide with an existing key
    while redis_client.exists(key):
        generated_code = str(uuid.uuid4())[:8]
        key = f"job:{generated_code}"

    data = job.model_dump(mode="json")
    data["required_license"] = license_to_code(data.get("required_license"))
    user_email = current_user.get("sub")
    user_role = current_user.get("role")
    # Autopopulate source for recruiters if missing or blank
    if user_role == "recruiter" or not data.get("source"):
        raw_user = redis_client.get(f"user:{user_email}")
        label = None
        if raw_user:
            try:
                udata = json.loads(raw_user)
                label = udata.get("school_label")
            except Exception:
                label = None
        if label:
            data["source"] = label.split("-", 1)[-1] if "-" in label else label

    if data.get("external_apply_url") and not data.get("source"):
        raise HTTPException(status_code=400, detail="Source required when external apply URL is provided")

    data["job_code"] = generated_code
    data["posted_by"] = user_email
    data["timestamp"] = datetime.now().isoformat()
    data.setdefault("assigned_students", [])
    data.setdefault("placed_students", [])
    data.setdefault("uninterested_students", [])
    data.setdefault("rejected_students", [])
    data.setdefault("student_notes", {})

    redis_client.set(key, json.dumps(data))
    logger.info("Stored job at %s: %s", key, data)
    return {"message": "Job stored", "job_code": generated_code}


@app.put("/jobs/{job_code}")
def update_job(job_code: str, updated: dict, token_data: dict = Depends(get_current_user)):
    key = f"job:{job_code}"
    raw = redis_client.get(key)

    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        job = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Malformed job record")

    if token_data.get("role") not in ADMIN_ROLES and token_data.get("sub") != job.get("posted_by"):
        raise HTTPException(status_code=403, detail="Not authorized to edit this job")

    if "min_pay" in updated or "max_pay" in updated:
        min_pay = float(updated.get("min_pay", job.get("min_pay", 0)))
        max_pay = float(updated.get("max_pay", job.get("max_pay", 0)))
        if min_pay <= 0 or max_pay <= 0 or min_pay > max_pay:
            raise HTTPException(status_code=400, detail="Invalid pay range")
    if "required_license" in updated:
        updated["required_license"] = license_to_code(updated["required_license"])
    if "external_apply_url" in updated:
        parsed = urlparse(updated["external_apply_url"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=400, detail="Invalid external_apply_url")
        if not (updated.get("source") or job.get("source")):
            raise HTTPException(status_code=400, detail="Source required when external_apply_url is provided")
    job.update(updated)
    redis_client.set(key, json.dumps(job))
    logger.info("✏️ Updated job %s", job_code)
    return {"message": "Job updated"}

def _build_match_response(
    job_code: str, job_id: str, matches: list[Any] | Any
) -> dict[str, Any]:
    """Return a standardized response payload for match endpoints."""

    status = "complete"
    results: list[Any] = matches if isinstance(matches, list) else []
    stored_payload_raw = redis_client.get(f"match_job:{job_id}")
    if stored_payload_raw is not None:
        try:
            stored_payload = json.loads(stored_payload_raw)
        except json.JSONDecodeError:
            stored_payload = None
        if isinstance(stored_payload, dict):
            status = stored_payload.get("status", status)
            stored_results = stored_payload.get("results")
            if isinstance(stored_results, list):
                results = stored_results
        elif isinstance(stored_payload, list):
            results = stored_payload
    else:
        payload = {"status": status, "results": results}
        redis_client.set(f"match_job:{job_id}", json.dumps(payload))

    redis_client.set(f"match_job_lookup:{job_code}", job_id)

    return {
        "job_id": job_id,
        "status": status,
        "results": results,
        "matches": results,
    }


@app.post("/match")
def match_job(
    req: JobCodeRequest,
    request: Request,
    _background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """Launch a background matching job and return immediately."""

    job_id = str(uuid.uuid4())

    enqueue_time = datetime.now().timestamp()
    request_id = getattr(request.state, "request_id", None)
    logger.info(
        "⚙️ Executing match synchronously for job %s (job_id=%s, request_id=%s)",
        req.job_code,
        job_id,
        request_id,
    )
    matches = match_worker(req.job_code, False, enqueue_time, job_id=job_id)
    return _build_match_response(req.job_code, job_id, matches)


@app.post("/rematches/{job_code}")
def rematch_job(
    job_code: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Queue a rematch computation without notifying students."""
    enq_time = datetime.now().timestamp()
    job_id = str(uuid.uuid4())
    request_id = getattr(request.state, "request_id", None)
    logger.info(
        "🔁 Executing rematch synchronously for job %s (job_id=%s, request_id=%s)",
        job_code,
        job_id,
        request_id,
    )
    matches = match_worker(job_code, False, enq_time, job_id=job_id)
    return _build_match_response(job_code, job_id, matches)


def _max_travel_distance(student: dict[str, Any]) -> float:
    """Return the student's maximum travel distance as a float."""

    value = student.get("max_travel", 0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


async def filter_candidates(
    candidates: list[tuple[dict[str, Any], list[float], tuple[float, float]]],
    distances: dict[tuple[float, float], float],
    job_emb: list[float],
    *,
    batch_size: int = 25,
    job_code: str | None = None,
    job_identifier: str | None = None,
) -> tuple[list[dict[str, Any]], float]:
    """Filter candidate matches using vectorized similarity scoring."""

    if not candidates:
        return [], 0.0

    start = time.perf_counter()
    job_vector = np.asarray(job_emb, dtype=np.float32)

    filtered: list[dict[str, Any]] = []
    embeddings: list[np.ndarray] = []
    student_payloads: list[dict[str, Any]] = []
    distance_values: list[float] = []

    skipped_no_distance = 0
    skipped_travel = 0
    skipped_embedding = 0

    for student, emb, coord in candidates:
        dist = distances.get(coord)
        if dist is None:
            skipped_no_distance += 1
            continue
        if dist > _max_travel_distance(student):
            skipped_travel += 1
            continue
        try:
            emb_vec = np.asarray(emb, dtype=np.float32)
        except Exception:
            skipped_embedding += 1
            continue
        if emb_vec.shape != job_vector.shape:
            skipped_embedding += 1
            continue
        embeddings.append(emb_vec)
        student_payloads.append(student)
        distance_values.append(dist)

    if embeddings:
        candidate_matrix = np.vstack(embeddings)
        scores = candidate_matrix @ job_vector
    else:
        scores = np.empty(0, dtype=np.float32)

    for idx, student in enumerate(student_payloads):
        score = float(scores[idx]) if idx < len(scores) else 0.0
        filtered.append(
            {
                "name": f"{student.get('first_name', '')} {student.get('last_name', '')}",
                "first_name": student.get("first_name", ""),
                "last_name": student.get("last_name", ""),
                "email": student.get("email"),
                "score": score,
                "distance_miles": round(distance_values[idx], 1),
            }
        )

    total_duration = time.perf_counter() - start

    logger.info(
        "🏃 Vectorized candidate filtering evaluated %s candidates (kept %s, skipped %s distance / %s travel / %s embedding) in %.2fs",
        len(candidates),
        len(filtered),
        skipped_no_distance,
        skipped_travel,
        skipped_embedding,
        total_duration,
    )

    if job_code is not None:
        logger.info(
            "✅ Candidate filtering finished with %s candidates in %.2fs for job %s (job_id=%s)",
            len(filtered),
            total_duration,
            job_code,
            job_identifier or "n/a",
        )
    else:
        logger.info(
            "✅ Candidate filtering finished with %s candidates in %.2fs",
            len(filtered),
            total_duration,
        )
    return filtered, total_duration


async def _perform_match_async(
    job_code: str,
    send_emails: bool = False,
    enq_time: float | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    job_id: str | None = None,
):
    overall_start = time.perf_counter()
    job_start = overall_start
    overall_wall_start = time.time()
    job_identifier = job_id or "n/a"
    logger.info(
        "⏱️ _perform_match_async started for job %s (job_id=%s) at %.6f",
        job_code,
        job_identifier,
        time.time(),
    )
    key = f"job:{job_code}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")
    logger.info(
        "📥 Retrieved job payload for job %s (job_id=%s) in %.2fs",
        job_code,
        job_identifier,
        time.perf_counter() - overall_start,
    )
    job = json.loads(raw)
    job.setdefault("uninterested_students", [])
    lookup_id = redis_client.get(f"match_job_lookup:{job_code}")
    was_matched_before = False
    if redis_client.exists(f"match_job:{job_code}"):
        was_matched_before = True
    elif lookup_id:
        existing_payload: str | None = redis_client.get(f"match_job:{lookup_id}")
        if existing_payload:
            try:
                parsed_payload = json.loads(existing_payload)
            except json.JSONDecodeError:
                was_matched_before = True
            else:
                status = str(parsed_payload.get("status", "")).lower()
                if status != "pending":
                    was_matched_before = True

    required_license = license_to_code(job.get("required_license"))

    poster_code = None
    poster_raw = redis_client.get(f"user:{job.get('posted_by')}")
    if poster_raw:
        try:
            p_data = json.loads(poster_raw)
            poster_code = p_data.get("institutional_code") or p_data.get("school_code")
        except Exception:
            poster_code = None

    combined = job.get("job_description", "") + " " + ", ".join(job.get("desired_skills", []))
    embed_start = time.perf_counter()
    embedding_wall_start = time.time()
    try:
        resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
        job_emb = resp.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")
    embed_end = time.perf_counter()
    embed_elapsed = embed_end - embed_start
    embedding_wall_end = time.time()
    embedding_time = embedding_wall_end - embedding_wall_start
    logger.info(
        "⏱️ Embeddings started at %.6f, completed at %.6f, duration=%.2fs for job %s (job_id=%s)",
        embed_start,
        embed_end,
        embed_elapsed,
        job_code,
        job_identifier,
    )
    if progress_callback:
        try:
            progress_callback(
                "embeddings_complete",
                {"job_code": job_code, "elapsed": embed_elapsed},
            )
        except Exception:
            logger.exception("Progress callback failed during embeddings event")

    ensure_index(len(job_emb))
    search_start = time.perf_counter()
    faiss_time = 0.0
    filter_time = 0.0
    distance_time = 0.0
    filter_elapsed = 0.0
    elapsed_store = 0.0
    if vector_index is None:
        if progress_callback:
            try:
                progress_callback(
                    "search_complete",
                    {"job_code": job_code, "elapsed": 0.0, "candidate_count": 0},
                )
            except Exception:
                logger.exception("Progress callback failed during search event")
        total_time = time.time() - overall_wall_start
        logger.info(
            "🏁 Finished match job %s in %.2fs (embeddings %.2fs, FAISS %.2fs, filtering %.2fs, distances %.2fs, total %.2fs)",
            job_identifier,
            total_time,
            embedding_time,
            faiss_time,
            filter_time,
            distance_time,
            total_time,
        )
        payload = {"status": "complete", "results": []}
        storage_id = job_id or job_code
        redis_client.set(f"match_job:{storage_id}", json.dumps(payload))
        if job_id:
            redis_client.set(f"match_job_lookup:{job_code}", storage_id)
        if job_id and job_id != job_code:
            redis_delete(f"match_job:{job_code}")
        if progress_callback:
            try:
                progress_callback(
                    "stored",
                    {"job_code": job_code, "match_count": 0},
                )
            except Exception:
                logger.exception("Progress callback failed during stored event")
        return []

    matches = []
    if vector_index.ntotal == 0:
        rebuild_vector_index()
    search_vec = np.array([job_emb], dtype="float32")
    k = min(50, vector_index.ntotal)
    if k > 0:
        candidates = vector_emails
        logger.info(
            "🔍 Starting FAISS search for job %s with %d candidates",
            job_identifier,
            len(candidates),
        )
        faiss_start = time.time()
        sims, idxs = vector_index.search(search_vec, k)
        faiss_time = time.time() - faiss_start
        similarities = sims[0]
        logger.info(
            "✅ FAISS search completed in %.2fs with %d results for job %s",
            faiss_time,
            len(similarities),
            job_identifier,
        )
        candidate_emails = [vector_emails[i] for i in idxs[0] if i != -1]
    else:
        candidate_emails = []
    search_end = time.perf_counter()
    search_elapsed = search_end - search_start
    logger.info(
        "🔍 FAISS similarity search completed at %.6f (duration=%.2fs) for job %s (job_id=%s) with %s candidates",
        search_end,
        search_elapsed,
        job_code,
        job_identifier,
        len(candidate_emails),
    )
    if progress_callback:
        try:
            progress_callback(
                "search_complete",
                {
                    "job_code": job_code,
                    "elapsed": search_elapsed,
                    "candidate_count": len(candidate_emails),
                },
            )
        except Exception:
            logger.exception("Progress callback failed during search event")

    candidates: list[tuple[dict, list, tuple[float, float]]] = []
    candidate_coords: list[tuple[float, float]] = []
    filtering_wall_start = time.time()
    filtering_perf_start = time.perf_counter()
    filter_wall_start = filtering_wall_start
    logger.info(
        "🔎 Filtering candidates started at %.6f with %d raw candidates for job %s (job_id=%s)",
        filtering_wall_start,
        len(candidate_emails),
        job_code,
        job_identifier,
    )

    for email in candidate_emails:
        skey = resolve_student_key(email)
        student_raw = redis_client.get(skey) if skey else None
        if not student_raw:
            continue
        try:
            student = json.loads(student_raw)
            emb = student.get("embedding")
            if not emb:
                continue
            if student.get("email") in job.get("uninterested_students", []):
                continue
            student_license = license_to_code(student.get("license") or student.get("education_level"))
            if required_license and student_license != required_license:
                continue
            student_user_raw = redis_client.get(f"user:{student.get('email')}")
            if student_user_raw and poster_code:
                try:
                    su = json.loads(student_user_raw)
                    stu_code = su.get("institutional_code") or su.get("school_code")
                    if su.get("role") == "applicant" and stu_code != poster_code:
                        continue
                except Exception:
                    pass
            coord = (float(student.get("lat")), float(student.get("lng")))
            candidate_coords.append(coord)
            candidates.append((student, emb, coord))
        except Exception:
            continue

    logger.info(
        "🗺️ Preparing distance lookups for job %s (job_id=%s) with %s origins",
        job_code,
        job_identifier,
        len(candidate_coords),
    )
    if progress_callback:
        try:
            progress_callback(
                "start",
                {"job_code": job_code, "candidate_count": len(candidates)},
            )
        except Exception:
            logger.exception("Progress callback failed during start event")

    distances: dict[tuple[float, float], float] = {}
    distance_elapsed = 0.0
    if candidate_coords:
        try:
            logger.info(
                f"🛠️ Preparing distance batches for job {job_code} ({len(candidate_coords)} origins)"
            )
            distance_start = time.perf_counter()
            distance_wall_start = time.time()
            coro = get_driving_distance_miles(
                candidate_coords,
                dest_lat=job.get("lat"),
                dest_lng=job.get("lng"),
                job_code=job_code,
                job_id=job_identifier,
            )
            result = await coro if asyncio.iscoroutine(coro) else coro
            if isinstance(result, dict):
                distances = result
            elif isinstance(result, (int, float)):
                distances = {coord: float(result) for coord in candidate_coords}
        except Exception:
            distances = {}
        finally:
            distance_elapsed = time.perf_counter() - distance_start
            distance_time = time.time() - distance_wall_start
    if progress_callback:
        try:
            progress_callback(
                "distances_complete",
                {
                    "job_code": job_code,
                    "elapsed": distance_elapsed,
                    "candidate_count": len(candidate_coords),
                },
            )
        except Exception:
            logger.exception("Progress callback failed during distance completion event")
    logger.info(
        "⏱️ Distance lookups completed in %.2fs for job %s (job_id=%s) (%s origins)",
        distance_elapsed,
        job_code,
        job_identifier,
        len(candidate_coords),
    )

    matches, filter_elapsed = await filter_candidates(
        candidates,
        distances,
        job_emb,
        job_code=job_code,
        job_identifier=job_identifier,
    )
    filtered_candidates = list(matches)
    logger.info(
        "✅ Candidate filtering completed for job %s (job_id=%s) in %.2fs, kept %d candidates",
        job_code,
        job_identifier,
        filter_elapsed,
        len(filtered_candidates),
    )
    filtering_wall_end = time.time()
    filtering_perf_elapsed = time.perf_counter() - filtering_perf_start
    logger.info(
        "✅ Filtering completed at %.6f, kept %d candidates, duration=%.2fs for job %s (job_id=%s)",
        filtering_wall_end,
        len(matches),
        filtering_perf_elapsed,
        job_code,
        job_identifier,
    )

    # Deduplicate by email
    dedup: dict[str, dict] = {}
    for m in matches:
        dedup[m["email"]] = m
    matches = list(dedup.values())
    logger.info(
        "🧮 Raw matches ready for filtering for job %s (job_id=%s): %s candidates",
        job_code,
        job_identifier,
        len(matches),
    )

    assigned = set(job.get("assigned_students", []))
    placed = set(job.get("placed_students", []))
    rejected = set(job.get("rejected_students", []))

    logger.info(
        "⚙️ Starting candidate filtering for job %s with %d raw matches",
        job_identifier,
        len(matches),
    )
    filter_wall_start = time.time()

    matches.sort(key=lambda x: x["score"], reverse=True)

    # Exclude already assigned students from the match limit so recruiters
    # can always receive up to 10 new candidates regardless of how many
    # students have been assigned.
    filtered_matches = [m for m in matches if m["email"] not in assigned]
    top_matches = filtered_matches[:10]

    # Only store unassigned/unplaced/unrejected matches and keep
    # the list length at a maximum of 10. Assigned candidates will be
    # reattached when retrieving match results.
    filtered = [
        m
        for m in matches
        if m["email"] not in assigned
        and m["email"] not in placed
        and m["email"] not in rejected
    ]

    top_matches = filtered[:10]

    for m in top_matches:
        if m["email"] in placed:
            m["status"] = "placed"
        elif m["email"] in rejected:
            m["status"] = "rejected"
        else:
            m["status"] = None

    filter_time = time.time() - filter_wall_start
    filtered_candidates = top_matches
    logger.info(
        "✅ Candidate filtering completed in %.2fs, kept %d candidates for job %s",
        filter_time,
        len(filtered_candidates),
        job_identifier,
    )
    logger.info(
        "🎯 Filtered top matches for job %s (job_id=%s): keeping %s candidates",
        job_code,
        job_identifier,
        len(top_matches),
    )

    payload = {"status": "complete", "results": top_matches}
    storage_id = job_id or job_code
    store_wall_start = time.time()
    store_perf_start = time.perf_counter()
    logger.info(
        "💾 Storing %s matches to Redis started at %.6f for job %s (job_id=%s)",
        len(top_matches),
        store_wall_start,
        job_code,
        job_identifier,
    )
    final_results = top_matches
    t_store = time.perf_counter()
    logger.info(
        "💾 Storing %d match results to Redis for job %s (job_id=%s)",
        len(final_results),
        job_code,
        job_identifier,
    )
    redis_client.set(f"match_job:{storage_id}", json.dumps(payload))
    elapsed_store = time.perf_counter() - t_store
    logger.info(
        "✅ Redis store completed for job %s (job_id=%s) in %.2fs",
        job_code,
        job_identifier,
        elapsed_store,
    )
    store_perf_elapsed = time.perf_counter() - store_perf_start
    store_wall_end = time.time()
    logger.info(
        "✅ Storing completed at %.6f, duration=%.2fs for job %s (job_id=%s)",
        store_wall_end,
        store_perf_elapsed,
        job_code,
        job_identifier,
    )
    if job_id:
        redis_client.set(f"match_job_lookup:{job_code}", storage_id)
    store_time = time.perf_counter()
    logger.info(
        "✅ Match results persisted for job %s (job_id=%s) at %.6f (elapsed %.2fs) with payload size %s",
        job_code,
        job_identifier,
        store_time,
        store_time - overall_start,
        len(top_matches),
    )
    if job_id and job_id != job_code:
        redis_delete(f"match_job:{job_code}")
    if progress_callback:
        try:
            progress_callback(
                "stored",
                {"job_code": job_code, "match_count": len(top_matches)},
            )
        except Exception:
            logger.exception("Progress callback failed during stored event")

    if send_emails:
        logger.info(
            "📧 Preparing to send %s notification emails for job %s (job_id=%s)",
            len(top_matches),
            job_code,
            job_identifier,
        )
        t_emails = time.perf_counter()
        logger.info(
            "📧 Starting email notifications for job %s (job_id=%s), sending %s emails",
            job_code,
            job_identifier,
            len(top_matches),
        )
        emails_sent = 0
        for m in top_matches:
            send_email(
                m["email"],
                f"New Job Match: {job.get('job_title')}",
                (
                    f"Hello {m['name']},\n\n"
                    f"You have been matched with the job '{job.get('job_title')}'. "
                    "This means that your resume is being reviewed by a recruiter to determine compatibility with any open assignments within their organization."
                ),
            )
            emails_sent += 1
        logger.info(
            "📬 Sent %s notification emails for job %s (job_id=%s)",
            emails_sent,
            job_code,
            job_identifier,
        )
        elapsed_emails = time.perf_counter() - t_emails
        logger.info(
            "✅ Email notifications finished in %.2fs for job %s (job_id=%s)",
            elapsed_emails,
            job_code,
            job_identifier,
        )

    # Metrics tracking
    try:
        avg_score = (
            sum(m["score"] for m in matches) / len(matches)
            if matches
            else 0.0
        )
        if was_matched_before:
            redis_client.incr("metrics:total_rematches")
        else:
            redis_client.incr("metrics:total_matches")
        redis_client.incrbyfloat("metrics:total_match_score", avg_score)
        redis_client.set(
            "metrics:last_match_timestamp", datetime.now().isoformat()
        )
    except Exception:
        pass

    post_processing_elapsed = time.perf_counter() - embed_start
    logger.info(
        "🚩 Finished all post-processing for job %s (job_id=%s) in %.2fs",
        job_code,
        job_identifier,
        post_processing_elapsed,
    )
    total_elapsed = time.perf_counter() - job_start
    logger.info(
        "🏁 Match job %s (job_id=%s) fully completed in %.2fs (embeddings %.2fs, FAISS %.2fs, filtering %.2fs, distances %.2fs, persistence %.2fs)",
        job_code,
        job_identifier,
        total_elapsed,
        embedding_time,
        faiss_time,
        filter_elapsed,
        distance_time,
        elapsed_store,
    )

    return top_matches


def _perform_match(
    job_code: str,
    send_emails: bool = False,
    enq_time: float | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    job_id: str | None = None,
):
    """Synchronous wrapper for background execution."""
    return asyncio.run(
        _perform_match_async(
            job_code,
            send_emails,
            enq_time,
            progress_callback,
            job_id=job_id,
        )
    )


def match_worker(
    job_code: str,
    send_emails: bool = False,
    enq_time: float | None = None,
    job_id: str | None = None,
):
    job_identifier = job_id or "n/a"
    start = datetime.now()
    worker_start = time.perf_counter()
    logger.info(
        "🔎 match_worker started for job %s (job_id=%s) at %.6f",
        job_code,
        job_identifier,
        time.time(),
    )
    timings: dict[str, float] = {}

    def progress_callback(event: str, payload: dict[str, Any]) -> None:
        job = payload.get("job_code", job_code)
        if event == "embeddings_complete":
            elapsed = payload.get("elapsed")
            if elapsed is not None:
                timings["embeddings"] = float(elapsed)
                logger.info(
                    "⏱️ Embeddings completed in %.2fs for job %s (job_id=%s)",
                    float(elapsed),
                    job,
                    job_identifier,
                )
            return
        if event == "search_complete":
            elapsed = payload.get("elapsed")
            if elapsed is not None:
                timings["search"] = float(elapsed)
                logger.info(
                    "⏱️ Candidate similarity search completed in %.2fs for job %s (job_id=%s) (%s candidates)",
                    float(elapsed),
                    job,
                    job_identifier,
                    payload.get("candidate_count", 0),
                )
            return
        if event == "start":
            logger.info(
                "🚦 Match job %s (job_id=%s) starting with %s candidates",
                job,
                job_identifier,
                payload.get("candidate_count", 0),
            )
        elif event == "distances_complete":
            elapsed = payload.get("elapsed")
            if elapsed is not None:
                timings["distances"] = float(elapsed)
                logger.info(
                    "⏱️ Distance lookups completed in %.2fs for job %s (job_id=%s) (%s origins)",
                    float(elapsed),
                    job,
                    job_identifier,
                    payload.get("candidate_count", 0),
                )
            else:
                logger.info(
                    "⏱️ Distance lookups completed for job %s (job_id=%s)",
                    job,
                    job_identifier,
                )
        elif event == "stored":
            logger.info(
                "✅ Stored %s matches for job %s (job_id=%s)",
                payload.get("match_count", 0),
                job,
                job_identifier,
            )

    if enq_time is not None:
        queue_time = start - datetime.fromtimestamp(enq_time)
        redis_client.incrbyfloat("metrics:match_queue_time", queue_time.total_seconds())
    result = _perform_match(
        job_code,
        send_emails,
        enq_time,
        progress_callback,
        job_id=job_id,
    )
    after_match = time.perf_counter()
    logger.info(
        "🧵 _perform_match_async completed for job %s (job_id=%s) at %.6f (elapsed %.2fs)",
        job_code,
        job_identifier,
        after_match,
        after_match - worker_start,
    )
    process_time = datetime.now() - start
    redis_client.incrbyfloat("metrics:match_process_time", process_time.total_seconds())
    t_total = after_match - worker_start
    t_emb = timings.get("embeddings", 0.0)
    t_search = timings.get("search", 0.0)
    t_dist = timings.get("distances", 0.0)
    t_other = max(t_total - (t_emb + t_search + t_dist), 0.0)
    logger.info(
        "✅ match_worker finished job %s (job_id=%s) in %.2fs (embeddings %.2fs, search %.2fs, distances %.2fs, other %.2fs)",
        job_code,
        job_identifier,
        t_total,
        t_emb,
        t_search,
        t_dist,
        t_other,
    )
    logger.info(
        "⬅️ match_worker returning results for job %s (job_id=%s) at %.6f",
        job_code,
        job_identifier,
        time.time(),
    )
    return result


@app.get("/match/{job_code}")
def get_match_results(job_code: str, current_user: dict = Depends(get_current_user)):
    lookup_key = f"match_job_lookup:{job_code}"
    storage_id = redis_client.get(lookup_key)
    candidate_keys: list[str] = []
    if storage_id:
        candidate_keys.append(f"match_job:{storage_id}")
    candidate_keys.append(f"match_job:{job_code}")

    results_json: str | None = None
    for candidate in candidate_keys:
        payload_json = redis_client.get(candidate)
        if payload_json is not None:
            results_json = payload_json
            break

    if results_json is None:
        legacy_key = f"match_results:{job_code}"
        legacy_json = redis_client.get(legacy_key)
        if legacy_json is not None:
            results_json = legacy_json

    if results_json is None:
        logger.warning("⚠️ No match results found for job %s", job_code)
        return {"matches": []}

    try:
        parsed = json.loads(results_json)
    except json.JSONDecodeError:
        logger.warning("⚠️ Stored match payload for job %s was not JSON", job_code)
        return {"matches": []}

    if isinstance(parsed, dict):
        stored_matches = parsed.get("results", [])
    elif isinstance(parsed, list):
        stored_matches = parsed
    else:
        stored_matches = []

    try:
        matches = {m["email"]: m for m in stored_matches}
        logger.info("📦 Returning %s stored matches for job %s", len(matches), job_code)

        # Ensure each match has first and last name fields
        for m in matches.values():
            if "first_name" not in m or "last_name" not in m:
                parts = m.get("name", "").split(" ", 1)
                m.setdefault("first_name", parts[0] if parts else "")
                m.setdefault("last_name", parts[1] if len(parts) > 1 else "")

        job_raw = redis_client.get(f"job:{job_code}")
        if not job_raw:
            raise HTTPException(status_code=404, detail="Job not found")

        job = json.loads(job_raw)
        assigned = set(job.get("assigned_students", []))
        placed = set(job.get("placed_students", []))
        rejected = set(job.get("rejected_students", []))

        for email, m in matches.items():
            if email in placed:
                m["status"] = "placed"
            elif email in assigned:
                m["status"] = "assigned"
            elif email in rejected:
                m["status"] = "rejected"
            else:
                m["status"] = None

            notes_raw = job.get("student_notes", {}).get(email, [])
            notes, latest_note = _normalize_notes(notes_raw)
            m["notes"] = notes
            if latest_note is not None:
                m["note"] = latest_note

        return {"matches": list(matches.values())}
    except Exception as e:
        logger.error("❌ Failed to load match results for %s: %s", job_code, e)
        return {"matches": []}


@app.get("/has-match/{job_id}")
def has_match_data(job_id: str):
    storage_id = job_id
    key = f"match_job:{storage_id}"
    results_json = redis_client.get(key)

    if results_json is None:
        lookup_key = f"match_job_lookup:{job_id}"
        lookup_id = redis_client.get(lookup_key)
        if lookup_id:
            storage_id = lookup_id
            key = f"match_job:{storage_id}"
            results_json = redis_client.get(key)

    if results_json is None:
        return {"status": "pending"}

    try:
        payload = json.loads(results_json)
    except json.JSONDecodeError:
        logger.warning("⚠️ Match payload for job %s was not JSON", job_id)
        return {"status": "complete", "results": []}

    if isinstance(payload, dict):
        status = payload.get("status", "complete")
        results: list[Any] = payload.get("results", [])
    elif isinstance(payload, list):
        status = "complete"
        results = payload
    else:
        status = "complete"
        results = []

    logger.info(
        "✅ Returning %s results with status %s for job %s (storage id %s)",
        len(results),
        status,
        job_id,
        storage_id,
    )
    return {"status": status, "results": results}

@app.get("/jobs")
def list_jobs(current_user: dict = Depends(get_current_user)):
    jobs = []
    for key in redis_client.scan_iter("job:*"):
        job_data = redis_client.get(key)
        if job_data:
            job = json.loads(job_data)
            job.setdefault("assigned_students", [])
            job.setdefault("placed_students", [])
            job.setdefault("uninterested_students", [])
            job.setdefault("rejected_students", [])
            job.setdefault("student_notes", {})
            jobs.append(job)

    def _timestamp_value(job: dict[str, Any]) -> float:
        raw = job.get("timestamp")
        if not raw:
            return 0.0
        try:
            return datetime.fromisoformat(raw).timestamp()
        except (ValueError, TypeError):
            return 0.0

    jobs.sort(key=_timestamp_value, reverse=True)
    logger.info("Returning %s jobs from Redis", len(jobs))
    return {"jobs": jobs}


@app.delete("/jobs/{job_code}")
def delete_job(job_code: str, token_data: dict = Depends(get_current_user)):
    if token_data.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required")

    job_key = f"job:{job_code}"
    match_key = f"match_job:{job_code}"
    lookup_key = f"match_job_lookup:{job_code}"

    if not redis_client.exists(job_key):
        raise HTTPException(status_code=404, detail="Job not found")

    redis_delete(job_key)
    redis_delete(match_key)
    match_id = redis_client.get(lookup_key)
    if match_id:
        redis_delete(f"match_job:{match_id}")
    redis_delete(lookup_key)
    redis_delete(f"match_results:{job_code}")

    return {"message": f"Job {job_code} deleted successfully"}


class StudentLoadTimeMetric(BaseModel):
    role: str
    duration: float


@app.post("/metrics/student-load-time")
def record_student_load_time(
    metric: StudentLoadTimeMetric, current_user: dict = Depends(get_current_user)
):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "role": metric.role,
        "duration": metric.duration,
    }
    try:
        redis_client.rpush(STUDENT_LOAD_TIME_KEY, json.dumps(entry))
    except Exception as e:
        logger.error("Failed to record student load time metric: %s", e)
    return {"status": "ok"}


@app.get("/metrics")
def get_metrics(current_user: dict = Depends(get_current_user)):
    """Return various application metrics."""
    total_users = 0
    approved = 0
    rejected = 0
    pending = 0
    for key in redis_client.scan_iter("user:*"):
        raw = redis_client.get(key)
        if not raw:
            continue
        total_users += 1
        info = json.loads(raw)
        if info.get("approved"):
            approved += 1
        elif info.get("rejected"):
            rejected += 1
        else:
            pending += 1

    students = 0
    for key in redis_client.scan_iter("*"):
        skey = str(key)
        if (
            skey.startswith("user:")
            or skey.startswith("job:")
            or skey.startswith("metrics:")
            or skey.startswith("school_code:")
            or skey.startswith("license:")
            or skey.startswith(f"{REFRESH_TOKEN_LOOKUP_PREFIX}:")
            or skey.startswith(f"{REFRESH_TOKEN_USER_PREFIX}:")
        ):
            continue
        if redis_client.get(key):
            students += 1

    jobs = 0
    for key in redis_client.scan_iter("job:*"):
        if redis_client.get(key):
            jobs += 1

    (
        total_matches,
        total_match_score,
        total_placements,
        total_rematches,
        sum_time_to_place,
        match_queue_time,
        match_process_time,
    ) = [
        redis_client.get(k)
        for k in [
            "metrics:total_matches",
            "metrics:total_match_score",
            "metrics:total_placements",
            "metrics:total_rematches",
            "metrics:sum_time_to_place",
            "metrics:match_queue_time",
            "metrics:match_process_time",
        ]
    ]
    total_matches = int(total_matches or 0)
    total_match_score = float(total_match_score or 0.0)
    total_placements = int(total_placements or 0)
    total_rematches = int(total_rematches or 0)
    sum_time_to_place = float(sum_time_to_place or 0.0)
    match_queue_time = float(match_queue_time or 0.0)
    match_process_time = float(match_process_time or 0.0)

    avg_match_score = (
        total_match_score / total_matches if total_matches else None
    )
    latest_match_timestamp = redis_client.get("metrics:last_match_timestamp")

    placement_rate = (
        total_placements / students if students else 0
    )
    avg_time_to_place = (
        sum_time_to_place / total_placements if total_placements else 0.0
    )
    avg_time_to_place = round(avg_time_to_place, 1)
    rematch_rate = (
        total_rematches / total_placements if total_placements else 0
    )

    license_counts: dict[str, int] = {}
    license_keys = list(redis_client.scan_iter("metrics:licensed:*"))
    if license_keys:
        values = redis_client.mget(license_keys)
        for k, v in zip(license_keys, values):
            lic = k.split("metrics:licensed:", 1)[1]
            license_counts[lic] = int(v or 0)

    return {
        "total_users": total_users,
        "approved_users": approved,
        "rejected_users": rejected,
        "pending_registrations": pending,
        "total_student_profiles": students,
        "total_jobs_posted": jobs,
        "total_matches": total_matches,
        "average_match_score": avg_match_score,
        "latest_match_timestamp": latest_match_timestamp,
        "placement_rate": placement_rate,
        "avg_time_to_placement_days": avg_time_to_place,
        "license_breakdown": license_counts,
        "rematch_rate": rematch_rate,
        "total_match_queue_time": match_queue_time,
        "total_match_process_time": match_process_time,
    }


class PlacementRequest(BaseModel):
    student_email: EmailStr
    job_code: str


@app.post("/place")
def place_student(data: dict, token_data: dict = Depends(get_current_user)):
    role = token_data.get("role")
    if role not in ADMIN_ROLES.union(CAREER_STAFF_ROLES):
        raise HTTPException(status_code=403, detail="Not authorized to place students")
    job_code = data["job_code"]
    student_email = normalize_email(data["student_email"])
    student_key_resolved = resolve_student_key(student_email)
    student_raw = redis_client.get(student_key_resolved) if student_key_resolved else None
    if not student_raw:
        raise HTTPException(status_code=404, detail="Student not found")
    try:
        student = json.loads(student_raw)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupted profile data")

    if role in CAREER_STAFF_ROLES:
        user_raw = redis_client.get(user_key(token_data.get("sub")))
        if not user_raw:
            raise HTTPException(status_code=404, detail="User not found")
        try:
            user = json.loads(user_raw)
        except Exception:
            raise HTTPException(status_code=500, detail="Corrupted user data")
        codes = _extract_institutional_codes(user)
        if not codes:
            raise HTTPException(status_code=400, detail="Institutional code required")
        st_code = _student_institutional_code(student)
        if not st_code or st_code.lower() not in {code.lower() for code in codes}:
            raise HTTPException(status_code=403, detail="Not authorized")
        if role == "career" and student.get("created_by") != token_data.get("sub"):
            raise HTTPException(status_code=403, detail="Not authorized")

    key = f"job:{job_code}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    job = json.loads(raw)
    job.setdefault("placed_students", [])
    job.setdefault("assigned_students", [])

    if student_email not in job["placed_students"]:
        job["placed_students"].append(student_email)
    if student_email in job["assigned_students"]:
        job["assigned_students"].remove(student_email)
        _remove_student_job(student_email, job_code, "assigned")

    _remove_student_job(student_email, job_code, "rejected")
    _remove_student_job(student_email, job_code, "uninterested")
    _add_student_job(student_email, job_code, "placed")

    redis_client.set(key, json.dumps(job))
    return {"message": f"Placed {student_email}"}

@app.post("/assign")
def assign_student(data: dict, token_data: dict = Depends(get_current_user)):
    job_code = data["job_code"]
    student_email = normalize_email(data["student_email"])
    note = data.get("note")
    key = f"job:{job_code}"
    try:
        raw = redis_client.get(key)
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        job = json.loads(raw)
        if not isinstance(job, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid student_notes format")
    role = token_data.get("role")
    if role == "recruiter" and job.get("posted_by") != token_data.get("sub"):
        raise HTTPException(status_code=403, detail="Not authorized to modify this job")
    if role not in ADMIN_ROLES | {"recruiter"}:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    job.setdefault("assigned_students", [])
    if student_email not in job["assigned_students"]:
        job["assigned_students"].append(student_email)
        _add_student_job(student_email, job_code, "assigned")
        _remove_student_job(student_email, job_code, "rejected")
        _remove_student_job(student_email, job_code, "uninterested")

    if note is not None:
        note_obj = {
            "text": note,
            "author": token_data["sub"],
            "timestamp": datetime.utcnow().isoformat(),
        }
        raw_notes = job.get("student_notes", {})
        if isinstance(raw_notes, str):
            try:
                notes_map = json.loads(raw_notes)
                if not isinstance(notes_map, dict):
                    raise ValueError
            except (json.JSONDecodeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid student_notes format")
        elif isinstance(raw_notes, dict):
            notes_map = raw_notes
        else:
            raise HTTPException(status_code=400, detail="Invalid student_notes format")

        existing = notes_map.get(student_email)
        if isinstance(existing, str):
            existing = [{"text": existing}]
        elif not isinstance(existing, list):
            existing = []
        existing.append(note_obj)
        notes_map[student_email] = existing
        job["student_notes"] = notes_map

    try:
        redis_client.set(key, json.dumps(job))
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    resp = {"message": f"Assigned {student_email}"}
    if note is not None:
        resp["notes"] = job["student_notes"][student_email]
    return resp


@app.post("/reject-assigned")
def reject_assigned_student(data: dict, token_data: dict = Depends(get_current_user)):
    """Remove an assigned student from a job and record a note."""
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    note = data.get("note")
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")

    key = f"job:{job_code}"
    try:
        raw = redis_client.get(key)
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        job = json.loads(raw)
        if not isinstance(job, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid student_notes format")
    role = token_data.get("role")
    if role == "recruiter" and job.get("posted_by") != token_data.get("sub"):
        raise HTTPException(status_code=403, detail="Not authorized to modify this job")
    if role not in ADMIN_ROLES | {"recruiter"}:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    job.setdefault("assigned_students", [])
    job.setdefault("rejected_students", [])

    if student_email in job["assigned_students"]:
        job["assigned_students"].remove(student_email)
        _remove_student_job(student_email, job_code, "assigned")
    if student_email not in job["rejected_students"]:
        job["rejected_students"].append(student_email)
        _add_student_job(student_email, job_code, "rejected")
    _remove_student_job(student_email, job_code, "placed")
    _remove_student_job(student_email, job_code, "uninterested")

    if note is not None:
        note_obj = {
            "text": note,
            "author": token_data["sub"],
            "timestamp": datetime.utcnow().isoformat(),
        }
        raw_notes = job.get("student_notes", {})
        if isinstance(raw_notes, str):
            try:
                notes_map = json.loads(raw_notes)
                if not isinstance(notes_map, dict):
                    raise ValueError
            except (json.JSONDecodeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid student_notes format")
        elif isinstance(raw_notes, dict):
            notes_map = raw_notes
        else:
            raise HTTPException(status_code=400, detail="Invalid student_notes format")

        existing = notes_map.get(student_email)
        if isinstance(existing, str):
            existing = [{"text": existing}]
        elif not isinstance(existing, list):
            existing = []
        existing.append(note_obj)
        notes_map[student_email] = existing
        job["student_notes"] = notes_map

    try:
        redis_client.set(key, json.dumps(job))
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    resp = {"message": "Student rejected"}
    if note is not None:
        resp["notes"] = job["student_notes"][student_email]
    return resp


@app.post("/student-note")
def student_note(data: dict, token_data: dict = Depends(get_current_user)):
    """Create or update a note for a student on a job."""
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    note = data.get("note")
    if not job_code or not student_email or note is None:
        raise HTTPException(status_code=400, detail="Missing job_code, student_email, or note")

    key = f"job:{job_code}"
    try:
        raw = redis_client.get(key)
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        job = json.loads(raw)
        if not isinstance(job, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid student_notes format")

    role = token_data.get("role")
    if role in ADMIN_ROLES:
        pass
    elif role == "recruiter" and (
        job.get("posted_by") == token_data.get("sub")
        and student_email in job.get("assigned_students", [])
    ):
        pass
    else:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    # Ensure student_notes is a dict; handle both dict and JSON string forms
    raw_notes = job.get("student_notes", {})
    if isinstance(raw_notes, str):
        try:
            notes_map = json.loads(raw_notes)
            if not isinstance(notes_map, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid student_notes format")
    elif isinstance(raw_notes, dict):
        notes_map = raw_notes
    else:
        raise HTTPException(status_code=400, detail="Invalid student_notes format")

    note_obj = {
        "text": note,
        "author": token_data["sub"],
        "timestamp": datetime.utcnow().isoformat(),
    }
    existing = notes_map.get(student_email)
    if isinstance(existing, str):
        existing = [{"text": existing}]
    elif not isinstance(existing, list):
        existing = []
    existing.append(note_obj)
    notes_map[student_email] = existing
    job["student_notes"] = notes_map

    try:
        redis_client.set(key, json.dumps(job))
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    return {"email": student_email, "notes": notes_map[student_email]}


@app.put("/student-note")
def update_student_note(data: dict, token_data: dict = Depends(get_current_user)):
    """Update an existing note for a student on a job."""
    if token_data.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    index = data.get("index")
    note = data.get("note")
    if not job_code or not student_email or note is None or index is None:
        raise HTTPException(
            status_code=400,
            detail="Missing job_code, student_email, index, or note",
        )
    try:
        index = int(index)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid index")

    key = f"job:{job_code}"
    try:
        raw = redis_client.get(key)
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        job = json.loads(raw)
        if not isinstance(job, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid student_notes format")

    raw_notes = job.get("student_notes", {})
    if isinstance(raw_notes, str):
        try:
            notes_map = json.loads(raw_notes)
            if not isinstance(notes_map, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid student_notes format")
    elif isinstance(raw_notes, dict):
        notes_map = raw_notes
    else:
        raise HTTPException(status_code=400, detail="Invalid student_notes format")

    existing = notes_map.get(student_email)
    if isinstance(existing, str):
        existing = [{"text": existing}]
    elif not isinstance(existing, list):
        existing = []
    if index < 0 or index >= len(existing):
        raise HTTPException(status_code=404, detail="Note not found")

    note_obj = {
        "text": note,
        "author": token_data["sub"],
        "timestamp": datetime.utcnow().isoformat(),
    }
    existing[index] = note_obj
    notes_map[student_email] = existing
    job["student_notes"] = notes_map

    try:
        redis_client.set(key, json.dumps(job))
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    return {"email": student_email, "notes": notes_map[student_email]}


@app.delete("/student-note")
def delete_student_note(data: dict, token_data: dict = Depends(get_current_user)):
    """Delete a note for a student on a job by index."""
    if token_data.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    index = data.get("index")
    if not job_code or not student_email or index is None:
        raise HTTPException(
            status_code=400, detail="Missing job_code, student_email, or index"
        )
    try:
        index = int(index)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid index")

    key = f"job:{job_code}"
    try:
        raw = redis_client.get(key)
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        job = json.loads(raw)
        if not isinstance(job, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid student_notes format")

    raw_notes = job.get("student_notes", {})
    if isinstance(raw_notes, str):
        try:
            notes_map = json.loads(raw_notes)
            if not isinstance(notes_map, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid student_notes format")
    elif isinstance(raw_notes, dict):
        notes_map = raw_notes
    else:
        raise HTTPException(status_code=400, detail="Invalid student_notes format")

    existing = notes_map.get(student_email)
    if isinstance(existing, str):
        existing = [{"text": existing}]
    elif not isinstance(existing, list):
        existing = []
    if index < 0 or index >= len(existing):
        raise HTTPException(status_code=404, detail="Note not found")

    existing.pop(index)
    notes_map[student_email] = existing
    job["student_notes"] = notes_map

    try:
        redis_client.set(key, json.dumps(job))
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    return {"email": student_email, "notes": notes_map.get(student_email, [])}


@app.post("/not-interested")
def mark_not_interested(data: dict, token_data: dict = Depends(get_current_user)):
    """Record that a student is not interested in a job."""
    job_code = data.get("job_code")
    student_email = normalize_email(data.get("student_email"))
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")

    key = f"job:{job_code}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    job = json.loads(raw)
    job.setdefault("uninterested_students", [])
    if student_email not in job["uninterested_students"]:
        job["uninterested_students"].append(student_email)
        _add_student_job(student_email, job_code, "uninterested")

    redis_client.set(key, json.dumps(job))
    return {"message": "Not interested recorded"}


@app.post("/notify-interest")
def notify_interest(data: dict, token_data: dict = Depends(get_current_user)):
    """Notify a student that a recruiter is interested and send them a job description."""
    job_code = data.get("job_code")
    student_email = data.get("student_email")
    if not job_code or not student_email:
        raise HTTPException(status_code=400, detail="Missing job_code or student_email")

    key = f"job:{job_code}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    job = json.loads(raw)
    if student_email not in job.get("assigned_students", []) and student_email not in job.get("placed_students", []):
        raise HTTPException(status_code=400, detail="Student not assigned to job")

    desc_html, _ = generate_job_description_html(job_code, student_email)

    skey = resolve_student_key(student_email)
    student_raw = redis_client.get(skey) if skey else None
    first_name = ""
    if student_raw:
        try:
            student = json.loads(student_raw)
            first_name = student.get("first_name", "")
        except Exception:
            pass

    public_url = (
        f"{SITE_BASE_URL}/public/job-description-html/{job_code}/{student_email}"
        if SITE_BASE_URL
        else f"/public/job-description-html/{job_code}/{student_email}"
    )
    summary = (
        f"Job: {job.get('job_title')} at {job.get('source', '')} in {job.get('city', '')}, {job.get('state', '')}"
    )
    token = str(uuid.uuid4())
    external_url = job.get("external_apply_url")
    body = (
        f"Hello {first_name},\n\n"
        f"{summary}\n\n"

        "Your resume has been matched with this job.\n\n"
        f"Please review the job description here: {public_url}\n\n"
    )
    html_body = (
        f"<p>Hello {first_name},</p>"
        f"<p>{summary}</p>"
        "<p>Your resume has been matched with this job.</p>"
        f"<p>Please review the job description <a href=\"{public_url}\">here</a>.</p>"
    )
    if external_url:
        click_url = (
            f"{SITE_BASE_URL}/track/click/{token}"
            if SITE_BASE_URL
            else f"/track/click/{token}"
        )
        body += f"You must apply using the following link: {click_url}\n\n"
        html_body += (
            f"<p>You must apply using the following link: "
            f"<a href=\"{click_url}\">Apply Now</a></p>"
        )
    body += "Good Luck!\n\nSupport Team @ TalentMatch-AI"
    html_body += "<p>Good Luck!</p><p>Support Team @ TalentMatch-AI</p>"
    try:
        redis_client.hset(
            EMAIL_OPEN_TOKENS_KEY,
            token,
            json.dumps(
                {
                    "student_email": student_email,
                    "job_code": job_code,
                    "external_url": external_url,
                    "sent": datetime.now(timezone.utc).isoformat(),
                }
            ),
        )
    except Exception as e:
        logger.error("Failed to store email open token: %s", e)
    try:
        send_email(
            student_email,
            f"Job Match: {job.get('job_title')}",
            body,
            html_body=html_body,
            track_token=token,
        )
    except Exception as e:
        logger.error("Notification email failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to send notification email")

    return {"message": "Notification sent"}


@app.post("/generate-resume")
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


@app.post("/generate-description")
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


@app.post("/generate-job-description")
def generate_job_description(req: ResumeRequest, current_user: dict = Depends(get_current_user)):
    html, existed = generate_job_description_html(req.job_code, req.student_email)
    return {"status": "exists"} if existed else {"status": "success"}


@app.get("/job-description/{job_code}/{student_email}")
def get_job_description(job_code: str, student_email: str, current_user: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    key = f"job_description:{job_code}:{student_email}"
    description = redis_client.get(key)
    if not description:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "success", "description": description}


@app.get("/job-description-html/{job_code}/{student_email}")
def get_job_description_html(job_code: str, student_email: str, current_user: dict = Depends(get_current_user)):
    student_email = normalize_email(student_email)
    key = f"jobdesc:{job_code}:{student_email}"
    html = redis_client.get(key)
    if not html:
        raise HTTPException(status_code=404, detail="Job description not found")
    return HTMLResponse(content=html, status_code=200)


# Public version of the job description HTML without auth
@app.get("/public/job-description-html/{job_code}/{student_email}")
def get_public_job_description_html(job_code: str, student_email: str):
    student_email = normalize_email(student_email)
    key = f"jobdesc:{job_code}:{student_email}"
    html = redis_client.get(key)
    if not html:
        raise HTTPException(status_code=404, detail="Job description not found")
    return HTMLResponse(content=html, status_code=200)


@app.get("/resume/{job_code}/{student_email}")
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


@app.get("/resume-html/{job_code}/{student_email}")
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






@app.get("/placements/{student_email}")
def get_placements(
    student_email: str, current_user: dict = Depends(get_current_user)
):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    student_email = normalize_email(student_email)
    key = resolve_student_key(student_email)
    if not key or not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Student not found")

    raw = redis_client.get(key)
    student = json.loads(raw) if raw else {}
    return student.get("placement_history", [])


@app.delete("/admin/reset-jobs")
def reset_jobs(current_user: dict = Depends(get_current_user)):
    """Delete all job postings and their stored match results."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")

    deleted = 0
    for key in list(redis_client.scan_iter("job:*")):
        redis_delete(key)
        deleted += 1
    for key in list(redis_client.scan_iter("match_job:*")):
        redis_delete(key)
    for key in list(redis_client.scan_iter("match_job_lookup:*")):
        redis_delete(key)
    for key in list(redis_client.scan_iter("match_results:*")):
        redis_delete(key)

    return {"message": f"Deleted {deleted} jobs and match data"}


@app.delete("/admin/student-claims/{email}")
def clear_student_claim(email: str, current_user: dict = Depends(get_current_user)):
    """Clear the claimed_by field and related claim tokens for a student."""
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    email = normalize_email(email)
    key = resolve_student_key(email)
    if not key or not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Student not found")

    raw = redis_client.get(key)
    student = json.loads(raw) if raw else {}
    student.pop("claimed_by", None)
    payload = json.dumps(student)
    redis_client.set(key, payload)
    redis_client.set(f"student:{email}", payload)

    for token_key in redis_client.scan_iter("student_claim:*"):
        k = token_key if isinstance(token_key, str) else token_key.decode()
        val = redis_client.get(k)
        if email in k or (isinstance(val, str) and normalize_email(val) == email):
            redis_delete(k)

    return {"message": f"Cleared claim for {email}"}


@app.delete("/admin/delete-student/{email}")
def delete_student(email: str, current_user: dict = Depends(get_current_user)):
    """Remove a student profile and any associated user record."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    email = normalize_email(email)
    skey = resolve_student_key(email)
    if not skey or not redis_client.exists(skey):
        raise HTTPException(status_code=404, detail="Student not found")

    # Delete student profile
    redis_delete(skey)
    redis_delete(student_email_key(email))

    # Remove any lingering user record to avoid bogus admin entries
    ukey = find_user_key(email)
    if ukey:
        redis_delete(ukey)

    # Clean up from job assignments/placements
    for job_key in redis_client.scan_iter("job:*"):
        raw = redis_client.get(job_key)
        if not raw:
            continue
        try:
            job = json.loads(raw)
        except Exception:
            continue

        assigned = job.get("assigned_students", [])
        placed = job.get("placed_students", [])

        updated = False
        if email in assigned:
            job["assigned_students"] = [e for e in assigned if e != email]
            updated = True
        if email in placed:
            job["placed_students"] = [e for e in placed if e != email]
            updated = True

        if updated:
            redis_client.set(job_key, json.dumps(job))

    # Remove resume if it exists
    for key in redis_client.scan_iter(f"resume:*:{email}"):
        redis_delete(key)

    # Remove job descriptions if any
    for key in redis_client.scan_iter(f"job_description:*:{email}"):
        redis_delete(key)

    # (Optional) Clean match results if student appears
    for match_key in redis_client.scan_iter("match_job:*"):
        raw = redis_client.get(match_key)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        if isinstance(data, dict):
            matches = data.get("results", [])
            status = data.get("status", "complete")
        elif isinstance(data, list):
            matches = data
            status = "complete"
        else:
            continue

        new_matches = [m for m in matches if m.get("email") != email]
        if len(new_matches) != len(matches):
            updated_payload = {"status": status, "results": new_matches}
            redis_client.set(match_key, json.dumps(updated_payload))

    for match_key in redis_client.scan_iter("match_results:*"):
        raw = redis_client.get(match_key)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        if isinstance(data, dict):
            matches = data.get("results", [])
            status = data.get("status", "complete")
        elif isinstance(data, list):
            matches = data
            status = "complete"
        else:
            continue

        new_matches = [m for m in matches if m.get("email") != email]
        if len(new_matches) != len(matches):
            updated_payload = {"status": status, "results": new_matches}
            redis_client.set(match_key, json.dumps(updated_payload))

    return {"message": f"Student {email} and related data deleted successfully"}


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

@app.get("/students/all")
def get_all_students(
    limit: int = 50,
    cursor: Optional[str] = None,
    license: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    cur = int(cursor or 0)
    students: list[dict] = []
    while len(students) < limit:
        cur, keys = redis_client.scan(cur, match="student:*", count=limit)
        for key in keys:
            raw = redis_client.get(key)
            if not raw:
                continue
            try:
                student = json.loads(raw)
            except Exception:
                continue

            email = student.get("email")
            st_license = student.get("license") or student.get("education_level")
            if license and (st_license or "").lower() != license.lower():
                continue

            assigned_codes = redis_client.smembers(
                _student_job_key(email, "assigned")
            )

            info = {
                "first_name": student.get("first_name"),
                "last_name": student.get("last_name"),
                "email": email,
                "phone": student.get("phone"),
                "city": student.get("city"),
                "state": student.get("state"),
                "license": st_license,
                "skills": student.get("skills"),
                "experience_summary": student.get("experience_summary"),
                "interests": student.get("interests"),
                "institutional_code": student.get("institutional_code")
                or student.get("school_code"),
                "assigned_job_code": next(iter(assigned_codes), None),
            }
            students.append(info)
            if len(students) >= limit:
                break
        if cur == 0:
            break
    next_cursor = None if cur == 0 else str(cur)
    return {"students": students, "next_cursor": next_cursor}


@app.post("/email-blast")
def send_email_blast(req: EmailBlastRequest, current_user: dict = Depends(get_current_user)):
    """Dispatch a bulk email to students matching the provided filters."""

    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    normalized_codes = {code.lower() for code in req.institutional_codes}
    license_filter = license_to_code(req.license)
    license_filter = license_filter.lower() if license_filter else None
    source_filter = req.source.lower() if req.source else None

    recipients: list[str] = []
    seen: set[str] = set()
    skipped_missing_email = 0
    skipped_filtered = 0

    cursor = 0
    while True:
        cursor, keys = redis_client.scan(cursor, match="student:*", count=200)
        for key in keys:
            raw = redis_client.get(key)
            if not raw:
                continue
            try:
                student = json.loads(raw)
            except Exception:
                continue

            email = normalize_email(student.get("email"))
            if not email:
                skipped_missing_email += 1
                continue
            if email in seen:
                continue

            st_code = _student_institutional_code(student)
            if normalized_codes and (
                not st_code or st_code.strip().lower() not in normalized_codes
            ):
                skipped_filtered += 1
                continue

            st_license = license_to_code(
                student.get("license") or student.get("education_level")
            )
            st_license = st_license.lower() if st_license else None
            if license_filter and st_license != license_filter:
                skipped_filtered += 1
                continue

            st_source = (student.get("source") or "").strip().lower()
            if source_filter and st_source != source_filter:
                skipped_filtered += 1
                continue

            recipients.append(email)
            seen.add(email)

        if cursor == 0:
            break

    if not recipients:
        raise HTTPException(
            status_code=400, detail="No students match the provided criteria"
        )

    blast_id = str(uuid.uuid4())
    blast_timestamp = datetime.now(timezone.utc).isoformat()
    stats_key = _blast_stats_key(blast_id)
    recipients_key = _blast_recipients_key(blast_id)
    filters_payload = {
        "institutional_codes": list(req.institutional_codes),
        "license": req.license,
        "source": req.source,
    }
    html_template = _plain_text_to_html(req.body)

    try:
        _hash_set_mapping(
            stats_key,
            {
                "matched": len(recipients),
                "sent": 0,
                "failed": 0,
                "unique_opens": 0,
                "total_opens": 0,
            },
        )
    except Exception as e:
        logger.error("Failed to initialize blast stats: %s", e)

    sent = 0
    failures: list[dict[str, str]] = []
    for recipient in recipients:
        token = str(uuid.uuid4())
        sent_at = datetime.now(timezone.utc).isoformat()
        token_payload = {
            "blast_id": blast_id,
            "recipient": recipient,
            "subject": req.subject,
            "filters": filters_payload,
            "sent": sent_at,
        }
        try:
            redis_client.hset(
                EMAIL_OPEN_TOKENS_KEY, token, json.dumps(token_payload)
            )
        except Exception as e:
            logger.error("Failed to store blast tracking token: %s", e)

        recipient_state = {
            "email": recipient,
            "token": token,
            "sent_at": sent_at,
            "status": "pending",
            "opens": 0,
            "first_open": None,
            "last_open": None,
        }

        try:
            send_email(
                recipient,
                req.subject,
                req.body,
                html_body=html_template,
                track_token=token,
            )
            sent += 1
            recipient_state["status"] = "sent"
            try:
                _hash_incr(stats_key, "sent", 1)
            except Exception as e:
                logger.error("Failed to increment blast sent count: %s", e)
        except Exception as exc:
            failures.append({"email": recipient, "error": str(exc)})
            recipient_state["status"] = "failed"
            recipient_state["error"] = str(exc)
            try:
                _hash_incr(stats_key, "failed", 1)
            except Exception as e:
                logger.error("Failed to increment blast failure count: %s", e)
        finally:
            try:
                redis_client.hset(
                    recipients_key, recipient, json.dumps(recipient_state)
                )
            except Exception as e:
                logger.error("Failed to store blast recipient state: %s", e)

    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "email_blast",
        "actor": current_user.get("sub"),
        "blast_id": blast_id,
        "filters": filters_payload,
        "matched": len(recipients),
        "sent": sent,
        "failed": len(failures),
        "skipped_missing_email": skipped_missing_email,
        "skipped_filtered": skipped_filtered,
    }

    try:
        redis_client.rpush(ACTIVITY_LOG_KEY, json.dumps(log_entry))
    except Exception as e:
        logger.error("Failed to record email blast activity: %s", e)

    blast_record = {
        "blast_id": blast_id,
        "timestamp": blast_timestamp,
        "subject": req.subject,
        "body_preview": req.body[:200],
        "filters": filters_payload,
        "matched": len(recipients),
        "sent": sent,
        "failed": len(failures),
        "skipped_missing_email": skipped_missing_email,
        "skipped_filtered": skipped_filtered,
    }

    try:
        redis_client.hset(EMAIL_BLAST_META_KEY, blast_id, json.dumps(blast_record))
        redis_client.rpush(EMAIL_BLAST_INDEX_KEY, blast_id)
    except Exception as e:
        logger.error("Failed to persist blast metadata: %s", e)

    return {
        "blast_id": blast_id,
        "matched": len(recipients),
        "sent": sent,
        "failed": len(failures),
        "failures": failures,
        "skipped_missing_email": skipped_missing_email,
        "skipped_filtered": skipped_filtered,
    }


@app.get("/email-blasts")
def list_email_blasts(
    limit: int = 50, current_user: dict = Depends(get_current_user)
):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    if limit <= 0:
        limit = 1

    try:
        ids = _list_range(EMAIL_BLAST_INDEX_KEY, -limit, -1)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list blasts: {e}")

    blasts: list[dict[str, Any]] = []
    for raw_id in reversed(ids):
        blast_id = raw_id if isinstance(raw_id, str) else str(raw_id)
        try:
            meta_raw = redis_client.hget(EMAIL_BLAST_META_KEY, blast_id)
        except Exception as e:
            logger.error("Failed to fetch blast metadata: %s", e)
            continue
        if not meta_raw:
            continue
        try:
            meta = json.loads(meta_raw)
        except Exception:
            continue
        stats_raw = _hash_getall(_blast_stats_key(blast_id))
        stats = {key: _safe_int(value) for key, value in stats_raw.items()}
        meta.setdefault("blast_id", blast_id)
        meta["stats"] = stats
        blasts.append(meta)

    return {"blasts": blasts}


@app.get("/email-blasts/{blast_id}")
def get_email_blast(blast_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    try:
        meta_raw = redis_client.hget(EMAIL_BLAST_META_KEY, blast_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load blast: {e}")

    if not meta_raw:
        raise HTTPException(status_code=404, detail="Blast not found")

    try:
        blast = json.loads(meta_raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Invalid blast metadata: {e}")

    stats_raw = _hash_getall(_blast_stats_key(blast_id))
    stats = {key: _safe_int(value) for key, value in stats_raw.items()}

    try:
        recipients_raw = _hash_getall(_blast_recipients_key(blast_id))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load blast recipients: {e}")

    recipients: list[dict[str, Any]] = []
    for email, payload in recipients_raw.items():
        try:
            data = json.loads(payload) if payload else {"email": email}
        except Exception:
            data = {"email": email}
        data.setdefault("email", email)
        recipients.append(data)

    recipients.sort(key=lambda item: item.get("email", ""))
    blast.setdefault("blast_id", blast_id)

    return {"blast": blast, "stats": stats, "recipients": recipients}


@app.get("/students/by-school")
def students_by_school(
    limit: int = 50,
    cursor: Optional[str] = None,
    license: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Return student profiles for the current user's school.

    Career service users only see profiles they created themselves.
    """
    u_key = user_key(current_user.get('sub'))
    raw_user = redis_client.get(u_key)
    if not raw_user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        user = json.loads(raw_user)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupted user data")

    codes = _extract_institutional_codes(user)
    if not codes:
        raise HTTPException(status_code=400, detail="Institutional code required")
    normalized_codes = {code.lower() for code in codes}

    cur = int(cursor or 0)
    students: list[dict] = []
    while len(students) < limit:
        cur, keys = redis_client.scan(cur, match="student:*", count=limit)
        for key in keys:
            raw = redis_client.get(key)
            if not raw:
                continue
            try:
                student = json.loads(raw)
            except Exception:
                continue

            student_code = _student_institutional_code(student)
            if not student_code or student_code.lower() not in normalized_codes:
                continue

            if (
                current_user.get("role") == "career"
                and student.get("created_by") != current_user.get("sub")
            ):
                continue

            email = student.get("email")
            st_license = student.get("license") or student.get("education_level")
            if license and (st_license or "").lower() != license.lower():
                continue
            info = {
                "first_name": student.get("first_name"),
                "last_name": student.get("last_name"),
                "email": email,
                "phone": student.get("phone"),
                "city": student.get("city"),
                "state": student.get("state"),
                "license": st_license,
                "skills": student.get("skills"),
                "experience_summary": student.get("experience_summary"),
                "interests": student.get("interests"),
                "institutional_code": student.get("institutional_code")
                or student.get("school_code"),
            }
            students.append(info)
            if len(students) >= limit:
                break
        if cur == 0:
            break

    next_cursor = None if cur == 0 else str(cur)
    return {"students": students, "next_cursor": next_cursor}


@app.get("/students/{email}/job-stats")
def student_job_stats(email: str, current_user: dict = Depends(get_current_user)):
    """Return job status sets for a given student."""
    norm = normalize_email(email)
    key = resolve_student_key(norm)
    raw = redis_client.get(key) if key else None
    if not raw:
        raise HTTPException(status_code=404, detail="Student not found")

    if current_user.get("role") not in ADMIN_ROLES:
        try:
            student = json.loads(raw)
        except Exception:
            raise HTTPException(status_code=500, detail="Corrupted profile data")
        user_raw = redis_client.get(user_key(current_user.get("sub")))
        if not user_raw:
            raise HTTPException(status_code=404, detail="User not found")
        try:
            user = json.loads(user_raw)
        except Exception:
            raise HTTPException(status_code=500, detail="Corrupted user data")
        codes = _extract_institutional_codes(user)
        if not codes:
            raise HTTPException(status_code=400, detail="Institutional code required")
        st_code = _student_institutional_code(student)
        if not st_code or st_code.lower() not in {code.lower() for code in codes}:
            raise HTTPException(status_code=403, detail="Not authorized")
        if (
            current_user.get("role") == "career"
            and student.get("created_by") != current_user.get("sub")
        ):
            raise HTTPException(status_code=403, detail="Not authorized")

    return {
        "assigned": list(redis_client.smembers(_student_job_key(norm, "assigned"))),
        "placed": list(redis_client.smembers(_student_job_key(norm, "placed"))),
        "rejected": list(redis_client.smembers(_student_job_key(norm, "rejected"))),
        "uninterested": list(
            redis_client.smembers(_student_job_key(norm, "uninterested"))
        ),
    }


@app.get("/students/{email}/jobs")
def student_jobs(email: str, current_user: dict = Depends(get_current_user)):
    """Return the job list for a given student."""
    norm = normalize_email(email)
    key = resolve_student_key(norm)
    raw = redis_client.get(key) if key else None
    if not raw:
        raise HTTPException(status_code=404, detail="Student not found")

    if current_user.get("role") not in ADMIN_ROLES:
        try:
            student = json.loads(raw)
        except Exception:
            raise HTTPException(status_code=500, detail="Corrupted profile data")
        user_raw = redis_client.get(user_key(current_user.get("sub")))
        if not user_raw:
            raise HTTPException(status_code=404, detail="User not found")
        try:
            user = json.loads(user_raw)
        except Exception:
            raise HTTPException(status_code=500, detail="Corrupted user data")
        codes = _extract_institutional_codes(user)
        if not codes:
            raise HTTPException(status_code=400, detail="Institutional code required")
        st_code = _student_institutional_code(student)
        if not st_code or st_code.lower() not in {code.lower() for code in codes}:
            raise HTTPException(status_code=403, detail="Not authorized")
        if (
            current_user.get("role") == "career"
            and student.get("created_by") != current_user.get("sub")
        ):
            raise HTTPException(status_code=403, detail="Not authorized")

    return {"jobs": _fetch_student_jobs(norm)}

@app.get("/students/me")
def student_me(current_user: dict = Depends(get_current_user)):
    """Return the logged-in applicant's student profile."""
    email = current_user.get("sub")
    key = resolve_student_key(email)
    raw = redis_client.get(key) if key else None
    if not raw:
        raise HTTPException(status_code=404, detail="Profile not found")

    try:
        student = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupted profile data")

    claimed_by = student.get("claimed_by")
    current_sub = current_user.get("sub")
    if claimed_by and claimed_by != current_sub:
        raise HTTPException(status_code=403, detail="Profile not claimed by current user")

    # Summaries of job status are stored in Redis sets keyed by status
    assigned_job_code = None
    placed = 0
    if email:
        assigned = redis_client.smembers(f"student_jobs:{email}:assigned") or []
        assigned_job_code = next(iter(assigned), None)
        if isinstance(assigned_job_code, bytes):
            assigned_job_code = assigned_job_code.decode("utf-8")
        placed = len(redis_client.smembers(f"student_jobs:{email}:placed") or [])

    info = {
        "first_name": student.get("first_name"),
        "last_name": student.get("last_name"),
        "email": student.get("email"),
        "phone": student.get("phone"),
        "city": student.get("city"),
        "state": student.get("state"),
        "license": student.get("license") or student.get("education_level"),
        "skills": student.get("skills"),
        "experience_summary": student.get("experience_summary"),
        "interests": student.get("interests"),
        "institutional_code": student.get("institutional_code"),
        "placed_jobs": placed,
        "assigned_job_code": assigned_job_code,
    }
    return info


# Default RSS feeds shipped with the application. Only keep the
# sources the project actively uses. Additional feeds can still be
# added through the admin interface.
NURSING_FEEDS = {
    "American Nurse": "https://www.myamericannurse.com/feed/",
}

def init_default_rss_feeds() -> None:
    """Ensure Redis contains the default RSS feeds."""
    for name, url in NURSING_FEEDS.items():
        key = f"rss_feed:{name}"
        existing = redis_client.get(key)
        if existing != url:
            redis_client.set(key, url)


def all_rss_feeds() -> dict[str, str]:
    """Return mapping of all configured RSS feeds."""
    feeds = {}
    for key in redis_client.scan_iter("rss_feed:*"):
        url = redis_client.get(key)
        if url is not None:
            name = key.split("rss_feed:", 1)[1]
            feeds[name] = url
    for n, u in NURSING_FEEDS.items():
        feeds.setdefault(n, u)
    return feeds

NURSING_NEWS_CACHE_KEY = "cache:nursing_news"
NURSING_NEWS_TTL = 3600  # seconds
# Use a browser-like User-Agent when fetching RSS feeds to avoid blocking
RSS_HEADERS = {"User-Agent": "Mozilla/5.0"}


@app.get("/nursing-news")
async def nursing_news(force_refresh: bool = False):
    """Fetch and return articles from popular nursing RSS feeds."""
    import xml.etree.ElementTree as ET
    if not force_refresh:
        cached = redis_client.get(NURSING_NEWS_CACHE_KEY)
        if cached:
            try:
                return json.loads(cached)
            except Exception:
                pass

    feeds = all_rss_feeds()

    async with httpx.AsyncClient(timeout=10, headers=RSS_HEADERS) as client:
        tasks = [client.get(url) for url in feeds.values()]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for (name, _), resp in zip(feeds.items(), responses):
        if isinstance(resp, Exception):
            results.append({"source": name, "articles": [], "error": str(resp)})
            continue
        try:
            root = ET.fromstring(resp.text)
            articles = []
            for item in root.findall(".//item")[:5]:
                title = item.findtext("title") or ""
                link = item.findtext("link") or ""
                summary = item.findtext("description") or item.findtext("summary") or item.findtext("content:encoded") or ""
                summary = unescape(re.sub("<.*?>", "", summary))

                image = None
                media = item.find('{http://search.yahoo.com/mrss/}content')
                if media is not None and media.get('url'):
                    image = media.get('url')
                if not image:
                    encl = item.find('enclosure')
                    if encl is not None and encl.get('url') and encl.get('type', '').startswith('image'):
                        image = encl.get('url')
                if not image:
                    desc = item.findtext('description') or ''
                    m = re.search(r"<img[^>]+src=['\"]([^'\"]+)['\"]", desc)
                    if m:
                        image = m.group(1)

                articles.append({
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "image": image,
                })
            results.append({"source": name, "articles": articles})
        except Exception as e:
            results.append({"source": name, "articles": [], "error": str(e)})

    data = {"feeds": results}
    try:
        if hasattr(redis_client, "setex"):
            redis_client.setex(NURSING_NEWS_CACHE_KEY, NURSING_NEWS_TTL, json.dumps(data))
        else:
            redis_client.set(NURSING_NEWS_CACHE_KEY, json.dumps(data))
    except Exception:
        pass
    return data

@app.get("/dev/check-admin")
def check_admin():
    raw = redis_client.get("user:admin@example.com")
    if not raw:
        return {"exists": False}
    return json.loads(raw)


@app.post("/admin/test-notification")
def admin_test_notification(current_user: dict = Depends(get_current_user)):
    """Send a sample candidate notification to the admin's email."""
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    admin_email = current_user.get("sub")
    job_title = random.choice(
        [
            "Registered Nurse",
            "Clinical Manager",
            "Nursing Assistant",
            "Care Coordinator",
            "Health Specialist",
        ]
    )
    send_email(
        admin_email,
        f"Job Match: {job_title}",
        (
            f"Hello,\n\nA recruiter has expressed interest in you for the job '{job_title}'. "
            "They may contact you soon."
        ),
    )
    return {"message": "Test email sent"}


@app.post("/admin/test-weekly-summary")
def admin_test_weekly_summary(current_user: dict = Depends(get_current_user)):
    """Manually trigger a weekly summary email to the admin's address."""
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    send_weekly_summary(current_user["sub"])
    return {"message": "Weekly summary sent"}


@app.post("/admin/send-welcome-emails")
def admin_send_welcome_emails(
    payload: WelcomeEmailRequest = Body(default=None),
    current_user: dict = Depends(get_current_user),
):
    """Send the welcome email to existing student profiles."""

    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    if payload is None:
        payload = WelcomeEmailRequest()

    limit = payload.limit
    resend = payload.resend

    processed = 0
    sent = 0
    skipped = 0
    failed = 0

    for key in redis_client.scan_iter("student:*:*"):
        if limit is not None and processed >= limit:
            break
        status = send_welcome_email_for_key(key, force=resend)
        processed += 1
        if status == "sent":
            sent += 1
        elif status == "failed":
            failed += 1
        else:
            skipped += 1

    return {
        "processed": processed,
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
    }


@app.get("/activity-log")
def activity_log(limit: int = 100, current_user: dict = Depends(get_current_user)):
    """Return recent activity log entries."""
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    try:
        raw_entries = redis_client.lrange(ACTIVITY_LOG_KEY, -limit, -1) or []
        entries = [json.loads(e) for e in raw_entries if e]
        pst = ZoneInfo("America/Los_Angeles")
        for entry in entries:
            ts = entry.get("timestamp")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                entry["timestamp_pst"] = dt.astimezone(pst).isoformat()
            except Exception:
                continue
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read activity log: {e}")

    return {"entries": entries}
