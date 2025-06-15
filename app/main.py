from datetime import datetime, timedelta
import json
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from jose import jwt, JWTError
import bcrypt
import openai
import redis

JWT_SECRET = "secret"
ALGORITHM = "HS256"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory user storage
# email -> user dict
users = {}

# Redis connection
redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)


def init_default_admin():
    """Create the default admin account if it doesn't exist."""
    if "admin@example.com" not in users:
        hashed = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt())
        users["admin@example.com"] = {
            "first_name": "Admin",
            "last_name": "User",
            "school": "Admin School",
            "password": hashed,
            "role": "admin",
            "approved": True,
        }


init_default_admin()


class RegisterRequest(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    school: str
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ApproveRequest(BaseModel):
    email: EmailStr


class RejectRequest(BaseModel):
    email: EmailStr


class StudentRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    phone: str
    education_level: str
    skills: list[str]
    experience_summary: str
    interests: str


def get_current_user(authorization: str = Header(..., alias="Authorization")):
    """Decode the JWT token from the Authorization header and return the payload."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload


@app.get("/")
def read_root():
    return {"message": "Hello, World"}


@app.post("/register")
def register(req: RegisterRequest):
    if req.email in users:
        raise HTTPException(status_code=400, detail="User already exists")
    hashed = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt())
    users[req.email] = {
        "first_name": req.first_name,
        "last_name": req.last_name,
        "school": req.school,
        "password": hashed,
        "role": "user",
        "approved": False,
    }
    return {"message": "Registration submitted. Awaiting admin approval"}


@app.post("/login")
def login(req: LoginRequest):
    user = users.get(req.email)
    if not user or not bcrypt.checkpw(req.password.encode(), user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("approved"):
        raise HTTPException(status_code=403, detail="User not approved")
    payload = {
        "sub": req.email,
        "role": user["role"],
        "exp": datetime.utcnow() + timedelta(hours=1),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)
    return {"token": token}


@app.post("/approve")
def approve(req: ApproveRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    user = users.get(req.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user["approved"] = True
    return {"message": f"{req.email} approved"}


@app.post("/reject")
def reject(req: RejectRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    user = users.get(req.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user["rejected"] = True
    return {"message": f"{req.email} rejected"}


@app.get("/pending-users")
def pending_users(current_user: dict = Depends(get_current_user)):
    """Return all users who have not yet been approved."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return [
        {"email": email, **{k: v for k, v in info.items() if k != "password"}}
        for email, info in users.items()
        if not info.get("approved") and not info.get("rejected")
    ]


@app.post("/students")
def create_student(
    student: StudentRequest, current_user: dict = Depends(get_current_user)
):
    """Create a student record with embedding and store in Redis."""
    combined = " ".join(
        [
            ", ".join(student.skills),
            student.experience_summary,
            student.interests,
        ]
    )
    try:
        resp = openai.embeddings.create(input=combined, model="text-embedding-3-small")
        embedding = resp.data[0].embedding
    except Exception:
        raise HTTPException(status_code=500, detail="Embedding generation failed")

    data = student.model_dump()
    data["embedding"] = embedding
    redis_client.set(student.email, json.dumps(data))
    return {"message": "Student stored"}
