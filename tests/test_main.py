from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_read_root():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"message": "Hello, World"}


def test_registration_flow():
    user = {"username": "jane", "password": "secret"}

    # Register
    resp = client.post("/register", json=user)
    assert resp.status_code == 200
    assert "awaiting approval" in resp.json()["message"]

    # Duplicate registration
    dup_resp = client.post("/register", json=user)
    assert dup_resp.status_code == 400

    # Login before approval should fail
    login_before = client.post("/login", json=user)
    assert login_before.status_code == 403

    # Approve user
    approve_resp = client.post(
        "/admin/approve/jane",
        json={"admin_username": "admin", "admin_password": "adminpass"},
    )
    assert approve_resp.status_code == 200

    # Login after approval
    login_after = client.post("/login", json=user)
    assert login_after.status_code == 200
    assert login_after.json() == {"token": "dummy-token"}
