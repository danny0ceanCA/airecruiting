import os
import json
import logging
import time
import resource
import sys

import redis
from dotenv import load_dotenv
from rq import Worker, Queue

from backend.app.services.summary import send_weekly_summary
from scripts.schedule_weekly_summary import schedule_weekly_summary
from backend.app.logging_utils import (
    RequestIdFilter,
    get_logger,
    request_id_ctx_var,
)

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

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s [%(request_id)s] %(message)s",
)
for handler in logging.getLogger().handlers:
    handler.addFilter(RequestIdFilter())

logger = get_logger(__name__)

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
        if role in {"career", "admin", "junior_admin"}:
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


class RequestIdWorker(Worker):
    """RQ Worker that sets request ID context from job metadata."""

    def execute_job(self, job, queue):  # type: ignore[override]
        token = request_id_ctx_var.set(job.meta.get("request_id", "-"))
        start_time = time.perf_counter()
        start_usage = resource.getrusage(resource.RUSAGE_SELF)
        status = "success"
        exc_info = None
        try:
            return super().execute_job(job, queue)
        except Exception:
            status = "failure"
            exc_info = sys.exc_info()
            raise
        finally:
            end_time = time.perf_counter()
            end_usage = resource.getrusage(resource.RUSAGE_SELF)

            wall_time = end_time - start_time
            cpu_time = (
                (end_usage.ru_utime + end_usage.ru_stime)
                - (start_usage.ru_utime + start_usage.ru_stime)
            )
            rss_delta = end_usage.ru_maxrss - start_usage.ru_maxrss

            queue_name = getattr(queue, "name", str(queue))
            log_message = (
                "Job %s on queue %s status=%s runtime=%.4fs cpu_time=%.4fs rss_delta=%s"
            )

            if status == "success":
                logger.info(
                    log_message,
                    job.id,
                    queue_name,
                    status,
                    wall_time,
                    cpu_time,
                    rss_delta,
                )
            else:
                logger.exception(
                    log_message,
                    job.id,
                    queue_name,
                    status,
                    wall_time,
                    cpu_time,
                    rss_delta,
                    exc_info=exc_info,
                )

            request_id_ctx_var.reset(token)


if __name__ == "__main__":
    schedule_weekly_summary()
    default_queue = Queue(connection=rq_client)
    weekly_queue = Queue("weekly", connection=rq_client)
    RequestIdWorker([default_queue, weekly_queue], connection=rq_client).work()
