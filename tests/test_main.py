import os
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("GOOGLE_KEY", "test")

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
        "first_name,last_name,email,phone,education_level,skills,experience_summary,interests,city,state,lat,lng,max_travel\n"
        "John,Doe,john@example.com,123,College,python,summary,coding,City,ST,0,0,100\n"
        "Jane,Smith,jane@example.com,456,College,sql,summary2,data,City,ST,0,0,100\n"
    )
    files = {"file": ("students.csv", csv_data, "text/csv")}
    resp = client.post("/students/upload", files=files, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 2
    assert len(stored) == 2


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
    s1 = {"first_name": "One", "last_name": "A", "email": "one@example.com", "education_level": "College"}
    s2 = {"first_name": "Two", "last_name": "B", "email": "two@example.com", "education_level": "HS"}
    main_app.redis_client.set("student:one@example.com", json.dumps(s1))
    main_app.redis_client.set("student:two@example.com", json.dumps(s2))

    login_resp = client.post("/login", json={"email": "admin@example.com", "password": "admin123"})
    token = login_resp.json()["token"]

    resp = client.get("/students/all", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()["students"]
    emails = {s["email"] for s in data}
    assert {"one@example.com", "two@example.com"} <= emails


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
        "education_level": "HS",
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
    }
    main_app.redis_client.set("student:stud@example.com", json.dumps(existing))

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
        "education_level": "College",
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

    saved = json.loads(main_app.redis_client.get("student:stud@example.com"))
    assert saved["first_name"] == "New"
    assert saved["education_level"] == "College"
    assert saved["embedding"] == [1.0, 2.0]
    assert saved["school_code"] == "SC1"


def test_generate_description(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    # Seed job and student
    main_app.redis_client.set(
        "student:stud@example.com",
        json.dumps({"first_name": "Stud", "last_name": "S", "skills": ["python"]})
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
            self.choices = [type("obj", (), {"message": type("obj", (), {"content": "done"})})]

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

    main_app.redis_client.set(
        "student:stud@example.com",
        json.dumps({"first_name": "Stud", "last_name": "S", "skills": ["python"]})
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
        })
    )

    class FakeResp:
        def __init__(self):
            self.choices = [type("obj", (), {"message": type("obj", (), {"content": "done"})})]

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
    main_app.redis_client.flushdb()
    init_default_admin()

    main_app.redis_client.set(
        "student:stud@example.com",
        json.dumps({"first_name": "Stud", "last_name": "S", "skills": ["python"]})
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

    sent = {}

    def fake_send(recipient, subject, body, attachments=None):
        sent['body'] = body
        sent['attachments'] = attachments

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
    assert stored is not None and "done" in stored
    assert main_app.redis_client.get("jobdesc:codei:stud@example.com") == stored
    assert "Good Luck" in sent.get("body")
    assert "/public/job-description-html/codei/stud@example.com" in sent.get("body")
    assert sent.get("attachments") is None


def test_notify_interest_multiple_times(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    main_app.redis_client.set(
        "student:stud@example.com",
        json.dumps({"first_name": "Stud", "last_name": "S", "skills": ["python"]})
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

    def fake_send(recipient, subject, body, attachments=None):
        bodies.append(body)

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
    assert len(bodies) == 2 and bodies[0] == bodies[1]
    stored = main_app.redis_client.get("job_description:codei:stud@example.com")
    assert stored is not None and "done" in stored


def test_generate_resume_html(monkeypatch):
    main_app.redis_client.flushdb()
    init_default_admin()

    main_app.redis_client.set(
        "student:stud@example.com",
        json.dumps({"first_name": "Stud", "last_name": "S", "skills": ["python"]})
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

    main_app.redis_client.set(
        "student:stud@example.com",
        json.dumps({"first_name": "Stud", "last_name": "S", "skills": ["python"]})
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

    main_app.redis_client.set(
        "student:stud@example.com",
        json.dumps({"first_name": "Stud", "last_name": "S", "phone": "123", "email": "stud@example.com"})
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


def test_generate_resume_requires_assignment():
    main_app.redis_client.flushdb()
    init_default_admin()

    main_app.redis_client.set("student:s1@example.com", json.dumps({"first_name": "S"}))
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

    main_app.redis_client.set("student:s1@example.com", json.dumps({"first_name": "S"}))
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

    main_app.redis_client.set("student:s1@example.com", json.dumps({"first_name": "S"}))
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

    main_app.redis_client.set("student:del@example.com", json.dumps({"email": "del@example.com"}))
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

    assert not main_app.redis_client.exists("student:del@example.com")
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

    main_app.redis_client.set("student:del@example.com", json.dumps({"email": "del@example.com"}))

    resp = client.delete(
        "/admin/delete-student/del@example.com",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


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
        "education_level": "College",
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
    assert resp.json()["email"] == applicant["email"]


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

    def fake_send_email(recipient, subject, body):
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

