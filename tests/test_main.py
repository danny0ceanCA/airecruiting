import os
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("GOOGLE_KEY", "test")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "admin123")

from fastapi.testclient import TestClient
from jose import jwt
import json
import app.main as main_app
from datetime import datetime, timedelta


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
        self.hashes.clear()
        self.lists.clear()

    def hset(self, name, key, value):
        self.hashes.setdefault(name, {})[key] = value

    def hget(self, name, key):
        return self.hashes.get(name, {}).get(key)

    def rpush(self, name, value):
        self.lists.setdefault(name, []).append(value)

    def lindex(self, name, index):
        lst = self.lists.get(name, [])
        if index < 0:
            index += len(lst)
        if 0 <= index < len(lst):
            return lst[index]
        return None


main_app.redis_client = DummyRedis()
from app.main import app, JWT_SECRET, ALGORITHM, init_default_admin
import backend.app.main  # register additional routes

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


def test_junior_admin_exists():
    main_app.redis_client.flushdb()
    os.environ["JUNIOR_ADMIN_EMAIL"] = "junior@example.com"
    os.environ["JUNIOR_ADMIN_PASSWORD"] = "junior123"
    init_default_admin()
    raw = main_app.redis_client.get("user:junior@example.com")
    junior = json.loads(raw)
    assert junior is not None
    assert junior["role"] == "junior_admin"
    del os.environ["JUNIOR_ADMIN_EMAIL"]
    del os.environ["JUNIOR_ADMIN_PASSWORD"]


def test_applicant_registration_without_code():
    main_app.redis_client.flushdb()
    init_default_admin()
    user = {
        "email": "nocode@example.com",
        "first_name": "No",
        "last_name": "Code",
        "password": "pw",
        "role": "applicant",
    }
    resp = client.post("/register", json=user)
    assert resp.status_code == 200


def test_non_applicant_requires_code():
    main_app.redis_client.flushdb()
    init_default_admin()
    user = {
        "email": "career@example.com",
        "first_name": "Car",
        "last_name": "Eer",
        "password": "pw",
        "role": "career",
    }
    resp = client.post("/register", json=user)
    assert resp.status_code == 400


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
        "school_code": "1001",
        "password": "secret",
        "role": "applicant",
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
        json={"email": user_data["email"], "role": "career"},
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
    assert payload["role"] == "career"


def test_register_links_existing_student():
    main_app.redis_client.flushdb()
    init_default_admin()

    email = "stud@example.com"
    profile = {
        "email": email,
        "student_id": "1",
        "institution_code": "1001",
        "created_by": "career@example.com",
    }
    main_app.persist_student_record(email, profile, "1001", "1")

    user = {
        "email": email,
        "first_name": "Stu",
        "last_name": "Dent",
        "school_code": "1001",
        "password": "pw",
        "role": "applicant",
    }
    resp = client.post("/register", json=user)
    assert resp.status_code == 200
    skey = main_app.resolve_student_key(email)
    stored = json.loads(main_app.redis_client.get(skey))
    assert stored.get("registered_by") == main_app.user_key(email)


