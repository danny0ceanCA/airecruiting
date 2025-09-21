import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import (
    ACTIVITY_LOG_KEY,
    ADMIN_ROLES,
    REFRESH_TOKEN_LOOKUP_PREFIX,
    REFRESH_TOKEN_USER_PREFIX,
    STUDENT_LOAD_TIME_KEY,
)
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.db.redis_client import redis_client
from app.models.metrics import StudentLoadTimeMetric

router = APIRouter()

logger = get_logger(__name__)

@router.post("/metrics/student-load-time")
def record_student_load_time(
    metric: StudentLoadTimeMetric, current_user: dict = Depends(get_current_user)
):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "role": metric.role,
        "duration": metric.duration,
    }
    try:
        redis_client.rpush(STUDENT_LOAD_TIME_KEY, json.dumps(entry))
    except Exception as e:
        logger.error("Failed to record student load time metric: %s", e)
    return {"status": "ok"}

@router.get("/metrics")
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
            or skey.startswith(f"{REFRESH_TOKEN_LOOKUP_PREFIX}:")
            or skey.startswith(f"{REFRESH_TOKEN_USER_PREFIX}:")
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

@router.get("/activity-log")
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

