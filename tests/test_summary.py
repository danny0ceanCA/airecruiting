import json
import os
from datetime import datetime, timezone, timedelta

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from backend.app.services import summary


class DummyRedis:
    def __init__(self):
        self.store = {}
        self.lists = {}
        self.sets = {}
        self.hashes = {}

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

        for k in list(self.store.keys()) + list(self.lists.keys()) + list(self.hashes.keys()):
            if fnmatch(k, pattern):
                yield k

    def scan(self, cursor=0, match=None, count=None):
        from fnmatch import fnmatch
        keys = [k for k in list(self.store.keys()) if not match or fnmatch(k, match)]
        return 0, keys

    def smembers(self, key):
        return self.sets.get(key, set())

    def scard(self, key):
        return len(self.smembers(key))

    def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    def srem(self, key, value):
        if key in self.sets:
            self.sets[key].discard(value)

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hscan_iter(self, key):
        for field, value in self.hashes.get(key, {}).items():
            yield field, value



def test_admin_weekly_summary():
    summary.redis_client = DummyRedis()
    now = datetime(2025, 8, 8, tzinfo=timezone.utc)

    # Users
    summary.redis_client.set("user:career@example.com", json.dumps({"role": "career"}))
    summary.redis_client.set("user:admin@example.com", json.dumps({"role": "admin"}))

    token = "tok-1"
    sent_ts = now.isoformat()
    summary.redis_client.hset(
        summary.EMAIL_OPEN_TOKENS_KEY,
        token,
        json.dumps(
            {
                "student_email": "stu@example.com",
                "job_code": "1",
                "sent": sent_ts,
            }
        ),
    )

    # Activity log for career user
    creation_log = {
        "user": "career@example.com",
        "method": "POST",
        "path": "/students",
        "timestamp": now.isoformat(),
        "student_email": "stu@example.com",
    }
    summary.redis_client.lpush(summary.ACTIVITY_LOG_KEY, json.dumps(creation_log))

    open_log = {"event": "email_open", "token": token, "timestamp": sent_ts}
    click_log = {"event": "email_click", "token": token, "timestamp": sent_ts}
    summary.redis_client.lpush(summary.ACTIVITY_LOG_KEY, json.dumps(open_log))
    summary.redis_client.lpush(summary.ACTIVITY_LOG_KEY, json.dumps(click_log))

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

    def fake_send_email(
        to,
        subject,
        body,
        html_body=None,
        attachments=None,
        track_token=None,
        reply_token=None,
    ):
        sent["to"] = to
        sent["subject"] = subject
        sent["body"] = body
        return "support@example.com"

    summary.send_email = fake_send_email

    captured_stats = {}

    def fake_build(stats, user_name):
        captured_stats["stats"] = stats
        return "body"

    summary.build_summary_narrative = fake_build

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    original_dt = summary.datetime
    summary.datetime = FixedDateTime
    summary.send_weekly_summary("admin@example.com")
    summary.datetime = original_dt

    assert sent["to"] == "admin@example.com"
    assert "Weekly Activity Summary" in sent["subject"]
    assert (
        captured_stats["stats"]["users"]["career@example.com"]["created_count"] == 1
    )
    email_stats = captured_stats["stats"]["email_analytics"]
    assert email_stats["sent_count"] == 1
    assert email_stats["unique_click_count"] == 1
    assert email_stats["click_students"] == ["stu@example.com"]


def test_compile_weekly_stats_handles_naive_timestamp():
    summary.redis_client = DummyRedis()
    now = datetime(2025, 8, 8, tzinfo=timezone.utc)
    naive = now.replace(tzinfo=None)

    log = {
        "user": "career@example.com",
        "method": "POST",
        "path": "/students",
        "timestamp": naive.isoformat(),
        "student_email": "stu@example.com",
    }
    summary.redis_client.lpush(summary.ACTIVITY_LOG_KEY, json.dumps(log))

    job = {
        "assigned_students": ["stu@example.com"],
        "placed_students": [],
        "student_notes": {
            "stu@example.com": [{"text": "note", "timestamp": naive.isoformat()}]
        },
    }
    summary.redis_client.set("job:1", json.dumps(job))

    stats = summary.compile_weekly_stats("career@example.com", now)
    assert stats["created_count"] == 1
    assert stats["students"][0]["latest_note"]["text"] == "note"
    assert stats["email_analytics"]["sent_count"] == 0


