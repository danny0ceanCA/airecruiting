"""Application entry point.

This module initialises the :class:`FastAPI` application, configures
middleware, and exposes several utility objects (JWT settings, the Redis
client, and ``init_default_admin``) used throughout the tests.  Authentication
routes are defined in :mod:`app.routes.auth` and included here.
"""

from __future__ import annotations

import json
import os
from typing import Any
import bcrypt
import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import httpx
import xml.etree.ElementTree as ET

try:  # pragma: no cover - optional dependency during tests
    import redis
except Exception:  # pragma: no cover - redis not installed
    redis = None

from backend.app.school_codes import SCHOOL_CODE_MAP
from backend.app.services.job import resolve_student_key as _resolve_student_key
from backend.app.logging_utils import RequestIdFilter, RequestLoggingMiddleware


load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(request_id)s] %(message)s")
for handler in logging.getLogger().handlers:
    handler.addFilter(RequestIdFilter())

# ---------------------------------------------------------------------------
# Global settings used by the auth routes and tests
# ---------------------------------------------------------------------------

JWT_SECRET = "secret"
ALGORITHM = "HS256"
redis_client = None  # replaced by tests with a dummy implementation

# Attempt to initialise a real Redis client when running the application
# outside of the test suite.  If ``REDIS_URL`` is not defined or the
# ``redis`` package/connection is unavailable, ``redis_client`` simply remains
# ``None`` and the routes will raise an HTTP 503 error when accessed.
redis_url = os.getenv("REDIS_URL")
if redis_url and redis is not None:
    try:  # pragma: no cover - network/connection errors are environment specific
        redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
    except Exception:  # pragma: no cover
        redis_client = None

# Placeholder OpenAI client used by tests.  The ``embeddings.create`` method is
# monkeypatched in the unit tests to avoid external API calls.
client = type(
    "Client",
    (),
    {
        "embeddings": type("Emb", (), {"create": lambda *a, **k: None})(),
        "chat": type("Chat", (), {"completions": type("Comp", (), {"create": lambda *a, **k: None})()})(),
    },
)()


def send_email(recipient: str, subject: str, body: str) -> None:
    """Placeholder email sender used by tests."""


def get_driving_distance_miles(*_args, **_kwargs) -> float:
    """Return a dummy driving distance in miles.

    The tests monkeypatch this function with predictable values to avoid any
    external API calls.  The default implementation simply returns ``0.0`` so
    that calling code has a sensible fallback when the function has not been
    patched.
    """

    return 0.0


def resolve_student_key(email: str) -> str | None:
    """Wrapper exposing :func:`backend.app.services.job.resolve_student_key`.

    The tests import ``resolve_student_key`` from :mod:`app.main` directly, so
    we provide this thin wrapper that supplies the configured ``redis_client``.
    """

    return _resolve_student_key(redis_client, email)


def student_email_key(email: str) -> str:
    """Return the redis key used to index students by email."""

    return f"student_email:{email.strip().lower()}"


def student_key(institution_code: str, student_id: str) -> str:
    """Return the canonical redis key for a student."""

    return f"student:{institution_code}:{student_id}"


def persist_student_record(
    email: str, data: dict[str, Any], institutional_code: str, student_id: str
) -> None:
    """Persist a student record and index it by email."""

    if redis_client is None:
        return

    record = dict(data)
    record.update(
        {"email": email, "institutional_code": institutional_code, "student_id": student_id}
    )
    redis_client.set(f"student:{institutional_code}:{student_id}", json.dumps(record))
    redis_client.set(student_email_key(email), f"{institutional_code}:{student_id}")


def init_default_admin() -> None:
    """Ensure a default administrator account exists in Redis."""

    if redis_client is None:
        return

    email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    password = os.getenv("ADMIN_PASSWORD", "admin123")

    key = f"user:{email}"
    if not redis_client.exists(key):
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        admin = {
            "email": email,
            "first_name": "Admin",
            "last_name": "User",
            "password": hashed,
            "role": "admin",
            "approved": True,
            "rejected": False,
        }
        redis_client.set(key, json.dumps(admin))


def init_default_school_codes() -> None:
    """Load the default school codes into Redis if missing."""

    if redis_client is None:
        return

    for code, label in SCHOOL_CODE_MAP.items():
        redis_client.set(f"school_code:{code}", label)


NURSING_FEEDS = [("Example", "http://example.com/feed")]


# ---------------------------------------------------------------------------
# FastAPI application setup
# ---------------------------------------------------------------------------

app = FastAPI()

app.add_middleware(RequestLoggingMiddleware)


@app.on_event("startup")
def startup() -> None:
    """Populate Redis with baseline data when the API starts.

    The tests monkeypatch ``redis_client`` with an in-memory stand in, so we
    guard against ``None`` to keep import side effects minimal.  When the
    application runs normally with a real Redis backend we pre-create the
    default administrator account and load the initial set of school codes so
    that a fresh deployment can be used immediately.
    """

    if redis_client is None:  # pragma: no cover - depends on deployment
        return

    init_default_admin()
    init_default_school_codes()


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "Hello, World"}


# Read allowed CORS origins from the environment.
# Defaults to ["*"] to permit any origin when not set.
allowed_origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from app.routes import auth, admin, students, jobs, matching, notes, licenses


app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(students.router)
app.include_router(jobs.router)
app.include_router(matching.router)
app.include_router(notes.router)
app.include_router(licenses.router)


@app.get("/school-codes")
def list_school_codes() -> dict:
    codes = []
    if redis_client is not None:
        # Ensure defaults are loaded if the store is empty
        if not any(redis_client.scan_iter("school_code:*")):
            init_default_school_codes()
        for key in redis_client.scan_iter("school_code:*"):
            code = key.split(":", 1)[1]
            label = redis_client.get(key)
            codes.append({"code": code, "label": label})
    return {"codes": codes}


@app.get("/rss-feeds")
def list_rss_feeds() -> dict:
    feeds = []
    if redis_client is not None:
        for key in redis_client.scan_iter("rss:*"):
            name = key.split(":", 1)[1]
            url = redis_client.get(key)
            feeds.append({"name": name, "url": url})
    return {"feeds": feeds}


@app.get("/nursing-news")
async def nursing_news() -> dict:
    if redis_client is not None:
        cached = redis_client.get("nursing_news")
        if cached:
            return json.loads(cached)

    feeds_out = []
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for name, url in NURSING_FEEDS:
            resp = await client.get(url)
            root = ET.fromstring(resp.text)
            articles = []
            for item in root.findall(".//item"):
                title = item.findtext("title")
                link = item.findtext("link")
                desc = item.findtext("description")
                enclosure = item.find("enclosure")
                image = enclosure.get("url") if enclosure is not None else None
                articles.append(
                    {
                        "title": title,
                        "link": link,
                        "description": desc,
                        "summary": desc,
                        "image": image,
                    }
                )
            feeds_out.append({"name": name, "url": url, "articles": articles})

    data = {"feeds": feeds_out}
    if redis_client is not None:
        redis_client.set("nursing_news", json.dumps(data))
    return data

