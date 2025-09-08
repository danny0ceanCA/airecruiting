import json
import os
from dotenv import load_dotenv
import redis

load_dotenv()

redis_url = os.getenv("REDIS_URL")
if not redis_url:
    raise RuntimeError("Missing REDIS_URL")

r = redis.Redis.from_url(redis_url, decode_responses=True)


def main():
    for key in r.scan_iter("job:*"):
        raw = r.get(key)
        if not raw:
            continue
        try:
            job = json.loads(raw)
        except Exception:
            continue
        code = job.get("job_code")
        if not code:
            continue
        for email in job.get("assigned_students", []) or []:
            r.hset(f"student_jobs:{email}", code, "assigned")
            r.delete(f"cache:student_profile:{email}")
        for email in job.get("placed_students", []) or []:
            r.hset(f"student_jobs:{email}", code, "placed")
            r.delete(f"cache:student_profile:{email}")
        for email in job.get("rejected_students", []) or []:
            r.hset(f"student_jobs:{email}", code, "rejected")
            r.delete(f"cache:student_profile:{email}")
        for email in job.get("uninterested_students", []) or []:
            r.hset(f"student_jobs:{email}", code, "uninterested")
            r.delete(f"cache:student_profile:{email}")


if __name__ == "__main__":
    main()
