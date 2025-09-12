import os
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("GOOGLE_KEY", "test")

import os
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("GOOGLE_KEY", "test")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "admin123")

from fastapi.testclient import TestClient
import json
import app.main as main_app


class DummyRedis:
    def __init__(self):
        self.store = {}
        self.hashes = {}
        self.lists = {}
        self.sets = {}

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

    def scan(self, cursor=0, match=None, count=None):
        from fnmatch import fnmatch
        keys = [k for k in self.store.keys() if not match or fnmatch(k, match)]
        return 0, keys

    def incr(self, key, amount=1):
        val = int(self.store.get(key, 0)) + amount
        self.store[key] = val
        return val

    def mget(self, keys):
        return [self.store.get(k) for k in keys]

    def smembers(self, key):
        return self.sets.get(key, set())


    def scard(self, key):
        return len(self.smembers(key))


    def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    def srem(self, key, value):
        if key in self.sets:
            self.sets[key].discard(value)

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
        self.sets.clear()


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
        "license": "lvn",
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
        "license": "lvn",
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


def test_get_match_results_includes_missing_assigned(monkeypatch):
    token = login_admin()

    store = {}

    def fake_get(key):
        return store.get(key)

    def fake_set(key, value):
        store[key] = value

    monkeypatch.setattr(main_app.redis_client, "get", fake_get)
    monkeypatch.setattr(main_app.redis_client, "set", fake_set)

    job_code = "XYZ3"
    store[f"match_results:{job_code}"] = json.dumps([])
    store[f"job:{job_code}"] = json.dumps({
        "job_code": job_code,
        "assigned_students": ["a@example.com", "b@example.com"],
        "placed_students": []
    })

    store["user:a@example.com"] = json.dumps({"first_name": "A", "last_name": "One"})
    store["user:b@example.com"] = json.dumps({"first_name": "B", "last_name": "Two"})

    resp = client.get(f"/match/{job_code}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()["matches"]
    emails = {m["email"] for m in data}
    assert emails == {"a@example.com", "b@example.com"}
    assert all(m["status"] == "assigned" for m in data)
    names = {m["email"]: (m.get("first_name"), m.get("last_name")) for m in data}
    assert names["a@example.com"] == ("A", "One")
    assert names["b@example.com"] == ("B", "Two")


def test_get_match_results_includes_notes(monkeypatch):
    token = login_admin()

    store = {}

    def fake_get(key):
        return store.get(key)

    def fake_set(key, value):
        store[key] = value

    monkeypatch.setattr(main_app.redis_client, "get", fake_get)
    monkeypatch.setattr(main_app.redis_client, "set", fake_set)

    job_code = "XYZ4"
    store[f"match_results:{job_code}"] = json.dumps([
        {"email": "a@example.com", "score": 1.0}
    ])
    store[f"job:{job_code}"] = json.dumps({
        "job_code": job_code,
        "assigned_students": [],
        "placed_students": [],
        "rejected_students": [],
        "student_notes": {"a@example.com": [{"text": "hi"}]}
    })

    resp = client.get(f"/match/{job_code}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()["matches"][0]
    assert data["notes"][0]["text"] == "hi"
    assert data["note"] == "hi"


def test_get_match_results_no_duplicate_emails(monkeypatch):
    token = login_admin()

    store = {}

    def fake_get(key):
        return store.get(key)

    def fake_set(key, value):
        store[key] = value

    monkeypatch.setattr(main_app.redis_client, "get", fake_get)
    monkeypatch.setattr(main_app.redis_client, "set", fake_set)

    job_code = "XYZ5"
    store[f"match_results:{job_code}"] = json.dumps([
        {"email": "dup@example.com", "score": 1.0},
        {"email": "dup@example.com", "score": 2.0},
    ])
    store[f"job:{job_code}"] = json.dumps({
        "job_code": job_code,
        "assigned_students": [],
        "placed_students": [],
    })

    resp = client.get(f"/match/{job_code}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()["matches"]
    emails = [m["email"] for m in data]
    assert emails == ["dup@example.com"]
    assert len(emails) == len(set(emails))


def test_match_filters_by_license(monkeypatch):
    token = login_admin()

    class FakeResp:
        def __init__(self, emb):
            self.data = [type("obj", (object,), {"embedding": emb})]

    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 10.0)
    monkeypatch.setattr(main_app.client.embeddings, "create", lambda input, model: FakeResp([1.0, 0.0]))

    s1 = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john2@example.com",
        "phone": "123",
        "license": "lvn",
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
        "email": "jane2@example.com",
        "phone": "456",
        "license": "ma",
        "skills": ["python"],
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
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "required_license": "lvn",
    }

    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    job_code = resp.json()["job_code"]

    match_resp = client.post("/match", json={"job_code": job_code}, headers={"Authorization": f"Bearer {token}"})
    assert match_resp.status_code == 200
    data = match_resp.json()["matches"]
    assert len(data) == 1
    assert data[0]["email"] == "john2@example.com"


def test_license_label_vs_code_matching(monkeypatch):
    token = login_admin()

    class FakeResp:
        def __init__(self, emb):
            self.data = [type("obj", (object,), {"embedding": emb})]

    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 10.0)
    monkeypatch.setattr(main_app.client.embeddings, "create", lambda input, model: FakeResp([1.0, 0.0]))

    s_label = {
        "first_name": "Label",
        "last_name": "User",
        "email": "label@example.com",
        "phone": "123",
        "license": "Medical Assistant",
        "skills": ["alpha"],
        "experience_summary": "summary",
        "interests": "A",
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 100.0,
    }
    resp = client.post("/students", json=s_label, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    skey = main_app.resolve_student_key("label@example.com")
    stored = json.loads(main_app.redis_client.get(skey))
    assert stored["license"] == "ma"

    job_code_req = {
        "job_title": "Job1",
        "job_description": "desc",
        "desired_skills": ["alpha"],
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "required_license": "ma",
    }
    resp = client.post("/jobs", json=job_code_req, headers={"Authorization": f"Bearer {token}"})
    job_code = resp.json()["job_code"]
    match_resp = client.post("/match", json={"job_code": job_code}, headers={"Authorization": f"Bearer {token}"})
    assert any(m["email"] == "label@example.com" for m in match_resp.json()["matches"])

    s_code = {
        "first_name": "Code",
        "last_name": "User",
        "email": "code@example.com",
        "phone": "456",
        "license": "ma",
        "skills": ["beta"],
        "experience_summary": "summary",
        "interests": "B",
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 100.0,
    }
    resp = client.post("/students", json=s_code, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    job_label_req = {
        "job_title": "Job2",
        "job_description": "desc",
        "desired_skills": ["beta"],
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "required_license": "Medical Assistant",
    }
    resp = client.post("/jobs", json=job_label_req, headers={"Authorization": f"Bearer {token}"})
    job_code2 = resp.json()["job_code"]
    stored_job = json.loads(main_app.redis_client.get(f"job:{job_code2}"))
    assert stored_job["required_license"] == "ma"
    match_resp2 = client.post("/match", json={"job_code": job_code2}, headers={"Authorization": f"Bearer {token}"})
    assert any(m["email"] == "code@example.com" for m in match_resp2.json()["matches"])


def test_update_job_with_corrupted_data():
    main_app.redis_client.flushdb()
    init_default_admin()
    token = login_admin()
    job_code = "CORRUPT1"
    main_app.redis_client.set(f"job:{job_code}", "not-json")
    resp = client.put(
        f"/jobs/{job_code}",
        json={"job_title": "New"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Malformed job record"


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
        "license": "lvn",
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
        "license": "lvn",
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
        "license": "lvn",
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
        "license": "lvn",
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
        "license": "lvn",
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
        "license": "lvn",
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


def test_match_limit_ignores_assigned_students(monkeypatch):
    token = login_admin()

    class FakeResp:
        def __init__(self, emb):
            self.data = [type("obj", (), {"embedding": emb})]

    monkeypatch.setattr(
        main_app.client.embeddings,
        "create",
        lambda *a, **k: FakeResp([1.0, 0.0]),
    )
    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 1.0)

    students = []
    for i in range(13):
        stu = {
            "first_name": "Stu",
            "last_name": str(i),
            "email": f"s{i}@example.com",
            "phone": "1",
            "license": "ma",
            "skills": ["python"],
            "experience_summary": "s",
            "interests": "i",
            "city": "c",
            "state": "s",
            "lat": 0.0,
            "lng": 0.0,
            "max_travel": 10.0,
            "school_code": "1001",
        }
        client.post("/students", json=stu, headers={"Authorization": f"Bearer {token}"})
        students.append(stu)

    job = {
        "job_title": "Dev",
        "job_description": "desc",
        "desired_skills": ["python"],
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
    }
    job_code = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"}).json()["job_code"]

    for stu in students[:3]:
        client.post(
            "/assign",
            json={"job_code": job_code, "student_email": stu["email"]},
            headers={"Authorization": f"Bearer {token}"},
        )

    resp = client.post("/match", json={"job_code": job_code}, headers={"Authorization": f"Bearer {token}"})
    data = resp.json()["matches"]
    assert len(data) == 10
    assigned_emails = {s["email"] for s in students[:3]}
    assert all(m["email"] not in assigned_emails for m in data)


def test_recruiter_job_source_autopopulated(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    recruiter = {
        "email": "rec2@example.com",
        "first_name": "Rec",
        "last_name": "R",
        "school_code": "1001",
        "password": "pw",
        "role": "recruiter",
    }
    client.post("/register", json=recruiter)
    rk = f"user:{recruiter['email']}"
    rdata = json.loads(main_app.redis_client.get(rk))
    rdata["approved"] = True
    rdata["role"] = "recruiter"
    main_app.redis_client.set(rk, json.dumps(rdata))
    token = client.post(
        "/login",
        json={"email": recruiter["email"], "password": recruiter["password"]},
    ).json()["token"]

    job = {
        "job_title": "Dev",
        "job_description": "desc",
        "desired_skills": ["python"],
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
    }
    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    job_code = resp.json()["job_code"]
    stored = json.loads(main_app.redis_client.get(f"job:{job_code}"))
    assert stored["source"] == "Unitek-Sacramento"


def test_reject_assigned(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [1.0]})]

    monkeypatch.setattr(main_app.client.embeddings, "create", lambda *a, **k: FakeResp())
    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 1.0)

    token = login_admin()

    student = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "phone": "123",
        "license": "lvn",
        "skills": ["python"],
        "experience_summary": "s",
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
        "job_description": "desc",
        "desired_skills": ["python"],
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
    }
    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"})
    job_code = resp.json()["job_code"]

    assign_note = "initial note"
    client.post(
        "/assign",
        json={"student_email": student["email"], "job_code": job_code, "note": assign_note},
        headers={"Authorization": f"Bearer {token}"},
    )

    stored = json.loads(main_app.redis_client.get(f"job:{job_code}"))
    notes = stored.get("student_notes", {}).get(student["email"])
    assert notes[-1]["text"] == assign_note

    note = "not a fit"
    r = client.post(
        "/reject-assigned",
        json={"job_code": job_code, "student_email": student["email"], "note": note},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200

    stored = json.loads(main_app.redis_client.get(f"job:{job_code}"))
    assert student["email"] not in stored.get("assigned_students", [])
    assert student["email"] in stored.get("rejected_students", [])
    notes = stored.get("student_notes", {}).get(student["email"])
    assert notes[-1]["text"] == note

    resp = client.get("/students/by-school", headers={"Authorization": f"Bearer {token}"})
    data = resp.json()["students"][0]
    assert data["assigned_job_count"] == 1
    assert "assigned_jobs" not in data
    jobs_resp = client.get(
        f"/students/{student['email']}/jobs",
        headers={"Authorization": f"Bearer {token}"},
    )
    entry = next(j for j in jobs_resp.json()["jobs"] if j["job_code"] == job_code)
    assert entry["status"] == "rejected"
    assert entry["notes"][-1]["text"] == note
    assert "posted_by" in entry


def test_student_note_school_code_fallback():
    main_app.redis_client.flushdb()
    init_default_admin()

    recruiter = {
        "email": "recruiter@example.com",
        "first_name": "Rec",
        "last_name": "R",
        "school_code": "1001",
        "password": "pw",
        "role": "recruiter",
    }
    client.post("/register", json=recruiter)
    ck = f"user:{recruiter['email']}"
    cdata = json.loads(main_app.redis_client.get(ck))
    cdata["approved"] = True
    cdata["role"] = "recruiter"
    main_app.redis_client.set(ck, json.dumps(cdata))
    token = client.post(
        "/login", json={"email": recruiter["email"], "password": recruiter["password"]}
    ).json()["token"]

    job = {
        "job_title": "Dev",
        "job_description": "desc",
        "desired_skills": ["python"],
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
    }
    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"})
    job_code = resp.json()["job_code"]

    student = {
        "first_name": "Stu",
        "last_name": "Dent",
        "email": "student@example.com",
        "phone": "123",
        "license": "ma",
        "skills": ["python"],
        "experience_summary": "s",
        "interests": "i",
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 10.0,
        "school_code": "1001",
        "institutional_code": "1001",
        "student_id": "stu1",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )

    client.post(
        "/assign",
        json={"student_email": student["email"], "job_code": job_code},
        headers={"Authorization": f"Bearer {token}"},
    )

    note = "hello"
    admin_token = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    ).json()["token"]
    r = client.post(
        "/student-note",
        json={"job_code": job_code, "student_email": student["email"], "note": note},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200

    stored = json.loads(main_app.redis_client.get(f"job:{job_code}"))
    notes = stored.get("student_notes", {}).get(student["email"])
    assert notes[-1]["text"] == note

    resp = client.get(
        "/students/by-school", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    data = resp.json()["students"]
    stu = next(s for s in data if s["email"] == student["email"])
    assert stu["assigned_job_count"] == 1
    assert "assigned_jobs" not in stu
    jobs_resp = client.get(
        f"/students/{student['email']}/jobs",
        headers={"Authorization": f"Bearer {token}"},
    )
    entry = next(j for j in jobs_resp.json()["jobs"] if j["job_code"] == job_code)
    assert entry["notes"][-1]["text"] == note
    assert "posted_by" in entry


def test_assign_note_persists_on_reject(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [1.0]})]

    monkeypatch.setattr(main_app.client.embeddings, "create", lambda *a, **k: FakeResp())
    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 1.0)

    token = login_admin()

    student = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "phone": "123",
        "license": "lvn",
        "skills": ["python"],
        "experience_summary": "s",
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
        "job_description": "desc",
        "desired_skills": ["python"],
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
    }
    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"})
    job_code = resp.json()["job_code"]

    note = "keep this note"
    client.post(
        "/assign",
        json={"student_email": student["email"], "job_code": job_code, "note": note},
        headers={"Authorization": f"Bearer {token}"},
    )

    stored = json.loads(main_app.redis_client.get(f"job:{job_code}"))
    notes = stored.get("student_notes", {}).get(student["email"])
    assert notes[-1]["text"] == note

    resp = client.get("/students/by-school", headers={"Authorization": f"Bearer {token}"})
    data = resp.json()["students"][0]
    assert data["assigned_job_count"] == 1
    assert "assigned_jobs" not in data
    jobs_resp = client.get(
        f"/students/{student['email']}/jobs",
        headers={"Authorization": f"Bearer {token}"},
    )
    entry = next(j for j in jobs_resp.json()["jobs"] if j["job_code"] == job_code)
    assert entry["status"] == "assigned"
    assert entry["notes"][-1]["text"] == note
    assert "posted_by" in entry


