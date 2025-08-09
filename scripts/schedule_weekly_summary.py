import os
import redis
from rq_scheduler import Scheduler

from worker import weekly_summary_worker


def schedule_weekly_summary() -> None:
    """Enqueue weekly summaries every Monday at 08:00 server time."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("Missing REDIS_URL")
    connection = redis.Redis.from_url(redis_url)
    scheduler = Scheduler(queue_name="weekly", connection=connection)
    scheduler.cron("0 8 * * MON", func=weekly_summary_worker, queue_name="weekly")
    print("Scheduled weekly summary at 08:00 every Monday")


if __name__ == "__main__":
    schedule_weekly_summary()
