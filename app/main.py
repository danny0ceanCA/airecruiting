from dotenv import load_dotenv

load_dotenv()

from datetime import datetime, timezone
import json
import uuid
import httpx

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from jose import JWTError, jwt

from app.api.routes import (
    admin_users,
    auth,
    jobs,
    metrics,
    notifications,
    resumes,
    root,
    rss,
    school_licenses,
    students,
)
from app.core.config import (
    ACTIVITY_LOG_KEY,
    ADMIN_ROLES,
    ALGORITHM,
    EMAIL_OPEN_TOKENS_KEY,
    EMAIL_SENDER,
    JWT_SECRET,
    NURSING_FEEDS,
    NURSING_NEWS_CACHE_KEY,
    NURSING_NEWS_TTL,
    REFRESH_TOKEN_LOOKUP_PREFIX,
    REFRESH_TOKEN_USER_PREFIX,
    RSS_HEADERS,
    SITE_BASE_URL,
    SMTP_HOST,
    client,
)
from app.core.logging import get_logger, request_id_ctx_var
from app.core.security import (
    _hash_refresh_token,
    generate_access_token,
    get_current_user,
    issue_refresh_token,
    revoke_refresh_token,
)
from app.db.init_db import (
    init_default_admin,
    init_default_licenses,
    init_default_rss_feeds,
    init_default_school_codes,
)
from app.db.redis_client import get_queue, redis_client
from app.services.core_utils import (
    all_licenses,
    all_school_codes,
    find_user_key,
    generate_student_id,
    get_school_label,
    license_to_code,
    normalize_email,
    persist_student_record,
    resolve_student_key,
    student_email_key,
    student_key,
    user_key,
)
from app.services.description import extract_benefits, generate_job_description_html
from app.services.distance import get_driving_distance_miles
from app.services.email import send_email
from app.services.embeddings import ensure_index, rebuild_vector_index, vector_emails, vector_index
from app.services.jobs import (
    _add_student_job,
    _fetch_student_jobs,
    _normalize_notes,
    _remove_student_job,
    _tracking_stats,
)
from app.services.matching import match_worker
from backend.app.services.summary import send_weekly_summary

logger = get_logger(__name__)

app = FastAPI()


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
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token_val = auth_header.split(" ", 1)[1]
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


@app.options("/{rest_of_path:path}")
async def preflight_handler(rest_of_path: str):
    return {}


@app.on_event("startup")
def on_startup():
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


app.include_router(root.router)
app.include_router(notifications.router)
app.include_router(auth.router)
app.include_router(admin_users.router)
app.include_router(school_licenses.router)
app.include_router(students.router)
app.include_router(jobs.router)
app.include_router(resumes.router)
app.include_router(metrics.router)
app.include_router(rss.router)

TRANSPARENT_PNG = notifications.TRANSPARENT_PNG


import sys
import types

_PROPAGATED_ATTRS = {
    "redis_client",
    "client",
    "vector_index",
    "vector_emails",
    "EMBEDDING_DIM",
    "ensure_index",
    "rebuild_vector_index",
    "send_email",
    "send_weekly_summary",
    "get_driving_distance_miles",
    "match_worker",
    "get_queue",
    "SMTP_HOST",
    "EMAIL_SENDER",
}

_TARGET_MODULES = [
    "app.core.config",
    "app.core.security",
    "app.db.init_db",
    "app.db.redis_client",
    "app.services.embeddings",
    "app.services.email",
    "app.services.core_utils",
    "app.services.jobs",
    "app.services.matching",
    "app.services.description",
    "app.services.distance",
    "app.services.rss",
    "app.api.routes.auth",
    "app.api.routes.admin_users",
    "app.api.routes.school_licenses",
    "app.api.routes.students",
    "app.api.routes.jobs",
    "app.api.routes.resumes",
    "app.api.routes.metrics",
    "app.api.routes.notifications",
    "app.api.routes.rss",
    "app.api.routes.root",
    "backend.app.services.summary",
]


class _MainModule(types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name in _PROPAGATED_ATTRS:
            for module_name in _TARGET_MODULES:
                module = sys.modules.get(module_name)
                if module and hasattr(module, name):
                    setattr(module, name, value)


sys.modules[__name__].__class__ = _MainModule
