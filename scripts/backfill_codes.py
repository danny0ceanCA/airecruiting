import os
import json
import redis


def backfill_institutional_codes():
    """Copy school_code to institutional_code for user and student records."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("Missing REDIS_URL")

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    total_updated = 0

    for pattern in ("user:*", "student:*"):
        for key in client.scan_iter(pattern):
            raw = client.get(key)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            inst = data.get("institutional_code")
            school = data.get("school_code")
            if (not inst) and school:
                data["institutional_code"] = school
                client.set(key, json.dumps(data))
                total_updated += 1
    print(f"Backfill complete. Updated {total_updated} records.")


if __name__ == "__main__":
    backfill_institutional_codes()
