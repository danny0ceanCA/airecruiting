import json
from datetime import datetime

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt

from app.core.config import (
    ACTIVITY_LOG_KEY,
    ADMIN_ROLES,
    ALGORITHM,
    JWT_SECRET,
    REFRESH_TOKEN_LOOKUP_PREFIX,
    REFRESH_TOKEN_USER_PREFIX,
)
from app.core.logging import get_logger, request_id_ctx_var
from app.core.security import (
    generate_access_token,
    get_current_user,
    _hash_refresh_token,
    issue_refresh_token,
    revoke_refresh_token,
)
from app.db.redis_client import redis_client
from app.models.user import (
    ApproveRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RejectRequest,
    VerifyTokenRequest,
)
from app.services.core_utils import (
    find_user_key,
    get_school_label,
    normalize_email,
    resolve_student_key,
    student_email_key,
    student_key,
    user_key,
)
from app.services.email import send_email

router = APIRouter()

logger = get_logger(__name__)

@router.post("/register")
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

@router.post("/login")
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

@router.post("/refresh")
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

@router.post("/verify-token")
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

@router.post("/approve")
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

@router.post("/reject")
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

@router.get("/pending-users")
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

