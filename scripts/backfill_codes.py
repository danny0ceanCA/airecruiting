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

    for pattern in ("user:*", "student:*:*"):
        for key in client.scan_iter(pattern):
            if client.type(key) != "string":
                continue
            try:
                raw = client.get(key)
            except redis.exceptions.ResponseError:
                continue
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue

            modified = False
            if pattern.startswith("student"):
                key_str = key if isinstance(key, str) else key.decode()
                parts = key_str.split(":", 2)
                if len(parts) == 3:
                    _, inst_code, sid = parts
                    if "institutional_code" not in data:
                        data["institutional_code"] = inst_code
                        modified = True
                    if "student_id" not in data:
                        data["student_id"] = sid
                        modified = True

            inst = data.get("institutional_code")
            school = data.get("school_code")
            if (not inst) and school:
                data["institutional_code"] = school
                modified = True

            if modified:
                try:
                    client.set(key, json.dumps(data))
                except redis.exceptions.ResponseError:
                    continue
                total_updated += 1
    print(f"Backfill complete. Updated {total_updated} records.")


if __name__ == "__main__":
    backfill_institutional_codes()