def test_student_note_unassigned(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [1.0]})]

    monkeypatch.setattr(main_app.client.embeddings, "create", lambda *a, **k: FakeResp())
    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 1.0)

    token = login_admin()

    student = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "phone": "123",
        "license": "lvn",
        "skills": ["python"],
        "experience_summary": "s",
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
        "job_description": "desc",
        "desired_skills": ["python"],
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
    }
    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"})
    job_code = resp.json()["job_code"]

    note = "standalone note"
    r = client.post(
        "/student-note",
        json={"job_code": job_code, "student_email": student["email"], "note": note},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200

    stored = json.loads(main_app.redis_client.get(f"job:{job_code}"))
    notes = stored.get("student_notes", {}).get(student["email"])
    assert notes[-1]["text"] == note
    assert student["email"] not in stored.get("assigned_students", [])
    assert student["email"] not in stored.get("rejected_students", [])
    assert student["email"] not in stored.get("placed_students", [])
    assert student["email"] not in stored.get("uninterested_students", [])


def test_student_note_assigned(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [1.0]})]

    monkeypatch.setattr(main_app.client.embeddings, "create", lambda *a, **k: FakeResp())
    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 1.0)

    token = login_admin()

    student = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "phone": "123",
        "license": "lvn",
        "skills": ["python"],
        "experience_summary": "s",
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
        "job_description": "desc",
        "desired_skills": ["python"],
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
    }
    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"})
    job_code = resp.json()["job_code"]

    client.post(
        "/assign",
        json={"student_email": student["email"], "job_code": job_code},
        headers={"Authorization": f"Bearer {token}"},
    )

    note = "new note"
    r = client.post(
        "/student-note",
        json={"job_code": job_code, "student_email": student["email"], "note": note},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200

    stored = json.loads(main_app.redis_client.get(f"job:{job_code}"))
    assert student["email"] in stored.get("assigned_students", [])
    notes = stored.get("student_notes", {}).get(student["email"])
    assert notes[-1]["text"] == note

    resp = client.get("/students/by-school", headers={"Authorization": f"Bearer {token}"})
    data = resp.json()["students"][0]
    assert data["assigned_job_count"] == 1
    assert "assigned_jobs" not in data
    jobs_resp = client.get(
        f"/students/{student['email']}/jobs",
        headers={"Authorization": f"Bearer {token}"},
    )
    entry = next(j for j in jobs_resp.json()["jobs"] if j["job_code"] == job_code)
    assert entry["notes"][-1]["text"] == note
    assert entry["status"] == "assigned"
    assert "posted_by" in entry

    r = client.post(
        "/reject-assigned",
        json={"job_code": job_code, "student_email": student["email"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200

    stored = json.loads(main_app.redis_client.get(f"job:{job_code}"))
    notes = stored.get("student_notes", {}).get(student["email"])
    assert notes[-1]["text"] == note

    resp = client.get("/students/by-school", headers={"Authorization": f"Bearer {token}"})
    data = resp.json()["students"][0]
    assert data["assigned_job_count"] == 1
    assert "assigned_jobs" not in data
    jobs_resp = client.get(
        f"/students/{student['email']}/jobs",
        headers={"Authorization": f"Bearer {token}"},
    )
    entry = next(j for j in jobs_resp.json()["jobs"] if j["job_code"] == job_code)
    assert entry["status"] == "rejected"
    assert entry["notes"][-1]["text"] == note
    assert "posted_by" in entry


def test_student_note_multiple_posts_unassigned(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [1.0]})]

    monkeypatch.setattr(main_app.client.embeddings, "create", lambda *a, **k: FakeResp())
    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 1.0)

    token = login_admin()

    student = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "phone": "123",
        "license": "lvn",
        "skills": ["python"],
        "experience_summary": "s",
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
        "job_description": "desc",
        "desired_skills": ["python"],
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
    }
    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"})
    job_code = resp.json()["job_code"]

    note1 = "first note"
    note2 = "second note"
    client.post(
        "/student-note",
        json={"job_code": job_code, "student_email": student["email"], "note": note1},
        headers={"Authorization": f"Bearer {token}"},
    )
    client.post(
        "/student-note",
        json={"job_code": job_code, "student_email": student["email"], "note": note2},
        headers={"Authorization": f"Bearer {token}"},
    )

    stored = json.loads(main_app.redis_client.get(f"job:{job_code}"))
    notes = stored.get("student_notes", {}).get(student["email"])
    assert len(notes) == 2
    assert notes[0]["text"] == note1
    assert notes[-1]["text"] == note2


