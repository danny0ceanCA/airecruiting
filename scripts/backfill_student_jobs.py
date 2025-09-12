#!/usr/bin/env python3
"""Backfill student job reference sets from existing job records."""
import os
import json
import redis
from dotenv import load_dotenv

load_dotenv()

redis_url = os.getenv("REDIS_URL")
if not redis_url:
    raise RuntimeError("Missing REDIS_URL")

r = redis.Redis.from_url(redis_url, decode_responses=True)


def main() -> None:
    for job_key in r.scan_iter("job:*"):
        raw = r.get(job_key)
        if not raw:
            continue
        try:
            job = json.loads(raw)
        except Exception:
            continue
        code = job.get("job_code")
        if not code:
            continue
        mapping = {
            "assigned": job.get("assigned_students", []),
            "placed": job.get("placed_students", []),
            "rejected": job.get("rejected_students", []),
            "uninterested": job.get("uninterested_students", []),
        }
        for status, emails in mapping.items():
            for email in emails:
                r.sadd(f"student_jobs:{email}:{status}", code)

    print("Backfill complete")


if __name__ == "__main__":
    main()
