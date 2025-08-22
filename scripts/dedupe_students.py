import os
import json
import redis
from collections import defaultdict
from dotenv import load_dotenv


def normalize_email(email: str | None) -> str:
    """Return a lowercase, stripped version of an email."""
    return (email or "").strip().lower()


def student_email_key(email: str) -> str:
    """Return the index key for a student email."""
    return f"student_email:{normalize_email(email)}"


def dedupe_students() -> None:
    """Remove duplicate student records keyed by email."""
    load_dotenv()
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("Missing REDIS_URL")

    client = redis.Redis.from_url(redis_url, decode_responses=True)

    students: dict[str, list[dict]] = defaultdict(list)

    for key in client.scan_iter("student:*:*"):
        if client.type(key) != "string":
            continue
        raw = client.get(key)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        email = normalize_email(data.get("email"))
        if not email:
            continue
        parts = key.split(":", 2)
        if len(parts) != 3:
            continue
        _, inst_code, sid = parts
        sid = data.get("student_id") or sid
        students[email].append({
            "key": key,
            "inst": inst_code,
            "sid": sid,
        })

    removed = 0
    summary: list[str] = []

    for email, records in students.items():
        # Always ensure index points to canonical record
        canonical = max(records, key=lambda r: int(r["sid"]) if str(r["sid"]).isdigit() else -1)
        client.set(student_email_key(email), f"{canonical['inst']}:{canonical['sid']}")
        if len(records) <= 1:
            continue
        removed_keys = []
        for rec in records:
            if rec is canonical:
                continue
            client.delete(rec["key"])
            removed += 1
            removed_keys.append(rec["key"])
        summary.append(
            f"{email}: kept {canonical['key']} removed {', '.join(removed_keys)}"
        )
        print(
            f"Email {email}: kept {canonical['key']}; removed {', '.join(removed_keys)}"
        )

    print(
        f"\nDeduplication complete. Removed {removed} duplicate records for {len(summary)} emails."
    )
    if summary:
        print("Duplicates removed:")
        for line in summary:
            print(f" - {line}")


if __name__ == "__main__":
    dedupe_students()