def test_recruiter_can_add_note_for_assigned_student():
    main_app.redis_client.flushdb()
    init_default_admin()

    recruiter = {
        "email": "rec@example.com",
        "first_name": "Rec",
        "last_name": "R",
        "school_code": "1001",
        "password": "pw",
        "role": "recruiter",
    }
    client.post("/register", json=recruiter)
    rk = f"user:{recruiter['email']}"
    rdata = json.loads(main_app.redis_client.get(rk))
    rdata["approved"] = True
    rdata["role"] = "recruiter"
    main_app.redis_client.set(rk, json.dumps(rdata))
    token = client.post(
        "/login", json={"email": recruiter["email"], "password": recruiter["password"]}
    ).json()["token"]

    student = {
        "first_name": "Stu",
        "last_name": "Dent",
        "email": "stu@example.com",
        "phone": "1",
        "license": "ma",
        "skills": ["python"],
        "experience_summary": "s",
        "interests": "i",
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 10.0,
        "school_code": "1001",
        "institutional_code": "1001",
        "student_id": "stu2",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )

    job = {
        "job_title": "Dev",
        "job_description": "desc",
        "desired_skills": ["python"],
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
    }
    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"})
    job_code = resp.json()["job_code"]

    client.post(
        "/assign",
        json={"student_email": student["email"], "job_code": job_code},
        headers={"Authorization": f"Bearer {token}"},
    )

    note = "follow up"
    r = client.post(
        "/student-note",
        json={"job_code": job_code, "student_email": student["email"], "note": note},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    stored = json.loads(main_app.redis_client.get(f"job:{job_code}"))
    notes = stored.get("student_notes", {}).get(student["email"])
    assert notes[-1]["text"] == note


def test_recruiter_note_forbidden_unassigned_or_unowned():
    main_app.redis_client.flushdb()
    init_default_admin()

    rec1 = {
        "email": "rec1@example.com",
        "first_name": "R1",
        "last_name": "One",
        "school_code": "1001",
        "password": "pw",
        "role": "recruiter",
    }
    rec2 = {
        "email": "rec2@example.com",
        "first_name": "R2",
        "last_name": "Two",
        "school_code": "1001",
        "password": "pw",
        "role": "recruiter",
    }
    for rec in (rec1, rec2):
        client.post("/register", json=rec)
        rk = f"user:{rec['email']}"
        rdata = json.loads(main_app.redis_client.get(rk))
        rdata["approved"] = True
        rdata["role"] = "recruiter"
        main_app.redis_client.set(rk, json.dumps(rdata))
    token1 = client.post(
        "/login", json={"email": rec1["email"], "password": rec1["password"]}
    ).json()["token"]
    token2 = client.post(
        "/login", json={"email": rec2["email"], "password": rec2["password"]}
    ).json()["token"]

    student1 = {
        "first_name": "Stu",
        "last_name": "One",
        "email": "s1@example.com",
        "phone": "1",
        "license": "ma",
        "skills": ["python"],
        "experience_summary": "s",
        "interests": "i",
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 10.0,
        "school_code": "1001",
        "institutional_code": "1001",
        "student_id": "s1",
    }
    student2 = {**student1, "email": "s2@example.com", "student_id": "s2"}
    main_app.persist_student_record(
        student1["email"], student1, student1["institutional_code"], student1["student_id"]
    )
    main_app.persist_student_record(
        student2["email"], student2, student2["institutional_code"], student2["student_id"]
    )

    job = {
        "job_title": "Dev",
        "job_description": "desc",
        "desired_skills": ["python"],
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
    }
    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token1}"})
    job_code = resp.json()["job_code"]

    client.post(
        "/assign",
        json={"student_email": student1["email"], "job_code": job_code},
        headers={"Authorization": f"Bearer {token1}"},
    )

    note = "check"
    r_unassigned = client.post(
        "/student-note",
        json={"job_code": job_code, "student_email": student2["email"], "note": note},
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert r_unassigned.status_code == 403

    r_unowned = client.post(
        "/student-note",
        json={"job_code": job_code, "student_email": student1["email"], "note": note},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert r_unowned.status_code == 403


def test_recruiter_cannot_modify_unowned_job():
    main_app.redis_client.flushdb()
    init_default_admin()

    rec1 = {
        "email": "rec1@example.com",
        "first_name": "R1",
        "last_name": "One",
        "school_code": "1001",
        "password": "pw",
        "role": "recruiter",
    }
    rec2 = {
        "email": "rec2@example.com",
        "first_name": "R2",
        "last_name": "Two",
        "school_code": "1001",
        "password": "pw",
        "role": "recruiter",
    }
    for rec in (rec1, rec2):
        client.post("/register", json=rec)
        rk = f"user:{rec['email']}"
        rdata = json.loads(main_app.redis_client.get(rk))
        rdata["approved"] = True
        rdata["role"] = "recruiter"
        main_app.redis_client.set(rk, json.dumps(rdata))
    token1 = client.post(
        "/login", json={"email": rec1["email"], "password": rec1["password"]}
    ).json()["token"]
    token2 = client.post(
        "/login", json={"email": rec2["email"], "password": rec2["password"]}
    ).json()["token"]

    student = {
        "first_name": "Stu",
        "last_name": "Dent",
        "email": "stu@example.com",
        "phone": "1",
        "license": "ma",
        "skills": ["python"],
        "experience_summary": "s",
        "interests": "i",
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 10.0,
        "school_code": "1001",
        "institutional_code": "1001",
        "student_id": "stu3",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )

    job = {
        "job_title": "Dev",
        "job_description": "desc",
        "desired_skills": ["python"],
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
    }
    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token1}"})
    job_code = resp.json()["job_code"]

    r_assign = client.post(
        "/assign",
        json={"student_email": student["email"], "job_code": job_code},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert r_assign.status_code == 403

    client.post(
        "/assign",
        json={"student_email": student["email"], "job_code": job_code},
        headers={"Authorization": f"Bearer {token1}"},
    )

    r_reject = client.post(
        "/reject-assigned",
        json={"student_email": student["email"], "job_code": job_code},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert r_reject.status_code == 403


def test_student_note_multiple_posts_assigned(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [1.0]})]

    monkeypatch.setattr(main_app.client.embeddings, "create", lambda *a, **k: FakeResp())
    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 1.0)

    token = login_admin()

    student = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "phone": "123",
        "license": "lvn",
        "skills": ["python"],
        "experience_summary": "s",
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
        "job_description": "desc",
        "desired_skills": ["python"],
        "min_pay": 1.0,
        "max_pay": 2.0,
        "city": "c",
        "state": "s",
        "lat": 0.0,
        "lng": 0.0,
    }
    resp = client.post("/jobs", json=job, headers={"Authorization": f"Bearer {token}"})
    job_code = resp.json()["job_code"]

    client.post(
        "/assign",
        json={"student_email": student["email"], "job_code": job_code},
        headers={"Authorization": f"Bearer {token}"},
    )

    note1 = "first note"
    note2 = "second note"
    client.post(
        "/student-note",
        json={"job_code": job_code, "student_email": student["email"], "note": note1},
        headers={"Authorization": f"Bearer {token}"},
    )
    client.post(
        "/student-note",
        json={"job_code": job_code, "student_email": student["email"], "note": note2},
        headers={"Authorization": f"Bearer {token}"},
    )

    stored = json.loads(main_app.redis_client.get(f"job:{job_code}"))
    notes = stored.get("student_notes", {}).get(student["email"])
    assert len(notes) == 2
    assert notes[0]["text"] == note1
    assert notes[-1]["text"] == note2

