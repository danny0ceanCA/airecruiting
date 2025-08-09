import json
from datetime import datetime, timezone

from backend.app.services import summary


class DummyRedis:
    def __init__(self):
        self.store = {}
        self.lists = {}

    def set(self, key, value):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def lrange(self, key, start, end):
        lst = self.lists.get(key, [])
        if end == -1:
            end = len(lst) - 1
        return lst[start : end + 1]

    def scan_iter(self, pattern="*"):
        from fnmatch import fnmatch

        for k in list(self.store.keys()) + list(self.lists.keys()):
            if fnmatch(k, pattern):
                yield k



def test_admin_weekly_summary():
    summary.redis_client = DummyRedis()
    now = datetime.now(timezone.utc)

    # Users
    summary.redis_client.set("user:career@example.com", json.dumps({"role": "career"}))
    summary.redis_client.set("user:admin@example.com", json.dumps({"role": "admin"}))

    # Activity log for career user
    log = {
        "user": "career@example.com",
        "method": "POST",
        "path": "/students",
        "timestamp": now.isoformat(),
        "student_email": "stu@example.com",
    }
    summary.redis_client.lpush(summary.ACTIVITY_LOG_KEY, json.dumps(log))

    # Job record
    job = {
        "assigned_students": ["stu@example.com"],
        "placed_students": [],
        "student_notes": {
            "stu@example.com": [{"text": "note", "timestamp": now.isoformat()}]
        },
    }
    summary.redis_client.set("job:1", json.dumps(job))

    sent = {}

    def fake_send_email(to, subject, body):
        sent["to"] = to
        sent["subject"] = subject
        sent["body"] = body

    summary.send_email = fake_send_email

    captured_stats = {}

    def fake_build(stats, user_name):
        captured_stats["stats"] = stats
        return "body"

    summary.build_summary_narrative = fake_build

    summary.send_weekly_summary("admin@example.com")

    assert sent["to"] == "admin@example.com"
    assert "Weekly Activity Summary" in sent["subject"]
    assert (
        captured_stats["stats"]["users"]["career@example.com"]["created_count"] == 1
    )