def test_non_admin_cannot_approve():
    main_app.redis_client.flushdb()

    # Create regular user who will attempt approval
    user1 = {
        "email": "user1@example.com",
        "first_name": "User",
        "last_name": "One",
        "school_code": "1001",
        "password": "pass1",
        "role": "applicant",
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
        "school_code": "1001",
        "password": "pass2",
        "role": "applicant",
    }
    client.post("/register", json=target)

    resp = client.post(
        "/approve",
        json={"email": target["email"], "role": "career"},
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
        "school_code": "1001",
        "password": "pass1",
        "role": "applicant",
    }
    u2 = {
        "email": "pend2@example.com",
        "first_name": "Pending",
        "last_name": "Two",
        "school_code": "1001",
        "password": "pass2",
        "role": "applicant",
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
        "school_code": "1001",
        "password": "secret",
        "role": "applicant",
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
        "school_code": "1001",
        "password": "pwd",
        "role": "applicant",
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
        "school_code": "1001",
        "password": "pass",
        "role": "applicant",
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
        "school_code": "1001",
        "password": "secret",
        "role": "applicant",
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
        "first_name,last_name,email,phone,license,skills,experience_summary,interests,city,state,lat,lng,max_travel\n"
        "John,Doe,john@example.com,123,College,python,summary,coding,City,ST,0,0,100\n"
        "Jane,Smith,jane@example.com,456,College,sql,summary2,data,City,ST,0,0,100\n"
    )
    files = {"file": ("students.csv", csv_data, "text/csv")}
    resp = client.post("/students/upload", files=files, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 2
    assert len(stored) == 2


def test_student_creation_records_metadata(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    login_resp = client.post("/login", json={"email": "admin@example.com", "password": "admin123"})
    token = login_resp.json()["token"]

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [0.0, 0.1]})]

    def fake_create(input, model):
        return FakeResp()

    monkeypatch.setattr(main_app.client.embeddings, "create", fake_create)
    monkeypatch.setattr(main_app, "ensure_index", lambda dim: None)
    monkeypatch.setattr(main_app, "rebuild_vector_index", lambda: None)
    main_app.vector_index = None

    profile = {
        "first_name": "Stu",
        "last_name": "Dent",
        "email": "stud@example.com",
        "phone": "123",
        "license": "lvn",
        "skills": ["python"],
        "experience_summary": "summary",
        "interests": "coding",
        "city": "Town",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 10,
    }

    resp = client.post("/students", json=profile, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    skey = main_app.resolve_student_key(profile["email"])
    raw = main_app.redis_client.get(skey)
    stored = json.loads(raw)
    assert stored["created_by"] == "admin@example.com"
    assert "created_at" in stored
    datetime.fromisoformat(stored["created_at"])

    updated = profile.copy()
    updated["city"] = "NewCity"
    resp2 = client.put(
        f"/students/{profile['email']}",
        json=updated,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200
    raw2 = main_app.redis_client.get(skey)
    stored2 = json.loads(raw2)
    assert stored2["city"] == "NewCity"
    assert stored2["created_by"] == "admin@example.com"
    assert stored2["created_at"] == stored["created_at"]


def test_create_student_returns_existing_for_same_user(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    email = "stud@example.com"
    profile = {
        "email": email,
        "student_id": "1",
        "institution_code": "1001",
        "created_by": "career@example.com",
    }
    main_app.persist_student_record(email, profile, "1001", "1")

    user = {
        "email": email,
        "first_name": "Stu",
        "last_name": "Dent",
        "password": "pw",
        "role": "applicant",
    }
    client.post("/register", json=user)

    key = main_app.user_key(email)
    udata = json.loads(main_app.redis_client.get(key))
    udata["approved"] = True
    main_app.redis_client.set(key, json.dumps(udata))
    login = client.post("/login", json={"email": email, "password": "pw"})
    token = login.json()["token"]

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [0.0, 0.1]})]

    def fake_create(input, model):
        return FakeResp()

    monkeypatch.setattr(main_app.client.embeddings, "create", fake_create)
    monkeypatch.setattr(main_app, "ensure_index", lambda dim: None)
    monkeypatch.setattr(main_app, "rebuild_vector_index", lambda: None)
    main_app.vector_index = None

    body = {
        "first_name": "Stu",
        "last_name": "Dent",
        "email": email,
        "phone": "123",
        "license": "lvn",
        "skills": [],
        "experience_summary": "",
        "interests": "",
        "city": "Town",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 10,
    }
    resp = client.post(
        "/students",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    returned = resp.json()["student"]
    assert returned["email"] == email


def test_metrics_endpoint():
    main_app.redis_client.flushdb()
    init_default_admin()

    # Seed some users
    u1 = {
        "first_name": "A",
        "last_name": "B",
        "school_code": "1001",
        "password": "p",
        "role": "user",
        "approved": True,
        "rejected": False,
    }
    main_app.redis_client.set("user:user1@example.com", json.dumps(u1))

    u2 = {**u1, "approved": False, "rejected": False}
    main_app.redis_client.set("user:user2@example.com", json.dumps(u2))

    u3 = {**u1, "approved": False, "rejected": True}
    main_app.redis_client.set("user:user3@example.com", json.dumps(u3))

    # Seed student profiles
    main_app.redis_client.set("stud1@example.com", json.dumps({"email": "stud1@example.com"}))
    main_app.redis_client.set("stud2@example.com", json.dumps({"email": "stud2@example.com"}))

    # Seed jobs
    main_app.redis_client.set("job:abc", json.dumps({"job_code": "abc"}))

    # Seed metrics values
    main_app.redis_client.set("metrics:total_matches", 2)
    main_app.redis_client.set("metrics:total_match_score", 5.0)
    main_app.redis_client.set("metrics:last_match_timestamp", "2020-01-01T00:00:00")
    main_app.redis_client.set("metrics:total_placements", 2)
    main_app.redis_client.set("metrics:total_rematches", 1)
    main_app.redis_client.set("metrics:sum_time_to_place", 5.0)
    main_app.redis_client.set("metrics:licensed:A", 1)
    main_app.redis_client.set("metrics:licensed:B", 2)

    login_resp = client.post("/login", json={"email": "admin@example.com", "password": "admin123"})
    token = login_resp.json()["token"]

    resp = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_users"] == 4  # including default admin
    assert data["approved_users"] == 2  # admin + u1
    assert data["rejected_users"] == 1
    assert data["pending_registrations"] == 1
    assert data["total_student_profiles"] == 2
    assert data["total_jobs_posted"] == 1
    assert data["total_matches"] == 2
    assert abs(data["average_match_score"] - 2.5) < 1e-6
    assert data["placement_rate"] == 1
    assert abs(data["avg_time_to_placement_days"] - 2.5) < 1e-6
    assert data["license_breakdown"] == {"A": 1, "B": 2}
    assert data["rematch_rate"] == 0.5


def test_student_load_time_metric():
    main_app.redis_client = DummyRedis()
    main_app.redis_client.flushdb()
    init_default_admin()

    login_resp = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    )
    token = login_resp.json()["token"]

    resp = client.post(
        "/metrics/student-load-time",
        json={"role": "admin", "duration": 123.4},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    if hasattr(main_app.redis_client, "lrange"):
        entries = main_app.redis_client.lrange("metrics:student_load_time", 0, -1) or []
    else:
        entries = main_app.redis_client.lists.get("metrics:student_load_time", [])
    assert len(entries) == 1
    record = json.loads(entries[0])
    assert record["role"] == "admin"
    assert record["duration"] == 123.4


def test_admin_reset_jobs():
    main_app.redis_client.flushdb()
    init_default_admin()

    # Seed some job and match data
    main_app.redis_client.set("job:one", json.dumps({"job_code": "one"}))
    main_app.redis_client.set("match_results:one", json.dumps([]))

    login_resp = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    )
    token = login_resp.json()["token"]

    resp = client.delete(
        "/admin/reset-jobs", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert "Deleted" in resp.json()["message"]

    # verify cleanup
    assert list(main_app.redis_client.scan_iter("job:*")) == []
    assert list(main_app.redis_client.scan_iter("match_results:*")) == []


def test_students_all_admin_access():
    main_app.redis_client.flushdb()
    init_default_admin()

    # Seed some students
    s1 = {
        "first_name": "One",
        "last_name": "A",
        "email": "one@example.com",
        "license": "lvn",
        "city": "City1",
        "state": "ST",
        "institutional_code": "1001",
        "student_id": "one",
    }
    s2 = {
        "first_name": "Two",
        "last_name": "B",
        "email": "two@example.com",
        "license": "ma",
        "city": "City2",
        "state": "ST",
        "institutional_code": "1001",
        "student_id": "two",
    }
    main_app.persist_student_record(
        s1["email"], s1, s1["institutional_code"], s1["student_id"]
    )
    main_app.persist_student_record(
        s2["email"], s2, s2["institutional_code"], s2["student_id"]
    )

    login_resp = client.post("/login", json={"email": "admin@example.com", "password": "admin123"})
    token = login_resp.json()["token"]

    resp = client.get("/students/all", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()["students"]
    emails = {s["email"] for s in data}
    assert {"one@example.com", "two@example.com"} <= emails
    student_map = {s["email"]: s for s in data}
    assert student_map["one@example.com"]["city"] == "City1"
    assert student_map["one@example.com"]["state"] == "ST"
    assert student_map["two@example.com"]["city"] == "City2"
    assert student_map["two@example.com"]["state"] == "ST"


def test_students_all_forbidden_for_non_admin():
    main_app.redis_client.flushdb()
    init_default_admin()

    user = {
        "email": "user@example.com",
        "first_name": "User",
        "last_name": "Test",
        "school_code": "1001",
        "password": "pass",
        "role": "applicant",
    }
    client.post("/register", json=user)
    key = f"user:{user['email']}"
    data = json.loads(main_app.redis_client.get(key))
    data["approved"] = True
    main_app.redis_client.set(key, json.dumps(data))
    login_resp = client.post("/login", json={"email": user["email"], "password": user["password"]})
    token = login_resp.json()["token"]

    resp = client.get("/students/all", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_students_all_job_mapping(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    # Seed students
    s1 = {
        "first_name": "Alpha",
        "last_name": "A",
        "email": "a@example.com",
        "institutional_code": "1001",
        "student_id": "a1",
    }
    s2 = {
        "first_name": "Beta",
        "last_name": "B",
        "email": "b@example.com",
        "institutional_code": "1001",
        "student_id": "b1",
    }
    main_app.persist_student_record(
        s1["email"], s1, s1["institutional_code"], s1["student_id"]
    )
    main_app.persist_student_record(
        s2["email"], s2, s2["institutional_code"], s2["student_id"]
    )

    # Seed jobs referencing students
    jobs = [
        {"job_code": "J1", "assigned_students": [s1["email"]]},
        {"job_code": "J2", "assigned_students": [s2["email"]]},
        {"job_code": "J3", "assigned_students": [s1["email"], s2["email"]]},
        {"job_code": "J4"},  # unrelated job
    ]
    for job in jobs:
        main_app.redis_client.set(f"job:{job['job_code']}", json.dumps(job))

    calls = []

    def fake_track(email, code):
        calls.append((email, code))
        return {"email_sent": None, "first_open": None, "clicked": False}

    monkeypatch.setattr(main_app, "_tracking_stats", fake_track)

    token = client.post("/login", json={"email": "admin@example.com", "password": "admin123"}).json()["token"]

    resp = client.get("/students/all", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = {s["email"]: s for s in resp.json()["students"]}
    assert {"J1", "J3"} == {j["job_code"] for j in data[s1["email"]]["assigned_jobs"]}
    assert {"J2", "J3"} == {j["job_code"] for j in data[s2["email"]]["assigned_jobs"]}
    # Ensure tracking stats were only computed for relevant pairs
    assert set(calls) == {
        (s1["email"], "J1"),
        (s1["email"], "J3"),
        (s2["email"], "J2"),
        (s2["email"], "J3"),
    }


def test_update_student(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    login_resp = client.post("/login", json={"email": "admin@example.com", "password": "admin123"})
    token = login_resp.json()["token"]

    existing = {
        "first_name": "Old",
        "last_name": "Name",
        "email": "stud@example.com",
        "phone": "000",
        "license": "ma",
        "skills": ["c"],
        "experience_summary": "old",
        "interests": "old",
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 100.0,
        "embedding": [0.0, 0.0],
        "school_code": "SC1",
        "institutional_code": "SC1",
        "student_id": "stud1",
    }
    main_app.persist_student_record(
        existing["email"], existing, existing["institutional_code"], existing["student_id"]
    )

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [1.0, 2.0]})]

    def fake_create(input, model):
        return FakeResp()

    monkeypatch.setattr(main_app.client.embeddings, "create", fake_create)

    updated = {
        "first_name": "New",
        "last_name": "Name",
        "email": "stud@example.com",
        "phone": "111",
        "license": "lvn",
        "skills": ["python"],
        "experience_summary": "new summary",
        "interests": "coding",
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 100.0,
    }

    resp = client.put(
        "/students/stud@example.com",
        json=updated,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Student updated successfully"

    skey = main_app.resolve_student_key("stud@example.com")
    saved = json.loads(main_app.redis_client.get(skey))
    assert saved["first_name"] == "New"
    assert saved["license"] == "lvn"
    assert saved["embedding"] == [1.0, 2.0]
    assert saved["school_code"] == "SC1"


def test_generate_description(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    # Seed job and student
    student = {
        "first_name": "Stud",
        "last_name": "S",
        "skills": ["python"],
        "email": "stud@example.com",
        "institutional_code": "1001",
        "student_id": "stud2",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.redis_client.set(
        "job:code1",
        json.dumps({
            "job_code": "code1",
            "job_title": "Dev",
            "job_description": "desc",
            "desired_skills": ["python"],
        })
    )

    class FakeResp:
        def __init__(self):
            self.choices = [
                type(
                    "obj",
                    (),
                    {
                        "message": type(
                            "obj",
                            (),
                            {
                                "content": "<h2>Job Summary</h2><p>done</p><h2>Interview Preparation Tips</h2><p>tips</p>"
                            },
                        )
                    },
                )
            ]

    def fake_create(model, messages, temperature):
        return FakeResp()

    monkeypatch.setattr(main_app.client.chat.completions, "create", fake_create)

    login_resp = client.post("/login", json={"email": "admin@example.com", "password": "admin123"})
    token = login_resp.json()["token"]

    resp = client.post(
        "/generate-description",
        json={"student_email": "stud@example.com", "job_code": "code1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


def test_generate_job_description(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    student = {
        "first_name": "Stud",
        "last_name": "S",
        "skills": ["python"],
        "email": "stud@example.com",
        "institutional_code": "1001",
        "student_id": "stud3",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.redis_client.set(
        "job:code2",
        json.dumps({
            "job_code": "code2",
            "job_title": "Dev",
            "job_description": "desc",
            "desired_skills": ["python"],
            "min_pay": 5.0,
            "max_pay": 10.0,
            "city": "Austin",
            "state": "TX",
            "source": "Indeed",
        })
    )

    class FakeResp:
        def __init__(self):
            self.choices = [
                type(
                    "obj",
                    (),
                    {
                        "message": type(
                            "obj",
                            (),
                            {
                                "content": "<h2>Job Summary</h2><p>done</p><h2>Interview Preparation Tips</h2><p>tips</p>"
                            },
                        )
                    },
                )
            ]

    captured = {}

    def fake_create(model, messages, temperature):
        captured["messages"] = messages
        return FakeResp()

    monkeypatch.setattr(main_app.client.chat.completions, "create", fake_create)

    login_resp = client.post("/login", json={"email": "admin@example.com", "password": "admin123"})
    token = login_resp.json()["token"]

    resp = client.post(
        "/generate-job-description",
        json={"student_email": "stud@example.com", "job_code": "code2"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert "Pay Range" in captured["messages"][0]["content"]
    assert "5.0" in captured["messages"][0]["content"]
    assert "10.0" in captured["messages"][0]["content"]

    get_resp = client.get(
        "/job-description/code2/stud@example.com",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_resp.status_code == 200
    html_content = get_resp.json()["description"]
    assert html_content.lstrip().startswith("<!DOCTYPE html>")
    assert "done" in html_content
    assert "Interview Preparation Tips" in html_content
    assert "Source:" in html_content
    assert "Pay Range:" in html_content
    assert "Location:" in html_content
    assert "<h1>TalentMatch-AI</h1>" in html_content


def test_generate_job_description_with_benefits(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    student = {
        "first_name": "Stud",
        "last_name": "S",
        "skills": ["python"],
        "email": "stud@example.com",
        "institutional_code": "1001",
        "student_id": "stud4",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )

    job_desc = (
        "Benefits\nPulled from the full job description\nReferral program\n403(b)\n\n"
        "Full job description\nHIRING NOW!"
    )
    main_app.redis_client.set(
        "job:code3",
        json.dumps(
            {
                "job_code": "code3",
                "job_title": "Dev",
                "job_description": job_desc,
                "desired_skills": ["python"],
                "min_pay": 5.0,
                "max_pay": 10.0,
                "city": "Austin",
                "state": "TX",
                "source": "Indeed",
            }
        ),
    )

    class FakeResp:
        def __init__(self):
            self.choices = [
                type(
                    "obj",
                    (),
                    {
                        "message": type(
                            "obj",
                            (),
                            {
                                "content": "<h2>Job Summary</h2><p>done</p><h2>Interview Preparation Tips</h2><p>tips</p>",
                            },
                        )
                    },
                )
            ]

    def fake_create(model, messages, temperature):
        return FakeResp()

    monkeypatch.setattr(main_app.client.chat.completions, "create", fake_create)

    login_resp = client.post("/login", json={"email": "admin@example.com", "password": "admin123"})
    token = login_resp.json()["token"]

    resp = client.post(
        "/generate-job-description",
        json={"student_email": "stud@example.com", "job_code": "code3"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    html = main_app.redis_client.get("jobdesc:code3:stud@example.com")
    assert "<h2>Benefits</h2>" in html
    assert "Referral program" in html
    assert "<h2>Full Job Description</h2>" not in html


def test_generate_job_description_external(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    student = {
        "first_name": "Stud",
        "last_name": "S",
        "skills": ["python"],
        "email": "stud@example.com",
        "institutional_code": "1001",
        "student_id": "studext",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.redis_client.set(
        "job:code_ext",
        json.dumps(
            {
                "job_code": "code_ext",
                "job_title": "Dev",
                "job_description": "desc",
                "desired_skills": ["python"],
                "min_pay": 5.0,
                "max_pay": 10.0,
                "city": "Austin",
                "state": "TX",
                "source": "Indeed",
                "external_apply_url": "https://example.com/apply",
            }
        ),
    )

    class FakeResp:
        def __init__(self):
            self.choices = [
                type(
                    "obj",
                    (),
                    {
                        "message": type(
                            "obj",
                            (),
                            {
                                "content": "<h2>Job Summary</h2><p>done</p><h2>Interview Preparation Tips</h2><p>tips</p>"
                            },
                        )
                    },
                )
            ]

    captured = {}

    def fake_create(model, messages, temperature):
        captured["called"] = True
        return FakeResp()

    monkeypatch.setattr(main_app.client.chat.completions, "create", fake_create)

    login_resp = client.post("/login", json={"email": "admin@example.com", "password": "admin123"})
    token = login_resp.json()["token"]

    resp = client.post(
        "/generate-job-description",
        json={"student_email": "stud@example.com", "job_code": "code_ext"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    get_resp = client.get(
        "/job-description/code_ext/stud@example.com",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_resp.status_code == 200
    html_content = get_resp.json()["description"]
    assert captured.get("called")
    assert "<h1>TalentMatch-AI</h1>" in html_content
    assert "Interview Preparation Tips" in html_content
    assert "Apply Here" in html_content
    assert "https://example.com/apply" in html_content


def test_job_description_html_route():
    main_app.redis_client.flushdb()
    init_default_admin()

    main_app.redis_client.set(
        "jobdesc:codeh:stud@example.com",
        "html desc",
    )

    login_resp = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    )
    token = login_resp.json()["token"]

    resp = client.get(
        "/job-description-html/codeh/stud@example.com",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert "html" in resp.text.lower()


def test_public_job_description_html_route():
    main_app.redis_client.flushdb()
    init_default_admin()

    main_app.redis_client.set(
        "jobdesc:codep:stud@example.com",
        "public desc",
    )

    resp = client.get(
        "/public/job-description-html/codep/stud@example.com",
    )
    assert resp.status_code == 200
    assert "public" in resp.text.lower()


def test_notify_interest_generates_description(monkeypatch):
    main_app.redis_client = DummyRedis()
    init_default_admin()

    student = {
        "first_name": "Stud",
        "last_name": "S",
        "skills": ["python"],
        "email": "stud@example.com",
        "institutional_code": "1001",
        "student_id": "stud4",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.redis_client.set(
        "job:codei",
        json.dumps({
            "job_code": "codei",
            "job_title": "Dev",
            "job_description": "desc",
            "desired_skills": ["python"],
            "assigned_students": ["stud@example.com"],
            "external_apply_url": "https://example.com/apply",
        })
    )

    class FakeResp:
        def __init__(self):
            self.choices = [type("obj", (), {"message": type("obj", (), {"content": "done"})})]

    def fake_create(model, messages, temperature):
        return FakeResp()

    sent = {}

    def fake_send(recipient, subject, body, html_body=None, attachments=None, track_token=None):
        sent['body'] = body
        sent['attachments'] = attachments
        sent['token'] = track_token
        pixel_url = (
            f"{main_app.SITE_BASE_URL}/track/open/{track_token}.png"
            if main_app.SITE_BASE_URL
            else f"/track/open/{track_token}.png"
        )
        sent['final_body'] = body + (f'<img src="{pixel_url}" width="1" height="1" />' if track_token else '')

    monkeypatch.setattr(main_app.client.chat.completions, "create", fake_create)
    monkeypatch.setattr(main_app, "send_email", fake_send)

    token = client.post("/login", json={"email": "admin@example.com", "password": "admin123"}).json()["token"]

    resp = client.post(
        "/notify-interest",
        json={"student_email": "stud@example.com", "job_code": "codei"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    stored = main_app.redis_client.get("job_description:codei:stud@example.com")
    assert stored is not None
    assert "Apply Here" in stored
    assert main_app.redis_client.get("jobdesc:codei:stud@example.com") == stored
    token_val = sent.get("token")
    assert token_val
    mapping_raw = main_app.redis_client.hget(main_app.EMAIL_OPEN_TOKENS_KEY, token_val)
    assert mapping_raw is not None
    mapping = json.loads(mapping_raw)
    assert mapping.get("external_url") == "https://example.com/apply"
    click_url = f"/track/click/{token_val}"
    if main_app.SITE_BASE_URL:
        click_url = f"{main_app.SITE_BASE_URL}{click_url}"
    assert click_url in sent.get("body")
    assert "https://example.com/apply" not in sent.get("body")
    assert f"/track/open/{token_val}.png" in sent.get("final_body")
    assert "Good Luck" in sent.get("body")
    assert "/public/job-description-html/codei/stud@example.com" in sent.get("body")
    assert sent.get("attachments") is None
    assert "Your resume has been matched with this job." in sent.get("body")
    assert "recruiter has reviewed your resume" not in sent.get("body").lower()

    # Verify click tracking redirects and logs
    resp_click = client.get(f"/track/click/{token_val}", follow_redirects=False)
    assert resp_click.status_code in (302, 307)
    assert resp_click.headers.get("location") == "https://example.com/apply"
    log_raw = main_app.redis_client.lindex(main_app.ACTIVITY_LOG_KEY, -2)
    assert log_raw is not None
    log = json.loads(log_raw)
    assert log.get("event") == "email_click"
    assert log.get("token") == token_val


def test_notify_interest_multiple_times(monkeypatch):
    main_app.redis_client = DummyRedis()
    init_default_admin()

    student = {
        "first_name": "Stud",
        "last_name": "S",
        "skills": ["python"],
        "email": "stud@example.com",
        "institutional_code": "1001",
        "student_id": "stud5",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.redis_client.set(
        "job:codei",
        json.dumps({
            "job_code": "codei",
            "job_title": "Dev",
            "job_description": "desc",
            "desired_skills": ["python"],
            "assigned_students": ["stud@example.com"],
        })
    )

    class FakeResp:
        def __init__(self):
            self.choices = [type("obj", (), {"message": type("obj", (), {"content": "done"})})]

    def fake_create(model, messages, temperature):
        return FakeResp()

    bodies = []

    def fake_send(recipient, subject, body, html_body=None, attachments=None, track_token=None):
        bodies.append((body, track_token))

    monkeypatch.setattr(main_app.client.chat.completions, "create", fake_create)
    monkeypatch.setattr(main_app, "send_email", fake_send)

    token = client.post("/login", json={"email": "admin@example.com", "password": "admin123"}).json()["token"]

    resp1 = client.post(
        "/notify-interest",
        json={"student_email": "stud@example.com", "job_code": "codei"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp2 = client.post(
        "/notify-interest",
        json={"student_email": "stud@example.com", "job_code": "codei"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert len(bodies) == 2
    assert bodies[0][0] == bodies[1][0]
    assert bodies[0][1] != bodies[1][1]
    assert "Your resume has been matched with this job." in bodies[0][0]
    assert "recruiter has reviewed your resume" not in bodies[0][0].lower()
    stored = main_app.redis_client.get("job_description:codei:stud@example.com")
    assert stored is not None and "done" in stored


def test_career_notify_interest(monkeypatch):
    main_app.redis_client = DummyRedis()
    init_default_admin()

    # create career user
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
    main_app.redis_client.set(ck, json.dumps(cdata))
    token = client.post(
        "/login", json={"email": career["email"], "password": career["password"]}
    ).json()["token"]

    student = {
        "first_name": "Stud",
        "last_name": "S",
        "skills": ["python"],
        "email": "stud@example.com",
        "institutional_code": "1001",
        "student_id": "studc",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.redis_client.set(
        "job:codei",
        json.dumps(
            {
                "job_code": "codei",
                "job_title": "Dev",
                "job_description": "desc",
                "desired_skills": ["python"],
                "assigned_students": ["stud@example.com"],
            }
        ),
    )

    class FakeResp:
        def __init__(self):
            self.choices = [
                type("obj", (), {"message": type("obj", (), {"content": "done"})})
            ]

    def fake_create(model, messages, temperature):
        return FakeResp()

    monkeypatch.setattr(main_app.client.chat.completions, "create", fake_create)
    monkeypatch.setattr(main_app, "send_email", lambda *a, **k: None)

    resp = client.post(
        "/notify-interest",
        json={"student_email": "stud@example.com", "job_code": "codei"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert (
        main_app.redis_client.get("job_description:codei:stud@example.com")
        is not None
    )

def test_track_open_logs_event(monkeypatch):
    main_app.redis_client = DummyRedis()
    init_default_admin()

    student = {
        "first_name": "Stud",
        "last_name": "S",
        "skills": ["python"],
        "email": "stud@example.com",
        "institutional_code": "1001",
        "student_id": "stud7",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.redis_client.set(
        "job:codei",
        json.dumps({
            "job_code": "codei",
            "job_title": "Dev",
            "job_description": "desc",
            "desired_skills": ["python"],
            "assigned_students": ["stud@example.com"],
        }),
    )

    class FakeResp:
        def __init__(self):
            self.choices = [type("obj", (), {"message": type("obj", (), {"content": "done"})})]

    def fake_create(model, messages, temperature):
        return FakeResp()

    sent = {}

    def fake_send(recipient, subject, body, html_body=None, attachments=None, track_token=None):
        sent["token"] = track_token

    monkeypatch.setattr(main_app.client.chat.completions, "create", fake_create)
    monkeypatch.setattr(main_app, "send_email", fake_send)

    token = client.post("/login", json={"email": "admin@example.com", "password": "admin123"}).json()["token"]

    resp = client.post(
        "/notify-interest",
        json={"student_email": "stud@example.com", "job_code": "codei"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    tok = sent["token"]
    resp2 = client.get(f"/track/open/{tok}.png")
    assert resp2.status_code == 200
    assert resp2.headers["content-type"] == "image/png"
    assert resp2.content == main_app.TRANSPARENT_PNG
    entry_raw = main_app.redis_client.lindex(main_app.ACTIVITY_LOG_KEY, -2)
    entry = json.loads(entry_raw)
    assert entry["event"] == "email_open"
    assert entry["token"] == tok


def test_tracking_fields_returned(monkeypatch):
    main_app.redis_client = DummyRedis()
    init_default_admin()

    student = {
        "first_name": "Stud",
        "last_name": "S",
        "skills": ["python"],
        "email": "stud@example.com",
        "institutional_code": "1001",
        "student_id": "stud8",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.redis_client.set(
        "job:codei",
        json.dumps(
                {
                    "job_code": "codei",
                    "job_title": "Dev",
                    "job_description": "desc",
                    "desired_skills": ["python"],
                    "assigned_students": ["stud@example.com"],
                    "external_apply_url": "https://example.com/apply",
                }
            ),
        )

    class FakeResp:
        def __init__(self):
            self.choices = [type("obj", (), {"message": type("obj", (), {"content": "done"})})]

    def fake_create(model, messages, temperature):
        return FakeResp()

    sent = {}

    def fake_send(recipient, subject, body, html_body=None, attachments=None, track_token=None):
        sent["token"] = track_token

    monkeypatch.setattr(main_app.client.chat.completions, "create", fake_create)
    monkeypatch.setattr(main_app, "send_email", fake_send)

    token = client.post("/login", json={"email": "admin@example.com", "password": "admin123"}).json()["token"]

    resp = client.post(
        "/notify-interest",
        json={"student_email": "stud@example.com", "job_code": "codei"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    tok = sent["token"]
    client.get(f"/track/open/{tok}.png")
    client.get(f"/track/click/{tok}")

    resp2 = client.get(
        "/students/all", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp2.status_code == 200
    job_entry = resp2.json()["students"][0]["assigned_jobs"][0]
    assert job_entry["email_sent"] is not None
    assert job_entry["first_open"] is not None
    assert job_entry["clicked"] is True


def test_generate_resume_html(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    student = {
        "first_name": "Stud",
        "last_name": "S",
        "skills": ["python"],
        "email": "stud@example.com",
        "institutional_code": "1001",
        "student_id": "stud6",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.redis_client.set(
        "job:coder",
        json.dumps({
            "job_code": "coder",
            "job_title": "Dev",
            "job_description": "desc",
            "desired_skills": ["python"],
            "assigned_students": ["stud@example.com"],
        })
    )

    class FakeResp:
        def __init__(self):
            sample_html = (
                "<h2>Professional Summary</h2><p>Summary</p>"
                "<h2>Skills</h2><ul><li>Python</li></ul>"
                "<h2>Experience</h2><ul><li>Job</li></ul>"
                "<h2>Education</h2><p>College</p>"
            )
            self.choices = [
                type(
                    "obj",
                    (),
                    {"message": type("obj", (), {"content": sample_html})},
                )
            ]

    def fake_create(model, messages, temperature):
        return FakeResp()

    monkeypatch.setattr(main_app.client.chat.completions, "create", fake_create)

    token = client.post("/login", json={"email": "admin@example.com", "password": "admin123"}).json()["token"]

    resp = client.post(
        "/generate-resume",
        json={"student_email": "stud@example.com", "job_code": "coder"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    html_resp = client.get(
        "/resume-html/coder/stud@example.com",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert html_resp.status_code == 200
    lower_html = html_resp.text.lower()
    assert "professional summary" in lower_html
    assert "<ul>" in lower_html


def test_generate_resume_full_html(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    student = {
        "first_name": "Stud",
        "last_name": "S",
        "skills": ["python"],
        "email": "stud@example.com",
        "institutional_code": "1001",
        "student_id": "stud7",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.redis_client.set(
        "job:coder",
        json.dumps({
            "job_code": "coder",
            "job_title": "Dev",
            "job_description": "desc",
            "desired_skills": ["python"],
            "assigned_students": ["stud@example.com"],
        })
    )

    html_page = (
        "<!DOCTYPE html>"
        "<html><head><title>Title</title></head>"
        "<body>"
        "<h2>Professional Summary</h2><p>Summary</p>"
        "<h2>Skills</h2><ul><li>Python</li></ul>"
        "<h2>Experience</h2><ul><li>Job</li></ul>"
        "<h2>Education</h2><p>College</p>"
        "</body></html>"
    )

    class FakeResp:
        def __init__(self):
            self.choices = [type("obj", (), {"message": type("obj", (), {"content": html_page})})]

    def fake_create(model, messages, temperature):
        return FakeResp()

    monkeypatch.setattr(main_app.client.chat.completions, "create", fake_create)

    token = client.post("/login", json={"email": "admin@example.com", "password": "admin123"}).json()["token"]

    resp = client.post(
        "/generate-resume",
        json={"student_email": "stud@example.com", "job_code": "coder"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    html_resp = client.get(
        "/resume-html/coder/stud@example.com",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert html_resp.status_code == 200
    assert html_resp.text.lower().count("<html") == 1
    lower_html = html_resp.text.lower()
    assert "professional summary" in lower_html
    assert "<ul>" in lower_html


def test_resume_html_route():
    main_app.redis_client.flushdb()
    init_default_admin()

    main_app.redis_client.set(
        "resumehtml:codeh:stud@example.com",
        "<html><body><h2>Professional Summary</h2></body></html>",
    )
    main_app.redis_client.set(
        "job:codeh",
        json.dumps({"job_code": "codeh", "assigned_students": ["stud@example.com"]})
    )

    token = client.post("/login", json={"email": "admin@example.com", "password": "admin123"}).json()["token"]

    resp = client.get(
        "/resume-html/codeh/stud@example.com",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert "professional summary" in resp.text.lower()


def test_generate_resume_preview(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    student = {
        "first_name": "Stud",
        "last_name": "S",
        "phone": "123",
        "email": "stud@example.com",
        "institutional_code": "1001",
        "student_id": "stud8",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.redis_client.set(
        "job:coder",
        json.dumps({
            "job_code": "coder",
            "job_title": "Dev",
            "job_description": "desc",
            "desired_skills": ["python"],
            "assigned_students": [],
            "placed_students": [],
        })
    )

    class FakeResp:
        def __init__(self):
            self.choices = [type("obj", (), {"message": type("obj", (), {"content": "<h2>Name</h2>"})})]

    def fake_create(model, messages, temperature):
        assert "stud@example.com" not in messages[0]["content"]
        assert "123" not in messages[0]["content"]
        return FakeResp()

    monkeypatch.setattr(main_app.client.chat.completions, "create", fake_create)

    token = client.post("/login", json={"email": "admin@example.com", "password": "admin123"}).json()["token"]

    resp = client.post(
        "/generate-resume",
        json={"student_email": "stud@example.com", "job_code": "coder", "preview": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "preview"
    assert "stud@example.com" not in resp.json()["html"]
    assert main_app.redis_client.get("resumehtml:coder:stud@example.com") is None


def test_generate_resume_user_key_lookup(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    # store profile using a mixed-case user key to exercise find_user_key()
    main_app.redis_client.set(
        "user:Stud@Example.com",
        json.dumps({"first_name": "Stud", "last_name": "S", "skills": ["python"]}),
    )
    main_app.redis_client.set(
        "job:coder",
        json.dumps({
            "job_code": "coder",
            "job_title": "Dev",
            "job_description": "desc",
            "desired_skills": ["python"],
            "assigned_students": ["stud@example.com"],
        }),
    )

    class FakeResp:
        def __init__(self):
            self.choices = [type("obj", (), {"message": type("obj", (), {"content": "<h2>Summary</h2>"})})]

    def fake_create(model, messages, temperature):
        return FakeResp()

    monkeypatch.setattr(main_app.client.chat.completions, "create", fake_create)

    token = client.post("/login", json={"email": "admin@example.com", "password": "admin123"}).json()["token"]

    resp = client.post(
        "/generate-resume",
        json={"student_email": "stud@example.com", "job_code": "coder"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


def test_generate_resume_student_key_fallback(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    # only legacy student: key exists
    legacy_student = {
        "first_name": "Stud",
        "last_name": "S",
        "skills": ["python"],
        "email": "stud@example.com",
        "institutional_code": "1001",
        "student_id": "legacy",
    }
    main_app.redis_client.set("student:stud@example.com", json.dumps(legacy_student))
    main_app.redis_client.set(
        "job:coder",
        json.dumps({
            "job_code": "coder",
            "job_title": "Dev",
            "job_description": "desc",
            "desired_skills": ["python"],
            "assigned_students": ["stud@example.com"],
        }),
    )

    class FakeResp:
        def __init__(self):
            self.choices = [type("obj", (), {"message": type("obj", (), {"content": "<h2>Summary</h2>"})})]

    def fake_create(model, messages, temperature):
        return FakeResp()

    monkeypatch.setattr(main_app.client.chat.completions, "create", fake_create)

    token = client.post("/login", json={"email": "admin@example.com", "password": "admin123"}).json()["token"]

    resp = client.post(
        "/generate-resume",
        json={"student_email": "stud@example.com", "job_code": "coder"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


def test_generate_resume_requires_assignment():
    main_app.redis_client.flushdb()
    init_default_admin()

    student = {
        "first_name": "S",
        "email": "s1@example.com",
        "institutional_code": "1001",
        "student_id": "s1",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.redis_client.set("job:j1", json.dumps({"job_code": "j1"}))

    token = client.post("/login", json={"email": "admin@example.com", "password": "admin123"}).json()["token"]

    resp = client.post(
        "/generate-resume",
        json={"student_email": "s1@example.com", "job_code": "j1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_get_resume_requires_assignment():
    main_app.redis_client.flushdb()
    init_default_admin()

    student = {
        "first_name": "S",
        "email": "s1@example.com",
        "institutional_code": "1001",
        "student_id": "s1",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.redis_client.set("job:j1", json.dumps({"job_code": "j1"}))
    main_app.redis_client.set("resume:j1:s1@example.com", "resume")

    token = client.post("/login", json={"email": "admin@example.com", "password": "admin123"}).json()["token"]

    resp = client.get(
        "/resume/j1/s1@example.com",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_get_resume_html_requires_assignment():
    main_app.redis_client.flushdb()
    init_default_admin()

    student = {
        "first_name": "S",
        "email": "s1@example.com",
        "institutional_code": "1001",
        "student_id": "s1",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.redis_client.set("job:j1", json.dumps({"job_code": "j1"}))
    main_app.redis_client.set("resumehtml:j1:s1@example.com", "<html>")

    token = client.post("/login", json={"email": "admin@example.com", "password": "admin123"}).json()["token"]

    resp = client.get(
        "/resume-html/j1/s1@example.com",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_admin_delete_student_cleans_up():
    main_app.redis_client.flushdb()
    init_default_admin()

    student = {
        "email": "del@example.com",
        "institutional_code": "1001",
        "student_id": "del1",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    skey = main_app.student_key(student["institutional_code"], student["student_id"])
    # Simulate leftover user record
    main_app.redis_client.set(
        "user:del@example.com", json.dumps({"role": "applicant"})
    )
    main_app.redis_client.set(
        "job:j1",
        json.dumps({"job_code": "j1", "assigned_students": ["del@example.com"], "placed_students": ["del@example.com"]}),
    )
    main_app.redis_client.set("resume:j1:del@example.com", "resume")
    main_app.redis_client.set("job_description:j1:del@example.com", "desc")
    main_app.redis_client.set("match_results:j1", json.dumps([{"email": "del@example.com"}]))

    login_resp = client.post("/login", json={"email": "admin@example.com", "password": "admin123"})
    token = login_resp.json()["token"]

    resp = client.delete(
        "/admin/delete-student/del@example.com",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    assert not main_app.redis_client.exists(skey)
    assert main_app.redis_client.get(main_app.student_email_key("del@example.com")) is None
    assert main_app.redis_client.get("user:del@example.com") is None
    job = json.loads(main_app.redis_client.get("job:j1"))
    assert "del@example.com" not in job.get("assigned_students", [])
    assert "del@example.com" not in job.get("placed_students", [])
    assert main_app.redis_client.get("resume:j1:del@example.com") is None
    assert main_app.redis_client.get("job_description:j1:del@example.com") is None
    assert main_app.redis_client.get("match_results:j1") == "[]"


def test_delete_student_not_found():
    main_app.redis_client.flushdb()
    init_default_admin()

    login_resp = client.post("/login", json={"email": "admin@example.com", "password": "admin123"})
    token = login_resp.json()["token"]

    resp = client.delete(
        "/admin/delete-student/missing@example.com",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_delete_student_forbidden_non_admin():
    main_app.redis_client.flushdb()
    init_default_admin()

    user = {
        "email": "user@example.com",
        "first_name": "User",
        "last_name": "Test",
        "school_code": "1001",
        "password": "pass",
        "role": "applicant",
    }
    client.post("/register", json=user)
    key = f"user:{user['email']}"
    data = json.loads(main_app.redis_client.get(key))
    data["approved"] = True
    main_app.redis_client.set(key, json.dumps(data))
    login_resp = client.post("/login", json={"email": user["email"], "password": user["password"]})
    token = login_resp.json()["token"]

    student = {
        "email": "del@example.com",
        "institutional_code": "1001",
        "student_id": "del2",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )

    resp = client.delete(
        "/admin/delete-student/del@example.com",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_creating_student_does_not_create_user(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    admin_token = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    ).json()["token"]

    profile = {
        "first_name": "Stu",
        "last_name": "Dent",
        "email": "stu@example.com",
        "phone": "123",
        "license": "lvn",
        "skills": ["skill"],
        "experience_summary": "summary",
        "interests": "interest",
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 10.0,
    }

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [0.0, 0.0]})]

    def fake_create(input, model):
        return FakeResp()

    monkeypatch.setattr(main_app.client.embeddings, "create", fake_create)

    resp = client.post(
        "/students", json=profile, headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    assert main_app.redis_client.get("user:stu@example.com") is None


def test_recruiter_cannot_place_student():
    main_app.redis_client.flushdb()
    init_default_admin()

    # Seed a job to place into
    main_app.redis_client.set(
        "job:j1", json.dumps({"job_code": "j1", "assigned_students": [], "placed_students": []})
    )

    recruiter = {
        "email": "rec@example.com",
        "first_name": "Rec",
        "last_name": "R",
        "school_code": "1001",
        "password": "pass",
        "role": "recruiter",
    }
    client.post("/register", json=recruiter)
    key = f"user:{recruiter['email']}"
    data = json.loads(main_app.redis_client.get(key))
    data["approved"] = True
    data["role"] = "recruiter"
    main_app.redis_client.set(key, json.dumps(data))
    login_resp = client.post("/login", json={"email": recruiter["email"], "password": recruiter["password"]})
    token = login_resp.json()["token"]

    resp = client.post(
        "/place",
        json={"job_code": "j1", "student_email": "stud@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_students_me_endpoint(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    # create applicant user and profile
    applicant = {
        "email": "app@example.com",
        "first_name": "App",
        "last_name": "User",
        "school_code": "1001",
        "password": "pass",
        "role": "applicant",
    }
    client.post("/register", json=applicant)
    key = f"user:{applicant['email']}"
    data = json.loads(main_app.redis_client.get(key))
    data["approved"] = True
    data["role"] = "applicant"
    main_app.redis_client.set(key, json.dumps(data))
    login_resp = client.post("/login", json={"email": applicant["email"], "password": applicant["password"]})
    token = login_resp.json()["token"]

    profile = {
        "first_name": "App",
        "last_name": "User",
        "email": applicant["email"],
        "phone": "123",
        "license": "lvn",
        "skills": ["python"],
        "experience_summary": "summary",
        "interests": "dev",
        "city": "City",
        "state": "ST",
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 50.0,
    }

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [0.0, 0.0]})]

    def fake_create(input, model):
        return FakeResp()

    monkeypatch.setattr(main_app.client.embeddings, "create", fake_create)

    client.post("/students", json=profile, headers={"Authorization": f"Bearer {token}"})

    resp = client.get("/students/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == applicant["email"]
    assert data["city"] == "City"
    assert data["state"] == "ST"


def test_admin_user_management_flow():
    main_app.redis_client.flushdb()
    init_default_admin()

    admin_token = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    ).json()["token"]

    user = {
        "email": "editme@example.com",
        "first_name": "Ed",
        "last_name": "It",
        "school_code": "1001",
        "password": "pass",
        "role": "applicant",
    }
    client.post("/register", json=user)
    key = f"user:{user['email']}"
    data = json.loads(main_app.redis_client.get(key))
    data["approved"] = True
    main_app.redis_client.set(key, json.dumps(data))

    resp = client.get(
        "/admin/users", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    assert user["email"] in [u["email"] for u in resp.json()["users"]]

    resp = client.put(
        f"/admin/users/{user['email']}",
        json={"role": "recruiter", "active": False, "school_code": "1001"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    stored = json.loads(main_app.redis_client.get(key))
    assert stored["role"] == "recruiter"
    assert stored["active"] is False

    login = client.post(
        "/login", json={"email": user["email"], "password": user["password"]}
    )
    assert login.status_code == 403


def test_school_codes_endpoint():
    resp = client.get("/school-codes")
    assert resp.status_code == 200
    data = resp.json()
    assert "codes" in data
    assert any(c["code"] == "1001" for c in data["codes"])


def test_add_school_code():
    main_app.redis_client.flushdb()
    init_default_admin()
    login = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    )
    token = login.json()["token"]

    resp = client.post(
        "/admin/school-codes",
        json={"code": "SC1", "label": "School One"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    codes = client.get("/school-codes").json()["codes"]
    assert any(c["code"] == "SC1" for c in codes)


def test_update_and_delete_school_code():
    main_app.redis_client.flushdb()
    init_default_admin()
    token = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    ).json()["token"]

    client.post(
        "/admin/school-codes",
        json={"code": "SC2", "label": "School Two"},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = client.put(
        "/admin/school-codes/SC2",
        json={"label": "Updated Two"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    codes = client.get("/school-codes").json()["codes"]
    assert any(c["code"] == "SC2" and c["label"] == "Updated Two" for c in codes)

    resp = client.delete(
        "/admin/school-codes/SC2",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    codes = client.get("/school-codes").json()["codes"]
    assert not any(c["code"] == "SC2" for c in codes)


def test_init_default_school_codes_updates_label():
    main_app.redis_client.flushdb()
    main_app.redis_client.set("school_code:1002", "1002-Unitek-Old")
    main_app.init_default_school_codes()
    assert (
        main_app.redis_client.get("school_code:1002") == "1002-Unitek-SanJose"
    )


def test_admin_delete_user():
    main_app.redis_client.flushdb()
    init_default_admin()

    user = {
        "email": "todelete@example.com",
        "first_name": "To",
        "last_name": "Delete",
        "school_code": "1001",
        "password": "pw",
        "role": "applicant",
    }
    client.post("/register", json=user)
    key = f"user:{user['email']}"
    data = json.loads(main_app.redis_client.get(key))
    data["approved"] = True
    main_app.redis_client.set(key, json.dumps(data))

    admin_token = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    ).json()["token"]

    resp = client.delete(
        f"/admin/users/{user['email']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert main_app.redis_client.get(key) is None


def test_delete_user_not_found():
    main_app.redis_client.flushdb()
    init_default_admin()
    admin_token = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    ).json()["token"]

    resp = client.delete(
        "/admin/users/missing@example.com",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


def test_delete_user_forbidden_non_admin():
    main_app.redis_client.flushdb()
    init_default_admin()

    user = {
        "email": "staff@example.com",
        "first_name": "Staff",
        "last_name": "User",
        "school_code": "1001",
        "password": "pw",
        "role": "applicant",
    }
    client.post("/register", json=user)
    key = f"user:{user['email']}"
    data = json.loads(main_app.redis_client.get(key))
    data["approved"] = True
    main_app.redis_client.set(key, json.dumps(data))
    token = client.post(
        "/login", json={"email": user["email"], "password": user["password"]}
    ).json()["token"]

    resp = client.delete(
        "/admin/users/admin@example.com",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_nursing_news_cache(monkeypatch):
    main_app.redis_client.flushdb()

    calls = []

    class DummyResp:
        def __init__(self):
            self.text = (
                "<rss><channel>"
                "<item>"
                "<title>A</title>"
                "<link>http://a</link>"
                "<description>desc</description>"
                "<enclosure url='http://img/a.jpg' type='image/jpeg'/>"
                "</item>"
                "</channel></rss>"
            )

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def get(self, url):
            calls.append(url)
            return DummyResp()

    monkeypatch.setattr(
        main_app.httpx,
        "AsyncClient",
        lambda timeout=10, headers=None: DummyClient(),
    )

    resp1 = client.get("/nursing-news")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["feeds"]) == len(main_app.NURSING_FEEDS)
    for feed in data1["feeds"]:
        art = feed["articles"][0]
        assert "summary" in art
        assert "image" in art
    assert calls

    calls.clear()

    resp2 = client.get("/nursing-news")
    assert resp2.status_code == 200
    assert calls == []


def test_rss_feed_management():
    main_app.redis_client.flushdb()
    init_default_admin()

    token = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    ).json()["token"]

    resp = client.post(
        "/admin/rss-feeds",
        json={"name": "TestFeed", "url": "http://example.com/feed"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    feeds = client.get("/rss-feeds").json()["feeds"]
    assert any(f["name"] == "TestFeed" for f in feeds)

    resp = client.put(
        "/admin/rss-feeds/TestFeed",
        json={"url": "http://example.com/updated"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    feeds = client.get("/rss-feeds").json()["feeds"]
    assert any(
        f["name"] == "TestFeed" and f["url"] == "http://example.com/updated"
        for f in feeds
    )

    resp = client.delete(
        "/admin/rss-feeds/TestFeed",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    feeds = client.get("/rss-feeds").json()["feeds"]
    assert not any(f["name"] == "TestFeed" for f in feeds)


def test_admin_test_notification(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    sent = {}

    def fake_send_email(recipient, subject, body, html_body=None, attachments=None, track_token=None):
        sent["recipient"] = recipient
        sent["subject"] = subject
        sent["body"] = body

    monkeypatch.setattr(main_app, "send_email", fake_send_email)

    token = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    ).json()["token"]

    resp = client.post(
        "/admin/test-notification",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert sent["recipient"] == "admin@example.com"
    assert "Recruiter Interest" in sent["subject"]
    assert "recruiter has expressed interest" in sent["body"].lower()


def test_test_notification_forbidden():
    main_app.redis_client.flushdb()
    init_default_admin()

    # register and approve regular user
    user = {
        "email": "reg@example.com",
        "first_name": "Reg",
        "last_name": "User",
        "school_code": "1001",
        "password": "pass",
        "role": "applicant",
    }
    client.post("/register", json=user)
    key = f"user:{user['email']}"
    data = json.loads(main_app.redis_client.get(key))
    data["approved"] = True
    main_app.redis_client.set(key, json.dumps(data))

    token = client.post(
        "/login", json={"email": user["email"], "password": user["password"]}
    ).json()["token"]

    resp = client.post(
        "/admin/test-notification",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_admin_weekly_summary(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    called = {}

    def fake_summary(email):
        called["email"] = email

    monkeypatch.setattr(main_app, "send_weekly_summary", fake_summary)

    token = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    ).json()["token"]

    resp = client.post(
        "/admin/test-weekly-summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert called["email"] == "admin@example.com"


def test_weekly_summary_forbidden():
    main_app.redis_client.flushdb()
    init_default_admin()

    user = {
        "email": "reg@example.com",
        "first_name": "Reg",
        "last_name": "User",
        "school_code": "1001",
        "password": "pass",
        "role": "applicant",
    }
    client.post("/register", json=user)
    key = f"user:{user['email']}"
    data = json.loads(main_app.redis_client.get(key))
    data["approved"] = True
    main_app.redis_client.set(key, json.dumps(data))

    token = client.post(
        "/login", json={"email": user["email"], "password": user["password"]}
    ).json()["token"]

    resp = client.post(
        "/admin/test-weekly-summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_match_metrics_increment(monkeypatch):
    main_app.redis_client.flushdb()
    job = {
        "job_code": "abc",
        "job_title": "Test",
        "job_description": "d",
        "desired_skills": [],
        "lat": 0.0,
        "lng": 0.0,
        "posted_by": "admin@example.com",
    }
    student = {
        "email": "s@example.com",
        "first_name": "S",
        "last_name": "T",
        "embedding": [0.0] * 1536,
        "lat": 0.0,
        "lng": 0.0,
        "max_travel": 10,
        "institutional_code": "1001",
        "student_id": "s123",
    }
    main_app.redis_client.set("job:abc", json.dumps(job))
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )
    main_app.rebuild_vector_index()

    class FakeResp:
        def __init__(self):
            self.data = [type("obj", (), {"embedding": [0.0] * 1536})]

    monkeypatch.setattr(main_app.client.embeddings, "create", lambda *a, **k: FakeResp())
    monkeypatch.setattr(main_app, "get_driving_distance_miles", lambda *a, **k: 1.0)

    called = {}

    def fake_send_email(*args, **kwargs):
        called["count"] = called.get("count", 0) + 1

    monkeypatch.setattr(main_app, "send_email", fake_send_email)

    main_app.match_worker("abc", enq_time=datetime.now().timestamp())
    assert called == {}
    process = float(main_app.redis_client.get("metrics:match_process_time") or 0)
    queue = float(main_app.redis_client.get("metrics:match_queue_time") or 0)
    assert process > 0
    assert queue >= 0


def test_students_by_school_fallback():
    main_app.redis_client.flushdb()

    user = {
        "role": "career",
        "approved": True,
        "school_code": "1001",
    }
    main_app.redis_client.set("user:counselor@example.com", json.dumps(user))

    student = {
        "first_name": "Stu",
        "last_name": "Dent",
        "email": "student@example.com",
        "phone": "123",
        "license": "ma",
        "skills": [],
        "experience_summary": "",
        "interests": "",
        "school_code": "1001",
        "created_by": "counselor@example.com",
        "city": "City",
        "state": "ST",
        "institutional_code": "1001",
        "student_id": "stud9",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )

    token = jwt.encode(
        {
            "sub": "counselor@example.com",
            "role": "career",
            "exp": datetime.utcnow() + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm=ALGORITHM,
    )

    resp = client.get(
        "/students/by-school",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any(s["email"] == "student@example.com" for s in data["students"])
    entry = next(s for s in data["students"] if s["email"] == "student@example.com")
    assert entry["city"] == "City"
    assert entry["state"] == "ST"


def test_students_by_school_requires_code():
    main_app.redis_client.flushdb()

    user = {
        "role": "career",
        "approved": True,
    }
    main_app.redis_client.set("user:counselor@example.com", json.dumps(user))

    token = jwt.encode(
        {
            "sub": "counselor@example.com",
            "role": "career",
            "exp": datetime.utcnow() + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm=ALGORITHM,
    )

    resp = client.get(
        "/students/by-school",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Institutional code required"


def test_student_endpoints_handle_string_notes():
    main_app.redis_client.flushdb()
    init_default_admin()

    student = {
        "first_name": "Stu",
        "last_name": "Dent",
        "email": "student@example.com",
        "institutional_code": "001",
        "student_id": "stud10",
        "created_by": "counselor@example.com",
        "city": "City",
        "state": "ST",
    }
    main_app.persist_student_record(
        student["email"], student, student["institutional_code"], student["student_id"]
    )

    job = {
        "job_code": "J1",
        "job_title": "Test",
        "student_notes": {"student@example.com": "legacy"},
        "assigned_students": ["student@example.com"],
    }
    main_app.redis_client.set("job:J1", json.dumps(job))

    login_resp = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    )
    token_admin = login_resp.json()["token"]
    resp_all = client.get(
        "/students/all", headers={"Authorization": f"Bearer {token_admin}"}
    )
    student_entry = resp_all.json()["students"][0]
    assert student_entry["city"] == "City"
    assert student_entry["state"] == "ST"
    entry = student_entry["assigned_jobs"][0]
    assert entry["notes"] == [{"text": "legacy"}]
    assert entry["note"] == "legacy"
    assert "posted_by" in entry

    counselor = {"role": "career", "approved": True, "institutional_code": "001"}
    main_app.redis_client.set("user:counselor@example.com", json.dumps(counselor))
    token_counselor = jwt.encode(
        {
            "sub": "counselor@example.com",
            "role": "career",
            "exp": datetime.utcnow() + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm=ALGORITHM,
    )
    resp_school = client.get(
        "/students/by-school",
        headers={"Authorization": f"Bearer {token_counselor}"},
    )
    school_entry = resp_school.json()["students"][0]
    assert school_entry["city"] == "City"
    assert school_entry["state"] == "ST"
    entry = school_entry["assigned_jobs"][0]
    assert entry["notes"] == [{"text": "legacy"}]
    assert entry["note"] == "legacy"
    assert "posted_by" in entry

    token_student = jwt.encode(
        {
            "sub": "student@example.com",
            "role": "applicant",
            "exp": datetime.utcnow() + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm=ALGORITHM,
    )
    resp_me = client.get(
        "/students/me", headers={"Authorization": f"Bearer {token_student}"}
    )
    me_entry = resp_me.json()
    assert me_entry["city"] == "City"
    assert me_entry["state"] == "ST"
    entry = me_entry["assigned_jobs"][0]
    assert entry["notes"] == [{"text": "legacy"}]
    assert entry["note"] == "legacy"
    assert "posted_by" in entry


def test_malformed_user_skipped_in_listings():
    main_app.redis_client.flushdb()
    init_default_admin()

    login_resp = client.post(
        "/login", json={"email": "admin@example.com", "password": "admin123"}
    )
    token = login_resp.json()["token"]

    # Insert one valid and one malformed user record
    main_app.redis_client.set(
        "user:good@example.com", json.dumps({"first_name": "Good", "password": "pw"})
    )
    main_app.redis_client.set("user:bad@example.com", "{not-json}")

    pending = client.get("/pending-users", headers={"Authorization": f"Bearer {token}"})
    assert pending.status_code == 200
    emails = [u["email"] for u in pending.json()]
    assert "good@example.com" in emails
    assert "bad@example.com" not in emails

    users = client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert users.status_code == 200
    user_emails = [u["email"] for u in users.json()["users"]]
    assert "bad@example.com" not in user_emails

