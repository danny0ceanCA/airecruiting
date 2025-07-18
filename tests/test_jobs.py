import os
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("GOOGLE_KEY", "test")

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

    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 10.0)

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
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 100.0,
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
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 100.0,
    }

    client.post("/students", json=s1, headers={"Authorization": f"Bearer {token}"})
    client.post("/students", json=s2, headers={"Authorization": f"Bearer {token}"})

    job = {
        "job_title": "Dev",
        "job_description": "Need python dev",
        "desired_skills": ["python"],
        "job_code": "ABC123",
        "source": "test",
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
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


def test_match_respects_travel_distance(monkeypatch):
    token = login_admin()

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
        return FakeResp([1.0, 0.0])

    monkeypatch.setattr(main_app.client.embeddings, "create", fake_create)

    # distance always 150 miles
    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 150.0)

    s1 = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "phone": "123",
        "education_level": "College",
        "skills": ["python"],
        "experience_summary": "summary1",
        "interests": "A",
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 200.0,
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
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 100.0,
    }

    client.post("/students", json=s1, headers={"Authorization": f"Bearer {token}"})
    client.post("/students", json=s2, headers={"Authorization": f"Bearer {token}"})

    job = {
        "job_title": "Dev",
        "job_description": "Need python dev",
        "desired_skills": ["python"],
        "job_code": "ABC123",
        "source": "test",
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
    }

    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"})
    job_code = resp.json()["job_code"]

    match_resp = client.post("/match", json={"job_code": job_code}, headers={"Authorization": f"Bearer {token}"})
    data = match_resp.json()["matches"]
    assert len(data) == 1
    assert data[0]["email"] == "john@example.com"


def test_match_ignores_label_changes(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    class FakeResp:
        def __init__(self, emb):
            self.data = [type("obj", (), {"embedding": emb})]

    def fake_create(input, model):
        return FakeResp([1.0])

    monkeypatch.setattr(main_app.client.embeddings, "create", fake_create)
    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 1.0)

    # register career user
    career = {
        "email": "career@example.com",
        "first_name": "Car",
        "last_name": "Eer",
        "school_code": "1001",
        "password": "pw",
        "role": "career",
    }
    client.post("/register", json=career)
    ck = f"user:{career['email']}"
    cdata = json.loads(main_app.redis_client.get(ck))
    cdata["approved"] = True
    cdata["role"] = "career"
    main_app.redis_client.set(ck, json.dumps(cdata))
    career_token = client.post(
        "/login", json={"email": career["email"], "password": career["password"]}
    ).json()["token"]

    # register applicant user
    applicant = {
        "email": "app@example.com",
        "first_name": "App",
        "last_name": "L",
        "school_code": "1001",
        "password": "pw",
        "role": "applicant",
    }
    client.post("/register", json=applicant)
    ak = f"user:{applicant['email']}"
    adata = json.loads(main_app.redis_client.get(ak))
    adata["approved"] = True
    adata["role"] = "applicant"
    main_app.redis_client.set(ak, json.dumps(adata))
    applicant_token = client.post(
        "/login", json={"email": applicant["email"], "password": applicant["password"]}
    ).json()["token"]

    # change school label
    admin_token = login_admin()
    client.put(
        "/admin/school-codes/1001",
        json={"label": "New Label"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    student_profile = {
        "first_name": "Stu",
        "last_name": "D",
        "email": applicant["email"],
        "phone": "123",
        "education_level": "College",
        "skills": ["python"],
        "experience_summary": "exp",
        "interests": "int",
        "city": "C",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 50.0,
    }
    client.post(
        "/students",
        json=student_profile,
        headers={"Authorization": f"Bearer {applicant_token}"},
    )

    job = {
        "job_title": "Dev",
        "job_description": "Need python",
        "desired_skills": ["python"],
        "source": "x",
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "C",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
    }
    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {career_token}"})
    job_code = resp.json()["job_code"]

    match_resp = client.post(
        "/match", json={"job_code": job_code}, headers={"Authorization": f"Bearer {career_token}"}
    )
    assert match_resp.status_code == 200
    emails = [m["email"] for m in match_resp.json()["matches"]]
    assert applicant["email"] in emails


def test_match_includes_applicant_records_without_student(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [1.0]})]

    monkeypatch.setattr(main_app.client.embeddings, "create", lambda *a, **k: FakeResp())
    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 1.0)

    recruiter = {
        "email": "rec@example.com",
        "first_name": "Rec",
        "last_name": "R",
        "school_code": "1001",
        "password": "pw",
        "role": "career",
    }
    client.post("/register", json=recruiter)
    rk = f"user:{recruiter['email']}"
    rdata = json.loads(main_app.redis_client.get(rk))
    rdata["approved"] = True
    rdata["role"] = "career"
    main_app.redis_client.set(rk, json.dumps(rdata))
    recruiter_token = client.post(
        "/login", json={"email": recruiter["email"], "password": recruiter["password"]}
    ).json()["token"]

    applicant = {
        "email": "na@example.com",
        "first_name": "No",
        "last_name": "Student",
        "school_code": "1001",
        "password": "pw",
        "role": "applicant",
    }
    client.post("/register", json=applicant)
    ak = f"user:{applicant['email']}"
    adata = json.loads(main_app.redis_client.get(ak))
    adata["approved"] = True
    adata["role"] = "applicant"
    main_app.redis_client.set(ak, json.dumps(adata))
    client.post(
        "/login", json={"email": applicant["email"], "password": applicant["password"]}
    )

    job = {
        "job_title": "Dev",
        "job_description": "Need python",
        "desired_skills": ["python"],
        "source": "x",
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "C",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
    }
    resp = client.post(
        "/jobs", json=job, headers={"Authorization": f"Bearer {recruiter_token}"}
    )
    job_code = resp.json()["job_code"]

    match_resp = client.post(
        "/match", json={"job_code": job_code}, headers={"Authorization": f"Bearer {recruiter_token}"}
    )
    assert match_resp.status_code == 200
    emails = [m["email"] for m in match_resp.json()["matches"]]
    assert applicant["email"] in emails


