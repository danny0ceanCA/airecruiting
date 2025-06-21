import os
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "test")

from fastapi.testclient import TestClient
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
from app.main import app, init_default_admin

client = TestClient(app)


def setup_module():
    main_app.redis_client.flushdb()
    init_default_admin()


def login_admin():
    resp = client.post("/login", json={"email": "admin@example.com", "password": "admin123"})
    return resp.json()["token"]


def test_create_job_and_match(monkeypatch):
    token = login_admin()

    # fake redis store
    store = {}

    def fake_set(key, value):
        store[key] = value

    def fake_get(key):
        return store.get(key)

    def fake_exists(key):
        return key in store

    def fake_scan_iter(pattern="*"):
        for k in list(store.keys()):
            yield k

    monkeypatch.setattr(main_app.redis_client, "set", fake_set)
    monkeypatch.setattr(main_app.redis_client, "get", fake_get)
    monkeypatch.setattr(main_app.redis_client, "exists", fake_exists)
    monkeypatch.setattr(main_app.redis_client, "scan_iter", fake_scan_iter)

    class FakeResp:
        def __init__(self, emb):
            self.data = [type("obj", (), {"embedding": emb})]

    def fake_create(input, model):
        if "python" in input:
            return FakeResp([1.0, 0.0])
        elif "java" in input:
            return FakeResp([0.0, 1.0])
        return FakeResp([0.5, 0.5])

    monkeypatch.setattr(main_app.client.embeddings, "create", fake_create)

    # create two students
    s1 = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "phone": "123",
        "education_level": "College",
        "skills": ["python"],
        "experience_summary": "summary1",
        "interests": "A",
    }
    s2 = {
        "first_name": "Jane",
        "last_name": "Roe",
        "email": "jane@example.com",
        "phone": "456",
        "education_level": "College",
        "skills": ["java"],
        "experience_summary": "summary2",
        "interests": "B",
    }

    client.post("/students", json=s1, headers={"Authorization": f"Bearer {token}"})
    client.post("/students", json=s2, headers={"Authorization": f"Bearer {token}"})

    job = {
        "job_title": "Dev",
        "job_description": "Need python dev",
        "desired_skills": ["python"],
        "job_code": "ABC123",
        "source": "test",
        "rate_of_pay_range": "$1-$2",
    }

    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    job_code = resp.json()["job_code"]

    match_resp = client.post("/match", json={"job_code": job_code}, headers={"Authorization": f"Bearer {token}"})
    assert match_resp.status_code == 200
    data = match_resp.json()["matches"]
    assert len(data) == 2
    assert data[0]["email"] == "john@example.com"


def test_get_match_results_status(monkeypatch):
    token = login_admin()

    store = {}

    def fake_get(key):
        return store.get(key)

    def fake_set(key, value):
        store[key] = value

    monkeypatch.setattr(main_app.redis_client, "get", fake_get)
    monkeypatch.setattr(main_app.redis_client, "set", fake_set)

    job_code = "XYZ"
    store[f"match_results:{job_code}"] = json.dumps([
        {"email": "a@example.com", "score": 1.0}
    ])
    store[f"job:{job_code}"] = json.dumps({
        "job_code": job_code,
        "assigned_students": ["a@example.com"],
        "placed_students": []
    })

    resp = client.get(f"/match/{job_code}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()["matches"][0]
    assert data["status"] == "assigned"


def test_get_match_results_status_placed(monkeypatch):
    token = login_admin()

    store = {}

    def fake_get(key):
        return store.get(key)

    def fake_set(key, value):
        store[key] = value

    monkeypatch.setattr(main_app.redis_client, "get", fake_get)
    monkeypatch.setattr(main_app.redis_client, "set", fake_set)

    job_code = "XYZ2"
    store[f"match_results:{job_code}"] = json.dumps([
        {"email": "b@example.com", "score": 1.0}
    ])
    store[f"job:{job_code}"] = json.dumps({
        "job_code": job_code,
        "assigned_students": [],
        "placed_students": ["b@example.com"]
    })

    resp = client.get(f"/match/{job_code}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()["matches"][0]
    assert data["status"] == "placed"
