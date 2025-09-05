# scripts/schedule_weekly_summary.py
from __future__ import annotations
import os
import json
import logging
from datetime import timedelta
import redis
from rq_scheduler import Scheduler

# Call the real job directly (no extra scripts)
from backend.app.services.summary import send_weekly_summary

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

def _b2s(x):
    return x.decode() if isinstance(x, (bytes, bytearray)) else x

def schedule_weekly_summary() -> None:
    """
    Registers a weekly cron job for EACH career/admin user that calls:
      send_weekly_summary(<user_email>)
    Optional FIRST_RUN_ENQUEUE=1 will enqueue a one-time run immediately.
    """
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("Missing REDIS_URL")

    r = redis.Redis.from_url(redis_url)
    scheduler = Scheduler(queue_name="weekly", connection=r)

    # 1) Discover all target users
    targets: list[str] = []
    for key in r.scan_iter("user:*"):
        raw = r.get(key)
        if not raw:
            continue
        try:
            user = json.loads(_b2s(raw))
        except Exception:
            continue
        if user.get("role") in {"career", "admin", "junior_admin"}:
            email = _b2s(key).split("user:", 1)[1]
            targets.append(email)

    if not targets:
        log.warning("No career/admin/junior_admin users found; nothing to schedule.")
    else:
        log.info("Scheduling weekly summaries for %d users", len(targets))

    # 2) Register a cron per user (UTC time!)
    # Example: 16:30 UTC ≈ 08:30 AM Pacific during DST
    cron = os.getenv("WEEKLY_CRON", "30 16 * * 1")  # override via env if desired
    use_local_tz = os.getenv("USE_LOCAL_TZ", "0") == "1"

    # Optional: clean previous schedules for this func (avoid dupes)
    for job in scheduler.get_jobs():
        if job.func_name.endswith("backend.app.services.summary.send_weekly_summary"):
            scheduler.cancel(job)

    for email in targets:
        scheduler.cron(
            cron_string=cron,
            func=send_weekly_summary,
            args=[email],
            queue_name="weekly",
            use_local_timezone=use_local_tz,
            meta={"kind": "weekly_summary", "email": email},
            description=f"Weekly summary for {email}",
        )
        log.info("Scheduled weekly summary for %s at cron=%s (local_tz=%s)", email, cron, use_local_tz)

    # 3) First-run enqueue (optional): set FIRST_RUN_ENQUEUE=1 to send once now
    if os.getenv("FIRST_RUN_ENQUEUE", "0") == "1":
        # Use a Redis flag so we only trigger once
        if r.setnx("weekly:first_run_done", "1"):
            for email in targets:
                scheduler.enqueue_in(timedelta(seconds=2), send_weekly_summary, email)
                log.info("First-run enqueue requested; queued immediate send for %s", email)
        else:
            log.info("First-run enqueue already done previously; skipping.")

    print(f"Registered {len(targets)} weekly summary cron jobs.")

if __name__ == "__main__":
    schedule_weekly_summary()
