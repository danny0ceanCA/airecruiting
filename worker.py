import os
import json
import redis
from rq import Worker, Queue

from backend.app.services.summary import send_weekly_summary

redis_url = os.getenv("REDIS_URL")
if not redis_url:
    raise RuntimeError("Missing REDIS_URL")

redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
rq_client = redis.Redis.from_url(redis_url)

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
            email = key.split("user:", 1)[1]
            send_weekly_summary(email)


if __name__ == "__main__":
    default_queue = Queue(connection=rq_client)
    weekly_queue = Queue("weekly", connection=rq_client)
    Worker([default_queue, weekly_queue], connection=rq_client).work()
