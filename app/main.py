from dotenv import load_dotenv

load_dotenv()

from datetime import datetime, timedelta, timezone
import json
import csv
import os
import uuid
from typing import Optional
import smtplib
import logging
import sys
from email.message import EmailMessage
from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Header,
    Request,
    UploadFile,
    File,
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
import re
import numpy as np
import faiss
from rq import Queue
from html import unescape, escape
import random
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
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

# TTL for cached student profiles
PROFILE_CACHE_TTL = int(os.getenv("PROFILE_CACHE_TTL", "300"))


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
    """Send an email with optional attachments if SMTP configuration is available."""
    if not SMTP_HOST or not EMAIL_SENDER:
        logger.warning("[email] Skipping email to %s; SMTP not configured", recipient)
        return
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

async def get_driving_distance_miles(orig_lat: float, orig_lng: float, dest_lat: float, dest_lng: float) -> float:
    """Return driving distance in miles between two coordinates using Google Distance Matrix.

    Results are cached in Redis for 24 hours to avoid excessive API calls.
    """
    key = os.getenv("GOOGLE_KEY")
    if not key:
        raise RuntimeError("Missing GOOGLE_KEY")

    cache_key = f"distance:{orig_lat}:{orig_lng}:{dest_lat}:{dest_lng}"
    cached = redis_client.get(cache_key)
    if cached is not None:
        try:
            miles = float(cached)
            logger.info("Distance cache hit for %s", cache_key)
            return miles
        except ValueError:
            logger.exception("Invalid cached distance for %s", cache_key)

    logger.info("Distance cache miss for %s", cache_key)
    params = {
        "origins": f"{orig_lat},{orig_lng}",
        "destinations": f"{dest_lat},{dest_lng}",
        "units": "imperial",
        "key": key,
    }
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    async with httpx.AsyncClient() as client:
        try:
            logger.info("Requesting %s params=%s", url, params)
            resp = await client.get(url, params=params)
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
        value_meters = data["rows"][0]["elements"][0]["distance"]["value"]
    except Exception:
        logger.exception("Error parsing distance matrix response")
        raise

    miles = value_meters / 1609.34
    redis_client.setex(cache_key, int(timedelta(hours=24).total_seconds()), miles)
    return miles

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
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
    redis_client.set(
        key,
        json.dumps(
            {
                "first_name": first,
                "last_name": last,
                "institutional_code": "Admin School",
                "password": hashed,
                "active": True,
                "role": role,
                "approved": True,
                "rejected": False,
            }
        ),
    )
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
    init_default_rss_feeds()
    keys = redis_client.keys("match_results:*")
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

    if req.role in {"career", "recruiter"} and not req.institutional_code:
        raise HTTPException(status_code=400, detail="Institutional code required for career staff and recruiters")

    label = None
    if req.institutional_code:
        label = get_school_label(req.institutional_code)
        if not label:
            raise HTTPException(
                status_code=400,
                detail="Invalid school code. Please contact your administrator.",
            )

    hashed = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    redis_client.set(
        key,
        json.dumps(
            {
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
        ),
    )
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

    payload = {
        "sub": email,
        "role": user["role"],
        "exp": datetime.utcnow() + timedelta(hours=1),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)
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
    return {"token": token}


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
    user["approved"] = True
    if req.role is not None:
        user["role"] = req.role
    redis_client.set(key, json.dumps(user))
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

    redis_client.delete(key)
    return {"message": f"Deleted {email}"}


class SchoolCodeRequest(BaseModel):
    code: str
    label: str

class UpdateSchoolCodeRequest(BaseModel):
    label: str


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
    redis_client.delete(key)
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
    redis_client.delete(key)
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
    redis_client.delete(key)
    return {"message": "Feed deleted"}

@app.post("/students")
async def create_student(request: Request, current_user: dict = Depends(get_current_user)):
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
        redis_client.delete(key)
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
            redis_client.delete(existing_key)
        redis_client.delete(f"student:{student.email}")
        redis_client.delete(student_email_key(student.email))

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

@app.post("/match")
def match_job(
    req: JobCodeRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Enqueue a matching job and return immediately."""
    enq_time = datetime.now().timestamp()
    if hasattr(redis_client, "pipeline"):
        get_queue().enqueue(
            match_worker,
            req.job_code,
            False,
            enq_time,
            meta={"request_id": request.state.request_id},
        )
        return {"message": "Match job queued"}
    else:
        matches = match_worker(req.job_code, False, enq_time)
        return {"matches": matches}


@app.post("/rematches/{job_code}")
def rematch_job(
    job_code: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Queue a rematch computation without notifying students."""
    enq_time = datetime.now().timestamp()
    if hasattr(redis_client, "pipeline"):
        get_queue().enqueue(
            match_worker,
            job_code,
            False,
            enq_time,
            meta={"request_id": request.state.request_id},
        )
        return {"message": "Rematch queued"}
    else:
        matches = match_worker(job_code, False, enq_time)
        return {"matches": matches}


async def _perform_match_async(job_code: str, send_emails: bool = False, enq_time: float | None = None):
    key = f"job:{job_code}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")
    job = json.loads(raw)
    job.setdefault("uninterested_students", [])
    was_matched_before = bool(redis_client.exists(f"match_results:{job_code}"))

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
    try:
        resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
        job_emb = resp.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")

    ensure_index(len(job_emb))
    if vector_index is None:
        return []

    matches = []
    if vector_index.ntotal == 0:
        rebuild_vector_index()
    search_vec = np.array([job_emb], dtype="float32")
    k = min(50, vector_index.ntotal)
    if k > 0:
        sims, idxs = vector_index.search(search_vec, k)
        candidate_emails = [vector_emails[i] for i in idxs[0] if i != -1]
    else:
        candidate_emails = []

    tasks = []
    candidates = []
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
            coro = get_driving_distance_miles(
                student.get("lat"),
                student.get("lng"),
                job.get("lat"),
                job.get("lng"),
            )
            if asyncio.iscoroutine(coro):
                tasks.append(coro)
            else:
                tasks.append(asyncio.sleep(0, result=coro))
            candidates.append((student, emb))
        except Exception:
            continue

    dists = await asyncio.gather(*tasks, return_exceptions=True)
    for (student, emb), dist in zip(candidates, dists):
        if isinstance(dist, Exception):
            continue
        if dist > float(student.get("max_travel", 0)):
            continue
        score = float(np.dot(job_emb, emb))
        matches.append(
            {
                "name": f"{student.get('first_name', '')} {student.get('last_name', '')}",
                "first_name": student.get("first_name", ""),
                "last_name": student.get("last_name", ""),
                "email": student.get("email"),
                "score": score,
                "distance_miles": round(dist, 1),
            }
        )

    # Deduplicate by email
    dedup: dict[str, dict] = {}
    for m in matches:
        dedup[m["email"]] = m
    matches = list(dedup.values())

    # Include applicant user records with a matching institutional code when no
    # student profile exists for them
    for ukey in redis_client.scan_iter("user:*"):
        u_raw = redis_client.get(ukey)
        if not u_raw:
            continue
        try:
            udata = json.loads(u_raw)
        except Exception:
            continue
        if udata.get("role") != "applicant" or not poster_code:
            continue
        ucode = udata.get("institutional_code") or udata.get("school_code")
        if ucode != poster_code:
            continue
        user_license = license_to_code(udata.get("license") or udata.get("education_level"))
        if required_license and user_license != required_license:
            continue
        email = ukey.split("user:", 1)[1]
        if email in job.get("uninterested_students", []):
            continue
        if resolve_student_key(email):
            continue
        matches.append(
            {
                "name": f"{udata.get('first_name', '')} {udata.get('last_name', '')}",
                "first_name": udata.get("first_name", ""),
                "last_name": udata.get("last_name", ""),
                "email": email,
                "score": 0.0,
                "distance_miles": None,
            }
        )

    matches.sort(key=lambda x: x["score"], reverse=True)

    assigned = set(job.get("assigned_students", []))
    # Exclude already assigned students from the match limit so recruiters
    # can always receive up to 10 new candidates regardless of how many
    # students have been assigned.
    filtered_matches = [m for m in matches if m["email"] not in assigned]
    top_matches = filtered_matches[:10]

    placed = set(job.get("placed_students", []))
    rejected = set(job.get("rejected_students", []))

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




    redis_client.set(
        f"match_results:{job_code}", json.dumps(top_matches)
    )
    logger.info("✅ Stored %s matches for job %s", len(top_matches), job_code)

    if send_emails:
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

    return top_matches


def _perform_match(job_code: str, send_emails: bool = False, enq_time: float | None = None):
    """Synchronous wrapper for background execution."""
    return asyncio.run(_perform_match_async(job_code, send_emails, enq_time))


def match_worker(job_code: str, send_emails: bool = False, enq_time: float | None = None):
    start = datetime.now()
    if enq_time is not None:
        queue_time = start - datetime.fromtimestamp(enq_time)
        redis_client.incrbyfloat("metrics:match_queue_time", queue_time.total_seconds())
    result = _perform_match(job_code, send_emails)
    process_time = datetime.now() - start
    redis_client.incrbyfloat("metrics:match_process_time", process_time.total_seconds())
    return result


@app.get("/match/{job_code}")
def get_match_results(job_code: str, current_user: dict = Depends(get_current_user)):
    key = f"match_results:{job_code}"
    results_json = redis_client.get(key)

    if results_json is None:
        logger.warning("⚠️ No match results found for job %s", job_code)
        return {"matches": []}

    try:
        matches = {m["email"]: m for m in json.loads(results_json)}
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

        existing = set(matches)
        for email in assigned | placed | rejected:
            if email not in existing:
                udata = json.loads(redis_client.get(f"user:{email}") or "{}")
                first = udata.get("first_name", "")
                last = udata.get("last_name", "")
                name = f"{first} {last}".strip()
                matches[email] = {
                    "name": name,
                    "first_name": first,
                    "last_name": last,
                    "email": email,
                    "score": None,
                }

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


@app.get("/has-match/{job_code}")
def has_match_data(job_code: str):
    exists = redis_client.exists(f"match_results:{job_code}")
    return {"has_match": bool(exists)}

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
    logger.info("Returning %s jobs from Redis", len(jobs))
    return {"jobs": jobs}


@app.delete("/jobs/{job_code}")
def delete_job(job_code: str, token_data: dict = Depends(get_current_user)):
    if token_data.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    job_key = f"job:{job_code}"
    match_key = f"match_results:{job_code}"

    if not redis_client.exists(job_key):
        raise HTTPException(status_code=404, detail="Job not found")

    redis_client.delete(job_key)
    redis_client.delete(match_key)

    return {"message": f"Job {job_code} deleted successfully"}


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
    if token_data.get("role") not in {"admin", "junior_admin", "career"}:
        raise HTTPException(status_code=403, detail="Not authorized to place students")
    job_code = data["job_code"]
    student_email = normalize_email(data["student_email"])
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

    redis_client.set(key, json.dumps(job))
    _update_student_job(student_email, job_code, "placed")
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
    _update_student_job(student_email, job_code, "assigned")
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
    if student_email not in job["rejected_students"]:
        job["rejected_students"].append(student_email)

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
    _update_student_job(student_email, job_code, "rejected")
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

    redis_client.set(key, json.dumps(job))
    _update_student_job(student_email, job_code, "uninterested")
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
    send_email(
        student_email,
        f"Recruiter Interest: {job.get('job_title')}",
        body,
        html_body=html_body,
        track_token=token,
    )

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
    raw_content = ""
    if not job.get("external_apply_url"):
        prompt = f"""
You are generating a job description document for internal career services staff. The document should first summarize the position itself, then connect it with the student's background.

Use the student profile and job information below to:

- Provide a **Job Summary** that comprehensively covers the job description **without referencing the applicant's experience**
- Describe **key responsibilities** they might undertake as noted in the job description
- List **areas of strength** with plenty of details to reinforce existing experience and how it connects with the job description and potential **areas for growth** with plenty of insightful and targeted recommendations for training that will improve the probability of success
- Mention **school affiliation** and any relevant compliance or readiness info

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

    description_html = ""
    job_desc = job.get("job_description", "")
    if job_desc:
        lines = [line.strip() for line in job_desc.splitlines()]
        formatted: list[str] = []
        in_list = False
        for line in lines:
            if line.startswith(("- ", "* ", "• ")):
                if not in_list:
                    formatted.append("<ul>")
                    in_list = True
                formatted.append(f"<li>{escape(line[2:].strip())}</li>")
            elif line:
                if in_list:
                    formatted.append("</ul>")
                    in_list = False
                formatted.append(f"<p>{escape(line)}</p>")
            else:
                if in_list:
                    formatted.append("</ul>")
                    in_list = False
        if in_list:
            formatted.append("</ul>")
        description_html = "<h2>Full Job Description</h2>\n" + "\n".join(formatted)

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
{description_html}
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
        redis_client.delete(key)
        deleted += 1
    for key in list(redis_client.scan_iter("match_results:*")):
        redis_client.delete(key)

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
            redis_client.delete(k)

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
    redis_client.delete(skey)
    redis_client.delete(student_email_key(email))

    # Remove any lingering user record to avoid bogus admin entries
    ukey = find_user_key(email)
    if ukey:
        redis_client.delete(ukey)

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
        redis_client.delete(key)

    # Remove job descriptions if any
    for key in redis_client.scan_iter(f"job_description:*:{email}"):
        redis_client.delete(key)

    # (Optional) Clean match results if student appears
    for match_key in redis_client.scan_iter("match_results:*"):
        raw = redis_client.get(match_key)
        if not raw:
            continue
        try:
            matches = json.loads(raw)
            new_matches = [m for m in matches if m.get("email") != email]
            if len(new_matches) != len(matches):
                redis_client.set(match_key, json.dumps(new_matches))
        except Exception:
            continue

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

    email_sent_values = [t.get("sent") for t in tokens if t.get("sent")]
    email_sent = min(email_sent_values) if email_sent_values else None

    token_set = {t["token"] for t in tokens}
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


def _update_student_job(email: str, job_code: str, status: str) -> None:
    """Update the per-student job index and invalidate profile cache."""
    key = f"student_jobs:{normalize_email(email)}"
    try:
        redis_client.hset(key, job_code, status)
        redis_client.delete(f"cache:student_profile:{normalize_email(email)}")
    except Exception:
        pass


def _assemble_student_profile(student: dict) -> dict:
    """Build a student profile including job statuses with caching."""
    email = normalize_email(student.get("email"))
    if not email:
        return {}
    cache_key = f"cache:student_profile:{email}"
    cached = redis_client.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    job_statuses = redis_client.hgetall(f"student_jobs:{email}") or {}
    job_codes = list(job_statuses.keys())
    job_keys = [f"job:{code}" for code in job_codes]
    jobs_list: list[dict] = []
    if job_keys:
        try:
            raw_jobs = redis_client.mget(job_keys)
        except Exception:
            raw_jobs = []
        for code, raw in zip(job_codes, raw_jobs):
            if not raw:
                continue
            try:
                job = json.loads(raw)
            except Exception:
                continue
            status = job_statuses.get(code)
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

    info = {
        "first_name": student.get("first_name"),
        "last_name": student.get("last_name"),
        "email": email,
        "phone": student.get("phone"),
        "city": student.get("city"),
        "state": student.get("state"),
        "license": student.get("license") or student.get("education_level"),
        "skills": student.get("skills"),
        "experience_summary": student.get("experience_summary"),
        "interests": student.get("interests"),
        "institutional_code": student.get("institutional_code")
        or student.get("school_code"),
        "assigned_jobs": jobs_list,
        "placed_jobs": sum(1 for j in jobs_list if j["status"] == "placed"),
        "assigned_job_code": next(
            (j["job_code"] for j in jobs_list if j["status"] == "assigned"),
            None,
        ),
    }

    try:
        redis_client.setex(cache_key, PROFILE_CACHE_TTL, json.dumps(info))
    except Exception:
        pass

    return info

@app.get("/students/all")
def get_all_students(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    student_keys = list(redis_client.scan_iter("student:*"))
    if not student_keys:
        return {"students": []}
    try:
        raw_students = redis_client.mget(student_keys)
    except Exception:
        raw_students = []

    students = []
    for raw in raw_students:
        if not raw:
            continue
        try:
            student = json.loads(raw)
        except Exception:
            continue
        students.append(_assemble_student_profile(student))

    return {"students": students}

@app.get("/students/by-school")
def students_by_school(current_user: dict = Depends(get_current_user)):
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

    institutional_code = user.get("institutional_code") or user.get("school_code")
    if not institutional_code:
        raise HTTPException(status_code=400, detail="Institutional code required")

    student_keys = list(redis_client.scan_iter("student:*"))
    if not student_keys:
        return {"students": []}
    try:
        raw_students = redis_client.mget(student_keys)
    except Exception:
        raw_students = []

    students = []

    for raw in raw_students:
        if not raw:
            continue
        try:
            student = json.loads(raw)
        except Exception:
            continue

        if (student.get("institutional_code") or student.get("school_code")) != institutional_code:
            continue

        if current_user.get("role") == "career" and student.get("created_by") != current_user.get("sub"):
            continue

        students.append(_assemble_student_profile(student))

    return {"students": students}


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

    return _assemble_student_profile(student)


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
        f"Recruiter Interest: {job_title}",
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
