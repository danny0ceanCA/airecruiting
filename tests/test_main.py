import os
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "test")

from fastapi.testclient import TestClient
from jose import jwt
import json
import app.main as main_app


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

    def flushdb(self):
        self.store.clear()


main_app.redis_client = DummyRedis()
from app.main import app, JWT_SECRET, ALGORITHM, init_default_admin

client = TestClient(app)


def test_read_root():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"message": "Hello, World"}


def test_default_admin_exists():
    main_app.redis_client.flushdb()
    init_default_admin()
    raw = main_app.redis_client.get("user:admin@example.com")
    admin = json.loads(raw)
    assert admin is not None
    assert admin["role"] == "admin"
    assert admin["approved"] is True


def test_registration_flow():
    main_app.redis_client.flushdb()
    init_default_admin()
    admin_login = client.post(
        "/login",
        json={"email": "admin@example.com", "password": "admin123"},
    )
    admin_token = admin_login.json()["token"]

    user_data = {
        "email": "jane@example.com",
        "first_name": "Jane",
        "last_name": "Doe",
        "school": "Test University",
        "password": "secret",
    }

    # Register
    resp = client.post("/register", json=user_data)
    assert resp.status_code == 200
    assert "Awaiting admin approval" in resp.json()["message"]

    # Duplicate registration
    dup_resp = client.post("/register", json=user_data)
    assert dup_resp.status_code == 400

    # Login before approval should fail
    login_before = client.post(
        "/login", json={"email": user_data["email"], "password": user_data["password"]}
    )
    assert login_before.status_code == 403

    # Approve user using admin token
    approve_resp = client.post(
        "/approve",
        json={"email": user_data["email"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert approve_resp.status_code == 200

    # Login after approval
    login_after = client.post(
        "/login", json={"email": user_data["email"], "password": user_data["password"]}
    )
    assert login_after.status_code == 200
    token = login_after.json().get("token")
    assert token
    payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    assert payload["sub"] == user_data["email"]
    assert payload["role"] == "user"


def test_non_admin_cannot_approve():
    main_app.redis_client.flushdb()

    # Create regular user who will attempt approval
    user1 = {
        "email": "user1@example.com",
        "first_name": "User",
        "last_name": "One",
        "school": "Test U",
        "password": "pass1",
    }
    client.post("/register", json=user1)
    key = f"user:{user1['email']}"
    data = json.loads(main_app.redis_client.get(key))
    data["approved"] = True
    main_app.redis_client.set(key, json.dumps(data))
    login_resp = client.post("/login", json={"email": user1["email"], "password": user1["password"]})
    token = login_resp.json()["token"]

    # Create user to be approved
    target = {
        "email": "user2@example.com",
        "first_name": "User",
        "last_name": "Two",
        "school": "Test U",
        "password": "pass2",
    }
    client.post("/register", json=target)

    resp = client.post(
        "/approve",
        json={"email": target["email"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_pending_users_endpoint():
    main_app.redis_client.flushdb()
    init_default_admin()

    admin_login = client.post(
        "/login",
        json={"email": "admin@example.com", "password": "admin123"},
    )
    admin_token = admin_login.json()["token"]

    u1 = {
        "email": "pend1@example.com",
        "first_name": "Pending",
        "last_name": "One",
        "school": "PU",
        "password": "pass1",
    }
    u2 = {
        "email": "pend2@example.com",
        "first_name": "Pending",
        "last_name": "Two",
        "school": "PU",
        "password": "pass2",
    }
    client.post("/register", json=u1)
    client.post("/register", json=u2)

    resp = client.get(
        "/pending-users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    assert u1["email"] in emails and u2["email"] in emails


def test_pending_users_forbidden_for_non_admin():
    main_app.redis_client.flushdb()
    init_default_admin()

    regular = {
        "email": "regular@example.com",
        "first_name": "Reg",
        "last_name": "User",
        "school": "RU",
        "password": "secret",
    }
    client.post("/register", json=regular)
    key = f"user:{regular['email']}"
    data = json.loads(main_app.redis_client.get(key))
    data["approved"] = True
    main_app.redis_client.set(key, json.dumps(data))
    login_resp = client.post("/login", json={"email": regular["email"], "password": regular["password"]})
    token = login_resp.json()["token"]

    resp = client.get(
        "/pending-users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_admin_can_reject_user():
    main_app.redis_client.flushdb()
    init_default_admin()

    admin_login = client.post(
        "/login",
        json={"email": "admin@example.com", "password": "admin123"},
    )
    admin_token = admin_login.json()["token"]

    target = {
        "email": "rejectme@example.com",
        "first_name": "Reject",
        "last_name": "Me",
        "school": "RMU",
        "password": "pwd",
    }
    client.post("/register", json=target)

    resp = client.post(
        "/reject",
        json={"email": target["email"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    raw = main_app.redis_client.get(f"user:{target['email']}")
    assert json.loads(raw)["rejected"] is True

    pending = client.get(
        "/pending-users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    emails = [u["email"] for u in pending.json()]
    assert target["email"] not in emails


def test_non_admin_cannot_reject():
    main_app.redis_client.flushdb()

    regular = {
        "email": "reg@example.com",
        "first_name": "Reg",
        "last_name": "User",
        "school": "RU",
        "password": "pass",
    }
    client.post("/register", json=regular)
    key = f"user:{regular['email']}"
    data = json.loads(main_app.redis_client.get(key))
    data["approved"] = True
    main_app.redis_client.set(key, json.dumps(data))
    login_resp = client.post("/login", json={"email": regular["email"], "password": regular["password"]})
    token = login_resp.json()["token"]

    target = {
        "email": "victim@example.com",
        "first_name": "Vic",
        "last_name": "Tim",
        "school": "TU",
        "password": "secret",
    }
    client.post("/register", json=target)

    resp = client.post(
        "/reject",
        json={"email": target["email"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_upload_students(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    login_resp = client.post("/login", json={"email": "admin@example.com", "password": "admin123"})
    token = login_resp.json()["token"]

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [0.0, 0.1]})]

    def fake_create(input, model):
        return FakeResp()

    stored = {}

    def fake_set(key, value):
        stored[key] = value

    def fake_create(input, model):
        return FakeResp()

    monkeypatch.setattr(main_app.client.embeddings, "create", fake_create)
    monkeypatch.setattr(main_app.redis_client, "set", fake_set)
    monkeypatch.setattr(main_app.redis_client, "exists", lambda key: False)

    csv_data = (
        "first_name,last_name,email,phone,education_level,skills,experience_summary,interests\n"
        "John,Doe,john@example.com,123,College,python,summary,coding\n"
        "Jane,Smith,jane@example.com,456,College,sql,summary2,data\n"
    )
    files = {"file": ("students.csv", csv_data, "text/csv")}
    resp = client.post("/students/upload", files=files, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 2
    assert len(stored) == 2

