import base64
import json
import random
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse

from backend.app.services.summary import send_weekly_summary

from app.core.config import ACTIVITY_LOG_KEY, ADMIN_ROLES, EMAIL_OPEN_TOKENS_KEY
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.db.redis_client import redis_client
from app.services.email import send_email

router = APIRouter()

logger = get_logger(__name__)

TRANSPARENT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMBAc8o/QkAAAAASUVORK5CYII="
)

@router.get("/track/open/{token}.png")
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

@router.get("/track/click/{token}")
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

@router.post("/admin/test-notification")
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

@router.post("/admin/test-weekly-summary")
def admin_test_weekly_summary(current_user: dict = Depends(get_current_user)):
    """Manually trigger a weekly summary email to the admin's address."""
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    send_weekly_summary(current_user["sub"])
    return {"message": "Weekly summary sent"}
