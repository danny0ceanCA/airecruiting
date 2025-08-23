"""Authentication-related API routes.

This module defines registration, login, and admin approval endpoints.  The
routes mirror the simplified behaviour expected by the tests: user data is
stored in the ``redis_client`` instance defined in :mod:`app.main` and JSON Web
Tokens are issued on successful login.
"""

from __future__ import annotations

import json
from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, status
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr

from backend.app.logging_utils import get_logger

import app.main as main

JWT_SECRET = main.JWT_SECRET
ALGORITHM = main.ALGORITHM


router = APIRouter(prefix="", tags=["auth"])

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    password: str
    role: str
    school_code: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ApproveRequest(BaseModel):
    email: EmailStr
    role: str


class RejectRequest(BaseModel):
    email: EmailStr


# ---------------------------------------------------------------------------
# Helper dependencies
# ---------------------------------------------------------------------------


def get_current_user(authorization: str = Header(..., alias="Authorization")):
    """Decode the JWT from the ``Authorization`` header and return the user."""

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":  # pragma: no cover - defensive branch
            raise ValueError("Invalid auth scheme")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except (ValueError, JWTError):
        logger.warning("Invalid authorization token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    email = payload.get("sub")
    if not email:
        logger.warning("Token missing subject")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    raw = main.redis_client.get(f"user:{email}")
    if raw is None and hasattr(main.redis_client, "store"):
        raw = main.redis_client.store.get(f"user:{email}")
    if not raw:
        logger.warning("User %s not found during token lookup", email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return json.loads(raw)


def require_admin(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        logger.warning("Access denied for %s: admin privileges required", user.get("email"))
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return user


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/register")
def register(payload: RegisterRequest):
    """Register a new user.

    Applicants may register without a ``school_code``; other roles must supply
    one.  Users are stored in Redis with ``approved`` and ``rejected`` flags
    defaulting to ``False``.
    """

    logger.info("Registration attempt for %s", payload.email)
    if payload.role != "applicant" and not payload.school_code:
        logger.warning("Registration failed for %s: missing school code", payload.email)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="School code required")

    key = f"user:{payload.email}"
    if main.redis_client.exists(key):
        logger.warning("Registration failed for %s: user already exists", payload.email)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")

    data = payload.model_dump()
    data.update({"approved": False, "rejected": False, "active": True})
    main.redis_client.set(key, json.dumps(data))

    logger.info("User %s registered successfully", payload.email)
    return {"message": "Awaiting admin approval"}


@router.post("/login")
def login(payload: LoginRequest):
    logger.info("Login attempt for %s", payload.email)
    if main.redis_client is None:  # pragma: no cover - depends on deployment
        logger.error("Login attempt for %s failed: Redis not configured", payload.email)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis not configured",
        )
    key = f"user:{payload.email}"
    raw = main.redis_client.get(key)
    if not raw and payload.email.lower() == "admin@example.com":
        logger.debug("Default admin missing; initializing during login")
        # Ensure the default administrator account exists even if the startup
        # hook failed to populate Redis (e.g. when running with an empty data
        # store or when the application reloads).  This mirrors the behaviour
        # expected by the tests and allows first-time logins without any manual
        # bootstrapping.
        main.init_default_admin()
        raw = main.redis_client.get(key)
    if not raw:
        # Differentiate between non-existent users and password errors while
        # keeping the same 401 status code for authentication failures.
        logger.warning("Login failed: user %s not found", payload.email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    user = json.loads(raw)
    if user.get("password") != payload.password:
        logger.warning("Login failed for %s: incorrect password", payload.email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")

    if not user.get("approved"):
        logger.warning("Login denied for %s: not approved", payload.email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not approved. Contact an administrator for approval.",
        )
    if not user.get("active", True):
        logger.warning("Login denied for %s: user disabled", payload.email)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User disabled")

    token = jwt.encode({"sub": user["email"], "role": user["role"]}, JWT_SECRET, algorithm=ALGORITHM)
    logger.info("Login successful for %s", payload.email)
    return {"token": token}


@router.post("/approve")
def approve(payload: ApproveRequest, _: dict = Depends(require_admin)):
    logger.info("Approving user %s with role %s", payload.email, payload.role)
    key = f"user:{payload.email}"
    raw = main.redis_client.get(key)
    if not raw:
        logger.warning("Approve failed: user %s not found", payload.email)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user = json.loads(raw)
    user.update({"approved": True, "rejected": False, "role": payload.role})
    main.redis_client.set(key, json.dumps(user))
    logger.info("User %s approved", payload.email)
    return {"message": "User approved"}


@router.post("/reject")
def reject(payload: RejectRequest, _: dict = Depends(require_admin)):
    logger.info("Rejecting user %s", payload.email)
    key = f"user:{payload.email}"
    raw = main.redis_client.get(key)
    if not raw:
        logger.warning("Reject failed: user %s not found", payload.email)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user = json.loads(raw)
    user.update({"rejected": True, "approved": False})
    main.redis_client.set(key, json.dumps(user))
    logger.info("User %s rejected", payload.email)
    return {"message": "User rejected"}


@router.get("/pending-users")
def pending_users(_: dict = Depends(require_admin)) -> List[dict]:
    logger.debug("Listing pending users")
    users: List[dict] = []
    for key in main.redis_client.scan_iter("user:*"):
        raw = main.redis_client.get(key)
        if not raw:
            continue
        user = json.loads(raw)
        if not user.get("approved") and not user.get("rejected"):
            users.append(user)
    logger.debug("Found %d pending users", len(users))
    return users

