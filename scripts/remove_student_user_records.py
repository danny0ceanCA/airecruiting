import os
import redis
from typing import Any


def remove_student_user_records() -> None:
    """Delete user:* keys for emails with existing student profiles."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("Missing REDIS_URL")
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    removed = 0
    for ukey in list(client.scan_iter("user:*")):
        email = ukey.split("user:", 1)[1]
        if client.exists(f"student:{email}") or client.exists(f"student_email:{email}"):
            client.delete(ukey)
            removed += 1
    print(f"Removed {removed} user records linked to student profiles.")


if __name__ == "__main__":
    remove_student_user_records()
