from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# Simple in-memory user "database"
users = {}


class UserRequest(BaseModel):
    first_name: str
    last_name: str
    school: str
    password: str

@app.get("/")
def read_root():
    return {"message": "Hello, World"}


@app.post("/register")
def register(user: UserRequest):
    """Register a new user."""
    key = f"{user.first_name}-{user.last_name}-{user.school}"
    if key in users:
        raise HTTPException(status_code=400, detail="User already exists")
    users[key] = user.password
    return {"message": "User registered successfully"}


@app.post("/login")
def login(user: UserRequest):
    """Login a user and return a dummy token."""
    key = f"{user.first_name}-{user.last_name}-{user.school}"
    if users.get(key) != user.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": "dummy-token"}
