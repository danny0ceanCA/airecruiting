import os
import json
import redis


def migrate_emails_lowercase() -> None:
    """Convert all user:* keys to lowercase and merge duplicates."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("Missing REDIS_URL")

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    renamed = 0
    merged = 0
    seen: dict[str, dict] = {}

    for key in list(client.scan_iter("user:*")):
        email = key.split("user:", 1)[1]
        email_lc = email.lower()
        data_raw = client.get(key)
        try:
            data = json.loads(data_raw) if data_raw else {}
        except Exception:
            data = {}
        if email != email_lc:
            lc_key = f"user:{email_lc}"
            if lc_key in seen or client.exists(lc_key):
                existing_raw = client.get(lc_key)
                try:
                    existing = json.loads(existing_raw) if existing_raw else {}
                except Exception:
                    existing = {}
                merged_data = {**existing, **data}
                client.set(lc_key, json.dumps(merged_data))
                merged += 1
            else:
                client.rename(key, lc_key)
                renamed += 1
                seen[lc_key] = data
        else:
            seen[key] = data
            continue
        if key != f"user:{email_lc}":
            client.delete(key)

    print(f"Migration complete. Renamed {renamed} keys. Merged {merged} duplicates.")


if __name__ == "__main__":
    migrate_emails_lowercase()
