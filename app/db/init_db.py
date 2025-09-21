import json
import os
import re

import bcrypt

from backend.app.school_codes import SCHOOL_CODE_MAP

from app.core.config import DEFAULT_LICENSES, NURSING_FEEDS
from app.core.logging import get_logger
from app.db.redis_client import redis_client

logger = get_logger(__name__)

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

def init_default_school_codes():
    """Ensure Redis contains the default school codes with current labels."""
    for code, label in SCHOOL_CODE_MAP.items():
        key = f"school_code:{code}"
        existing = redis_client.get(key)
        if existing != label:
            redis_client.set(key, label)

def init_default_licenses() -> None:
    """Seed Redis with default license codes."""
    for code, label in DEFAULT_LICENSES.items():
        key = f"license:{code}"
        existing = redis_client.get(key)
        if existing != label:
            redis_client.set(key, label)

def init_default_rss_feeds() -> None:
    """Ensure Redis contains the default RSS feeds."""
    for name, url in NURSING_FEEDS.items():
        key = f"rss_feed:{name}"
        existing = redis_client.get(key)
        if existing != url:
            redis_client.set(key, url)

