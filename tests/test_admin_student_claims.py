import os
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("GOOGLE_KEY", "test")

import json
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from jose import jwt
import app.main as main_app
from app.main import app, JWT_SECRET, ALGORITHM


class DummyRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, value):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def exists(self, key):
        return key in self.store

    def delete(self, key):
        self.store.pop(key, None)

    def scan_iter(self, pattern="*"):
        from fnmatch import fnmatch
        for k in list(self.store.keys()):
            if fnmatch(k, pattern):
                yield k

    def incr(self, key, amount=1):
        val = int(self.store.get(key, 0)) + amount
        self.store[key] = val
        return val

    def incrbyfloat(self, key, amount=1.0):
        val = float(self.store.get(key, 0.0)) + amount
        self.store[key] = val
        return val

    def mget(self, keys):
        return [self.store.get(k) for k in keys]

    def flushdb(self):
        self.store.clear()


main_app.redis_client = DummyRedis()
client = TestClient(app)


def _admin_header(email: str = "admin@example.com") -> dict:
    token = jwt.encode(
        {"sub": email, "role": "admin", "exp": datetime.utcnow() + timedelta(hours=1)},
        JWT_SECRET,
        algorithm=ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def test_clear_student_claim():
    main_app.redis_client.flushdb()
    student = {
        "email": "stu@example.com",
        "student_id": "1",
        "institutional_code": "1001",
        "claimed_by": "claimer@example.com",
    }
    main_app.persist_student_record(student["email"], student, "1001", "1")
    main_app.redis_client.set("student_claim:token1:stu@example.com", "stu@example.com")
    main_app.redis_client.set("student_claim:token2:other@example.com", "other@example.com")

    resp = client.delete("/admin/student-claims/stu@example.com", headers=_admin_header())
    assert resp.status_code == 200

    key = main_app.resolve_student_key("stu@example.com")
    raw = main_app.redis_client.get(key)
    data = json.loads(raw)
    assert "claimed_by" not in data

    assert not main_app.redis_client.exists("student_claim:token1:stu@example.com")
    assert main_app.redis_client.exists("student_claim:token2:other@example.com")
