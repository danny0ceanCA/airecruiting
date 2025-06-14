from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, World"}


def test_register_and_login():
    user = {
        "first_name": "Jane",
        "last_name": "Doe",
        "school": "Example University",
        "password": "secret",
    }

    # Register user
    response = client.post("/register", json=user)
    assert response.status_code == 200
    assert response.json() == {"message": "User registered successfully"}

    # Duplicate registration should fail
    dup_response = client.post("/register", json=user)
    assert dup_response.status_code == 400

    # Successful login
    login_resp = client.post("/login", json=user)
    assert login_resp.status_code == 200
    assert login_resp.json() == {"token": "dummy-token"}

    # Wrong password
    bad_user = dict(user)
    bad_user["password"] = "wrong"
    bad_resp = client.post("/login", json=bad_user)
    assert bad_resp.status_code == 401