def test_compile_weekly_stats_includes_all_notes():
    summary.redis_client = DummyRedis()
    now = datetime(2025, 8, 8, tzinfo=timezone.utc)

    log = {
        "user": "career@example.com",
        "method": "POST",
        "path": "/students",
        "timestamp": now.isoformat(),
        "student_email": "stu@example.com",
    }
    summary.redis_client.lpush(summary.ACTIVITY_LOG_KEY, json.dumps(log))

    earlier = (now - timedelta(days=14)).isoformat()
    job = {
        "assigned_students": ["stu@example.com"],
        "placed_students": [],
        "student_notes": {
            "stu@example.com": [
                {"text": "old", "timestamp": earlier},
                {"text": "new", "timestamp": now.isoformat()},
            ]
        },
    }
    summary.redis_client.set("job:1", json.dumps(job))

    stats = summary.compile_weekly_stats("career@example.com", now)
    notes = stats["students"][0]["notes"]
    assert [n["text"] for n in notes] == ["old", "new"]
    assert stats["notes_count"] == 1
    assert stats["email_analytics"]["unique_open_count"] == 0


def test_preexisting_student_assignments_counted():
    summary.redis_client = DummyRedis()
    summary.send_email = lambda *a, **k: None  # avoid _ensure_dependencies import
    now = datetime(2025, 8, 8, tzinfo=timezone.utc)
    earlier = (now - timedelta(days=14)).isoformat()

    # Student created before the week
    student = {
        "email": "old@example.com",
        "created_by": "career@example.com",
        "created_at": earlier,
    }
    summary.redis_client.set("student:old@example.com", json.dumps(student))

    job = {
        "assigned_students": ["old@example.com"],
        "placed_students": ["old@example.com"],
        "student_notes": {},
    }
    summary.redis_client.set("job:1", json.dumps(job))

    stats = summary.compile_weekly_stats("career@example.com", now)
    assert stats["created_count"] == 0
    assert stats["assignment_count"] == 1
    assert stats["email_analytics"]["unique_click_count"] == 0
    assert stats["placement_count"] == 1
    assert stats["engaged_count"] == 1
    assert stats["students"] == []


def test_compile_weekly_stats_excludes_unowned_email_tokens():
    summary.redis_client = DummyRedis()
    now = datetime(2025, 8, 8, tzinfo=timezone.utc)

    owned_student = {
        "email": "owned@example.com",
        "created_by": "career@example.com",
        "created_at": now.isoformat(),
    }
    summary.redis_client.set("student:owned@example.com", json.dumps(owned_student))

    other_student = {
        "email": "other@example.com",
        "created_by": "other@example.com",
        "created_at": now.isoformat(),
    }
    summary.redis_client.set("student:other@example.com", json.dumps(other_student))

    job = {
        "assigned_students": [],
        "placed_students": [],
        "student_notes": {
            "owned@example.com": [{"text": "weekly", "timestamp": now.isoformat()}]
        },
    }
    summary.redis_client.set("job:1", json.dumps(job))

    summary.redis_client.hset(
        summary.EMAIL_OPEN_TOKENS_KEY,
        "tok-owned",
        json.dumps(
            {
                "student_email": "owned@example.com",
                "job_code": "1",
                "sent": now.isoformat(),
            }
        ),
    )

    summary.redis_client.hset(
        summary.EMAIL_OPEN_TOKENS_KEY,
        "tok-other",
        json.dumps(
            {
                "student_email": "other@example.com",
                "job_code": "2",
                "sent": now.isoformat(),
            }
        ),
    )

    stats = summary.compile_weekly_stats("career@example.com", now)

    assert [student["email"] for student in stats["students"]] == ["owned@example.com"]
    email_stats = stats["email_analytics"]
    assert email_stats["sent_count"] == 1
    assert email_stats["per_student"][0]["email"] == "owned@example.com"


