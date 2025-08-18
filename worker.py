import os
import json
import logging

import redis
from dotenv import load_dotenv
from rq import Worker, Queue

from backend.app.services.summary import send_weekly_summary
from scripts.schedule_weekly_summary import schedule_weekly_summary

load_dotenv()

missing_vars = [
    var
    for var in [
        "OPENAI_API_KEY",
        "SUMMARY_MODEL",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "EMAIL_SENDER",
    ]
    if not os.getenv(var)
]
if missing_vars:
    logging.warning("Missing environment variables: %s", ", ".join(missing_vars))

redis_url = os.getenv("REDIS_URL")
if not redis_url:
    raise RuntimeError("Missing REDIS_URL")

redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
rq_client = redis.Redis.from_url(redis_url)

logger = logging.getLogger(__name__)

def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()

def weekly_summary_worker() -> None:
    """Send summaries to career staff and admins."""
    for key in redis_client.scan_iter("user:*"):
        raw = redis_client.get(key)
        if not raw:
            continue
        try:
            user = json.loads(raw)
        except Exception:
            continue
        role = user.get("role")
        if role in {"career", "admin"}:
            raw_email = key.split("user:", 1)[1]
            email = normalize_email(raw_email)
            logger.info("Sending weekly summary to %s (normalized %s)", raw_email, email)
            try:
                if send_weekly_summary(email):
                    logger.info("Successfully sent weekly summary to %s", email)
                else:
                    logger.warning("No weekly summary sent to %s", email)
            except Exception:
                logger.exception("Failed to send weekly summary to %s", email)


if __name__ == "__main__":
    schedule_weekly_summary()
    default_queue = Queue(connection=rq_client)
    weekly_queue = Queue("weekly", connection=rq_client)
    Worker([default_queue, weekly_queue], connection=rq_client).work()
