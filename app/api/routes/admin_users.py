import json

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import ADMIN_ROLES
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.db.redis_client import redis_client
from app.models.user import UpdateUserRequest
from app.services.core_utils import find_user_key, get_school_label, normalize_email

router = APIRouter()

logger = get_logger(__name__)

@router.get("/admin/users")
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

@router.put("/admin/users/{email}")
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

@router.delete("/admin/users/{email}")
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

@router.get("/dev/check-admin")
def check_admin():
    raw = redis_client.get("user:admin@example.com")
    if not raw:
        return {"exists": False}
    return json.loads(raw)

