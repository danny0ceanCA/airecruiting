from fastapi.testclient import TestClient
from jose import jwt
from app.main import app, JWT_SECRET, ALGORITHM, users

client = TestClient(app)


def test_read_root():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"message": "Hello, World"}


def test_registration_flow():
    users.clear()

    admin_data = {
        "email": "admin@example.com",
        "first_name": "Admin",
        "last_name": "User",
        "school": "Admin School",
        "password": "adminpass",
    }

    # Create admin user and elevate role
    client.post("/register", json=admin_data)
    users[admin_data["email"]]["role"] = "admin"
    users[admin_data["email"]]["approved"] = True
    admin_login = client.post(
        "/login", json={"email": admin_data["email"], "password": admin_data["password"]}
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
    users.clear()

    # Create regular user who will attempt approval
    user1 = {
        "email": "user1@example.com",
        "first_name": "User",
        "last_name": "One",
        "school": "Test U",
        "password": "pass1",
    }
    client.post("/register", json=user1)
    users[user1["email"]]["approved"] = True
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

