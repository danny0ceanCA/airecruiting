import os
import pytest
import scripts.remove_student_user_records as mod


class DummyRedis:
    def __init__(self, data):
        self.store = dict(data)

    def scan_iter(self, pattern="*"):
        prefix = pattern.rstrip("*")
        for k in list(self.store.keys()):
            if k.startswith(prefix):
                yield k

    def exists(self, key):
        return key in self.store

    def delete(self, key):
        self.store.pop(key, None)


def test_removes_users_with_student_records(monkeypatch, capsys):
    os.environ["REDIS_URL"] = "redis://example"  # dummy value
    data = {
        "user:a@example.com": "u1",
        "user:b@example.com": "u2",
        "student:a@example.com": "s1",
        "student_email:b@example.com": "s2",
        "user:c@example.com": "u3",
    }
    dummy = DummyRedis(data)
    monkeypatch.setattr(mod.redis.Redis, "from_url", lambda *a, **k: dummy)

    mod.remove_student_user_records()

    assert "user:a@example.com" not in dummy.store
    assert "user:b@example.com" not in dummy.store
    assert "user:c@example.com" in dummy.store
    captured = capsys.readouterr()
    assert "Removed 2 user records" in captured.out


def test_requires_redis_url(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(RuntimeError):
        mod.remove_student_user_records()