def test_compile_weekly_stats_for_director_codes():
    summary.redis_client = DummyRedis()
    now = datetime(2025, 8, 8, tzinfo=timezone.utc)

    director = {
        "role": summary.CAREER_DIRECTOR_ROLE,
        "institutional_codes": ["1001", "2002"],
    }
    summary.redis_client.set("user:director@example.com", json.dumps(director))

    student_one = {
        "email": "one@example.com",
        "institutional_code": "1001",
        "created_by": "other@example.com",
        "created_at": now.isoformat(),
    }
    student_two = {
        "email": "two@example.com",
        "institutional_code": "2002",
        "created_by": "third@example.com",
        "created_at": now.isoformat(),
    }
    student_three = {
        "email": "three@example.com",
        "institutional_code": "3003",
        "created_by": "third@example.com",
        "created_at": now.isoformat(),
    }
    summary.redis_client.set("student:one@example.com", json.dumps(student_one))
    summary.redis_client.set("student:two@example.com", json.dumps(student_two))
    summary.redis_client.set("student:three@example.com", json.dumps(student_three))

    job = {
        "assigned_students": ["one@example.com", "two@example.com"],
        "placed_students": ["two@example.com"],
        "student_notes": {
            "one@example.com": [{"text": "note", "timestamp": now.isoformat()}],
            "two@example.com": [{"text": "note2", "timestamp": now.isoformat()}],
        },
    }
    summary.redis_client.set("job:dir", json.dumps(job))

    stats = summary.compile_weekly_stats("director@example.com", now)
    assert stats["created_count"] == 2
    assert len(stats["students"]) == 2
    emails = {entry["email"] for entry in stats["students"]}
    assert emails == {"one@example.com", "two@example.com"}


def test_build_summary_prompt_omits_notes_section_when_no_notes():
    now = datetime(2025, 8, 8, tzinfo=timezone.utc)

    stats = {
        "created_count": 0,
        "engaged_count": 0,
        "assignment_count": 0,
        "placement_count": 0,
        "notes_count": 0,
        "students": [],
        "window_end": now.isoformat(),
        "email_analytics": {
            "sent_count": 0,
            "unique_open_count": 0,
            "unique_click_count": 0,
            "click_students": [],
            "open_students": [],
            "per_student": [],
        },
    }

    prompt = summary.build_summary_prompt(stats, "Career Coach")
    assert "Student Notes Summary" not in prompt


def test_build_summary_prompt_includes_notes_section_when_notes_present():
    now = datetime(2025, 8, 8, tzinfo=timezone.utc)

    stats = {
        "created_count": 1,
        "engaged_count": 1,
        "assignment_count": 2,
        "placement_count": 1,
        "notes_count": 1,
        "students": [
            {
                "email": "owned@example.com",
                "assigned_jobs": 0,
                "placed_jobs": 0,
                "latest_note": {"text": "weekly", "timestamp": now.isoformat()},
                "notes": [{"text": "weekly", "timestamp": now.isoformat()}],
                "email_metrics": {"sent": 1, "opened": True, "clicked": False},
            }
        ],
        "window_end": now.isoformat(),
        "email_analytics": {
            "sent_count": 1,
            "unique_open_count": 1,
            "unique_click_count": 0,
            "click_students": [],
            "open_students": ["owned@example.com"],
            "per_student": [
                {
                    "email": "owned@example.com",
                    "sent": 1,
                    "opened": True,
                    "clicked": False,
                }
            ],
        },
    }

    prompt = summary.build_summary_prompt(stats, "Career Coach")
    assert "Student Notes Summary" in prompt
