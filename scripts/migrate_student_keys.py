import os
import json
import redis
from dotenv import load_dotenv


def normalize_email(email: str | None) -> str:
    """Return a lowercase, stripped version of an email."""
    return (email or "").strip().lower()


def student_key(institution_code: str, student_id: str) -> str:
    """Return the canonical redis key for a student."""
    return f"student:{institution_code}:{student_id}"


def student_email_key(email: str) -> str:
    """Return the index key for a student email."""
    return f"student_email:{normalize_email(email)}"


def generate_student_id(client: redis.Redis) -> str:
    """Generate a new student identifier."""
    return str(client.incr("student_id"))


def migrate_student_keys() -> None:
    """Migrate legacy student:* keys to student:{institution_code}:{student_id}."""
    load_dotenv()
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("Missing REDIS_URL in .env or environment variables")

    client = redis.Redis.from_url(redis_url, decode_responses=True)

    migrated = 0
    manual_review: list[str] = []

    for key in client.scan_iter("student:*"):
        parts = key.split(":", 2)
        if len(parts) == 2:
            # Legacy key: student:<email>
            email = parts[1]
            inst_code = None
        elif len(parts) == 3:
            if parts[2].isdigit():
                # New-style key: student:<institution_code>:<student_id>
                continue
            inst_code = parts[1]
            email = parts[2]
        else:
            continue

        raw = client.get(key)
        if not raw:
            manual_review.append(email)
            client.delete(key)
            continue

        try:
            data = json.loads(raw)
        except Exception:
            manual_review.append(email)
            client.delete(key)
            continue

        inst_code = data.get("institutional_code") or inst_code
        rec_email = normalize_email(data.get("email") or email)
        if not inst_code or not rec_email:
            manual_review.append(email)
            continue

        student_id = data.get("student_id") or generate_student_id(client)
        data["student_id"] = student_id
        data["institutional_code"] = inst_code
        data["email"] = rec_email

        new_key = student_key(inst_code, student_id)
        client.set(new_key, json.dumps(data))
        client.set(student_email_key(rec_email), f"{inst_code}:{student_id}")
        client.delete(key)
        migrated += 1
        print(f"Migrated: {key} → {new_key}")

    print(
        f"\nMigration complete. Migrated {migrated} students; {len(manual_review)} need manual review."
    )
    if manual_review:
        print("Manual review:", ", ".join(sorted(manual_review)))


if __name__ == "__main__":
    migrate_student_keys()
