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

import app.main as main

JWT_SECRET = main.JWT_SECRET
ALGORITHM = main.ALGORITHM


router = APIRouter(prefix="", tags=["auth"])


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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    raw = main.redis_client.get(f"user:{email}")
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return json.loads(raw)


def require_admin(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
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

    if payload.role != "applicant" and not payload.school_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="School code required")

    key = f"user:{payload.email}"
    if main.redis_client.exists(key):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")

    data = payload.model_dump()
    data.update({"approved": False, "rejected": False, "active": True})
    main.redis_client.set(key, json.dumps(data))

    return {"message": "Awaiting admin approval"}


@router.post("/login")
def login(payload: LoginRequest):
    key = f"user:{payload.email}"
    raw = main.redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user = json.loads(raw)
    if user.get("password") != payload.password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.get("approved"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not approved")
    if not user.get("active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User disabled")

    token = jwt.encode({"sub": user["email"], "role": user["role"]}, JWT_SECRET, algorithm=ALGORITHM)
    return {"token": token}


@router.post("/approve")
def approve(payload: ApproveRequest, _: dict = Depends(require_admin)):
    key = f"user:{payload.email}"
    raw = main.redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user = json.loads(raw)
    user.update({"approved": True, "rejected": False, "role": payload.role})
    main.redis_client.set(key, json.dumps(user))
    return {"message": "User approved"}


@router.post("/reject")
def reject(payload: RejectRequest, _: dict = Depends(require_admin)):
    key = f"user:{payload.email}"
    raw = main.redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user = json.loads(raw)
    user.update({"rejected": True, "approved": False})
    main.redis_client.set(key, json.dumps(user))
    return {"message": "User rejected"}


@router.get("/pending-users")
def pending_users(_: dict = Depends(require_admin)) -> List[dict]:
    users: List[dict] = []
    for key in main.redis_client.scan_iter("user:*"):
        raw = main.redis_client.get(key)
        if not raw:
            continue
        user = json.loads(raw)
        if not user.get("approved") and not user.get("rejected"):
            users.append(user)
    return users

