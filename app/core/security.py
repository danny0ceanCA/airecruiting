import hashlib
import secrets
import uuid
from datetime import datetime

from fastapi import Header, HTTPException
from jose import JWTError, jwt

from app.core.config import (
    ACCESS_TOKEN_TTL,
    ALGORITHM,
    JWT_SECRET,
    REFRESH_TOKEN_LOOKUP_PREFIX,
    REFRESH_TOKEN_TTL_SECONDS,
    REFRESH_TOKEN_USER_PREFIX,
)
from app.db.redis_client import redis_client
from app.services.core_utils import normalize_email

def _hash_refresh_token(token: str) -> str:
    """Return a deterministic hash for a refresh token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def _set_with_ttl(key: str, ttl: int, value: str) -> None:
    """Set a redis key with an optional TTL, falling back to set."""
    if hasattr(redis_client, "setex"):
        redis_client.setex(key, ttl, value)
    else:
        redis_client.set(key, value)

def issue_refresh_token(email: str) -> str:
    """Generate and persist a refresh token for a user, rotating old values."""
    normalized = normalize_email(email)
    raw_token = secrets.token_urlsafe(48)
    hashed = _hash_refresh_token(raw_token)
    current = redis_client.get(f"{REFRESH_TOKEN_USER_PREFIX}:{normalized}")
    if current:
        redis_client.delete(f"{REFRESH_TOKEN_LOOKUP_PREFIX}:{current}")
    _set_with_ttl(f"{REFRESH_TOKEN_USER_PREFIX}:{normalized}", REFRESH_TOKEN_TTL_SECONDS, hashed)
    _set_with_ttl(f"{REFRESH_TOKEN_LOOKUP_PREFIX}:{hashed}", REFRESH_TOKEN_TTL_SECONDS, normalized)
    return raw_token

def revoke_refresh_token(email: str, hashed: str | None = None) -> None:
    """Remove refresh token mappings for a user."""
    normalized = normalize_email(email)
    stored_hash = hashed or redis_client.get(f"{REFRESH_TOKEN_USER_PREFIX}:{normalized}")
    if stored_hash:
        redis_client.delete(f"{REFRESH_TOKEN_LOOKUP_PREFIX}:{stored_hash}")
    redis_client.delete(f"{REFRESH_TOKEN_USER_PREFIX}:{normalized}")

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

def get_current_user(authorization: str = Header(..., alias="Authorization")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload

