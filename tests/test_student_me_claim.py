import os
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("GOOGLE_KEY", "test")

from fastapi.testclient import TestClient
from jose import jwt
import app.main as main_app
from app.main import app, JWT_SECRET, ALGORITHM
import backend.app.main  # noqa: F401
from datetime import datetime, timedelta
import json


class DummyRedis:
    def __init__(self):
        self.store = {}
        self.hashes = {}
        self.lists = {}

    def set(self, key, value):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def exists(self, key):
        return key in self.store

    def delete(self, key):
        self.store.pop(key, None)
        self.hashes.pop(key, None)
        self.lists.pop(key, None)

    def scan_iter(self, pattern="*"):
        from fnmatch import fnmatch
        for k in list(self.store.keys()) + list(self.hashes.keys()):
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
        self.hashes.clear()
        self.lists.clear()

    def hset(self, name, key, value):
        self.hashes.setdefault(name, {})[key] = value

    def hget(self, name, key):
        return self.hashes.get(name, {}).get(key)

    def hgetall(self, name):
        return dict(self.hashes.get(name, {}))

    def setex(self, key, ttl, value):
        self.set(key, value)


main_app.redis_client = DummyRedis()

client = TestClient(app)


def _auth_header(email: str) -> dict:
    token = jwt.encode(
        {"sub": email, "role": "applicant", "exp": datetime.utcnow() + timedelta(hours=1)},
        JWT_SECRET,
        algorithm=ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def test_student_me_requires_claimed_by_current_user():
    main_app.redis_client.flushdb()
    student = {
        "email": "stud@example.com",
        "student_id": "1",
        "institutional_code": "1001",
        "claimed_by": "other@example.com",
    }
    main_app.persist_student_record(student["email"], student, "1001", "1")

    resp = client.get("/students/me", headers=_auth_header("stud@example.com"))
    assert resp.status_code == 403


def test_student_me_allows_self_claimed_profile():
    main_app.redis_client.flushdb()
    student = {
        "email": "me@example.com",
        "student_id": "2",
        "institutional_code": "1001",
        "claimed_by": "me@example.com",
    }
    main_app.persist_student_record(student["email"], student, "1001", "2")

    resp = client.get("/students/me", headers=_auth_header("me@example.com"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "me@example.com"
