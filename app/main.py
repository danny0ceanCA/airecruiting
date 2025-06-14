from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# In-memory user storage
# username -> {"password": str, "is_approved": bool, "is_admin": bool}
users = {"admin": {"password": "adminpass", "is_approved": True, "is_admin": True}}


class Credentials(BaseModel):
    username: str
    password: str


class AdminApproval(BaseModel):
    admin_username: str
    admin_password: str


@app.get("/")
def read_root():
    return {"message": "Hello, World"}


@app.post("/register")
def register(creds: Credentials):
    if creds.username in users:
        raise HTTPException(status_code=400, detail="User already exists")
    users[creds.username] = {
        "password": creds.password,
        "is_approved": False,
        "is_admin": False,
    }
    return {"message": "User registered successfully, awaiting approval"}


@app.post("/login")
def login(creds: Credentials):
    user = users.get(creds.username)
    if not user or user["password"] != creds.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("is_approved"):
        raise HTTPException(status_code=403, detail="User not approved")
    return {"token": "dummy-token"}


@app.post("/admin/approve/{username}")
def approve_user(username: str, admin: AdminApproval):
    admin_user = users.get(admin.admin_username)
    if (
        not admin_user
        or not admin_user.get("is_admin")
        or admin_user["password"] != admin.admin_password
    ):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    user = users.get(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user["is_approved"] = True
    return {"message": f"{username} approved"}