def test_rematches_endpoint(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    class FakeResp:
        def __init__(self, emb):
            self.data = [type("obj", (), {"embedding": emb})]

    monkeypatch.setattr(main_app.client.embeddings, "create", lambda *a, **k: FakeResp([1.0]))
    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 1.0)

    token = login_admin()

    student = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "phone": "123",
        "education_level": "College",
        "skills": ["python"],
        "experience_summary": "summary",
        "interests": "i",
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 50.0,
    }

    client.post("/students", json=student, headers={"Authorization": f"Bearer {token}"})

    job = {
        "job_title": "Dev",
        "job_description": "need python",
        "desired_skills": ["python"],
        "source": "x",
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
    }
    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"})
    job_code = resp.json()["job_code"]

    client.post("/match", json={"job_code": job_code}, headers={"Authorization": f"Bearer {token}"})
    rematch_resp = client.post(f"/rematches/{job_code}", headers={"Authorization": f"Bearer {token}"})
    assert rematch_resp.status_code == 200
    assert main_app.redis_client.get("metrics:total_rematches") == 1


def test_not_interested_filters_out_student(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [1.0]})]

    monkeypatch.setattr(main_app.client.embeddings, "create", lambda *a, **k: FakeResp())
    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 1.0)

    token = login_admin()

    s1 = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "phone": "123",
        "education_level": "College",
        "skills": ["python"],
        "experience_summary": "s1",
        "interests": "i",
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 50.0,
    }

    s2 = {
        "first_name": "Jane",
        "last_name": "Roe",
        "email": "jane@example.com",
        "phone": "456",
        "education_level": "College",
        "skills": ["java"],
        "experience_summary": "s2",
        "interests": "i",
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 50.0,
    }

    client.post("/students", json=s1, headers={"Authorization": f"Bearer {token}"})
    client.post("/students", json=s2, headers={"Authorization": f"Bearer {token}"})

    job = {
        "job_title": "Dev",
        "job_description": "desc",
        "desired_skills": ["python"],
        "source": "x",
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
    }

    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"})
    job_code = resp.json()["job_code"]

    first = client.post("/match", json={"job_code": job_code}, headers={"Authorization": f"Bearer {token}"})
    assert len(first.json()["matches"]) == 2

    client.post(
        "/not-interested",
        json={"job_code": job_code, "student_email": s2["email"]},
        headers={"Authorization": f"Bearer {token}"},
    )

    second = client.post("/match", json={"job_code": job_code}, headers={"Authorization": f"Bearer {token}"})
    emails = [m["email"] for m in second.json()["matches"]]
    assert s2["email"] not in emails
    assert s1["email"] in emails

    stored = json.loads(main_app.redis_client.get(f"job:{job_code}"))
    assert s2["email"] in stored.get("uninterested_students", [])
