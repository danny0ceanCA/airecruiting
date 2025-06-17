from fastapi.testclient import TestClient
from app.main import app, users, init_default_admin
import app.main as main_app

client = TestClient(app)


def setup_module():
    users.clear()
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
