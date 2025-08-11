import json
from datetime import datetime

from app.main import ACTIVITY_LOG_KEY, redis_client


def load_activity_logs():
    """Return parsed activity log entries."""
    entries = []
    raw_entries = redis_client.lrange(ACTIVITY_LOG_KEY, 0, -1) or []
    for raw in raw_entries:
        try:
            entries.append(json.loads(raw))
        except Exception:
            continue
    return entries


def build_indices(logs):
    """Build indices for POST /students and /students/upload logs."""
    student_posts: dict[str, str] = {}
    upload_posts: list[dict[str, str]] = []
    for log in logs:
        if log.get("method") != "POST":
            continue
        path = log.get("path")
        if path == "/students":
            user = log.get("user")
            ts = log.get("timestamp")
            if user and ts and user not in student_posts:
                student_posts[user] = ts
        elif path == "/students/upload":
            ts = log.get("timestamp")
            user = log.get("user")
            if ts and user:
                upload_posts.append({"timestamp": ts, "user": user})
    return student_posts, upload_posts


def find_upload_match(student_ts: datetime | None, uploads: list[dict[str, str]]):
    """Return upload log with timestamp within 5 minutes of student_ts."""
    if student_ts is None:
        return None
    for log in uploads:
        try:
            log_ts = datetime.fromisoformat(log["timestamp"])
        except Exception:
            continue
        if abs((student_ts - log_ts).total_seconds()) <= 300:
            return log
    return None


def main() -> None:
    logs = load_activity_logs()
    student_posts, upload_posts = build_indices(logs)

    updated = []
    manual_review = []

    for key in redis_client.scan_iter("student:*"):
        raw = redis_client.get(key)
        if not raw:
            continue
        try:
            student = json.loads(raw)
        except Exception:
            manual_review.append(key.split("student:", 1)[1])
            continue

        created_at = student.get("created_at")
        created_by = student.get("created_by")
        if created_at and created_by:
            continue

        email = key.split("student:", 1)[1]
        modified = False

        # Match applicant-created profiles by email
        if email in student_posts:
            ts = student_posts[email]
            if not created_at:
                student["created_at"] = ts
            if not created_by:
                student["created_by"] = email
            modified = True
        else:
            # Attempt to match to staff upload
            student_ts = None
            if created_at:
                try:
                    student_ts = datetime.fromisoformat(created_at)
                except Exception:
                    student_ts = None
            match = find_upload_match(student_ts, upload_posts)
            if match:
                if not created_at:
                    student["created_at"] = match["timestamp"]
                if not created_by:
                    student["created_by"] = match["user"]
                modified = True

        if modified:
            redis_client.set(key, json.dumps(student))
            updated.append(email)
        else:
            manual_review.append(email)

    print(
        f"Backfill complete. Updated {len(updated)} students; {len(manual_review)} need manual review."
    )
    if updated:
        print("Updated:", ", ".join(sorted(updated)))
    if manual_review:
        print("Manual review needed:", ", ".join(sorted(manual_review)))


if __name__ == "__main__":
    main()
