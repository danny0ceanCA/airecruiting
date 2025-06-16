from datetime import datetime, timedelta
import json
import csv
import os

from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from jose import jwt, JWTError
from dotenv import load_dotenv
import bcrypt
import openai
import redis

# Load environment variables
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
redis_url = os.getenv("REDIS_URL")

if not redis_url:
    raise RuntimeError("Missing REDIS_URL in .env")
if not openai.api_key:
    raise RuntimeError("Missing OPENAI_API_KEY in .env")

# Redis connection
redis_client = redis.Redis.from_url(redis_url, decode_responses=True)

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

# In-memory user store
users = {}

def init_default_admin():
    """Seed default admin user."""
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

# -------- Models -------- #
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

class JobRequest(BaseModel):
    job_title: str
    job_description: str
    desired_skills: list[str]
    job_code: str
    source: str
    rate_of_pay_range: str

class JobCodeRequest(BaseModel):
    job_code: str

# -------- Auth -------- #
def get_current_user(authorization: str = Header(..., alias="Authorization")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload

# -------- Routes -------- #
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
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return [
        {"email": email, **{k: v for k, v in info.items() if k != "password"}}
        for email, info in users.items()
        if not info.get("approved") and not info.get("rejected")
    ]

@app.post("/students")
def create_student(student: StudentRequest, current_user: dict = Depends(get_current_user)):
    if redis_client.exists(student.email):
        raise HTTPException(status_code=400, detail="Student already exists")

    combined = " ".join([
        ", ".join(student.skills),
        student.experience_summary,
        student.interests
    ])
    try:
        resp = openai.embeddings.create(input=combined, model="text-embedding-3-small")
        embedding = resp["data"][0]["embedding"] if isinstance(resp, dict) else resp.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")

    data = student.model_dump()
    data["embedding"] = embedding
    redis_client.set(student.email, json.dumps(data))
    return {"message": "Student stored"}

@app.post("/students/upload")
def upload_students(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    content = file.file.read().decode("utf-8").splitlines()
    reader = csv.DictReader(content)
    count = 0
    for row in reader:
        try:
            skills = [s.strip() for s in row.get("skills", "").split(",") if s.strip()]
            student = StudentRequest(
                first_name=row["first_name"],
                last_name=row["last_name"],
                email=row["email"],
                phone=row["phone"],
                education_level=row["education_level"],
                skills=skills,
                experience_summary=row["experience_summary"],
                interests=row["interests"],
            )
        except KeyError:
            continue

        if redis_client.exists(student.email):
            redis_client.delete(student.email)

        combined = " ".join([
            ", ".join(student.skills),
            student.experience_summary,
            student.interests
        ])
        try:
            resp = openai.embeddings.create(input=combined, model="text-embedding-3-small")
            embedding = resp["data"][0]["embedding"] if isinstance(resp, dict) else resp.data[0].embedding
        except Exception as e:
            continue  # Skip failed entries

        data = student.model_dump()
        data["embedding"] = embedding
        redis_client.set(student.email, json.dumps(data))
        count += 1

    return {"message": f"Processed {count} students", "count": count}


@app.post("/jobs")
def create_job(job: JobRequest, current_user: dict = Depends(get_current_user)):
    key = f"job:{job.job_code}"
    if redis_client.exists(key):
        raise HTTPException(status_code=400, detail="Job already exists")

    data = job.model_dump()
    data["posted_by"] = current_user.get("sub")
    data["timestamp"] = datetime.now().isoformat()
    redis_client.set(key, json.dumps(data))
    return {"message": "Job stored"}


@app.post("/match")
def match_job(req: JobCodeRequest, current_user: dict = Depends(get_current_user)):
    key = f"job:{req.job_code}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")
    job = json.loads(raw)

    combined = job.get("job_description", "") + " " + " ".join(job.get("desired_skills", []))
    try:
        resp = openai.embeddings.create(input=combined, model="text-embedding-3-small")
        job_emb = resp["data"][0]["embedding"] if isinstance(resp, dict) else resp.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")

    matches = []
    for key in redis_client.scan_iter("*"):
        if str(key).startswith("job:"):
            continue
        student_raw = redis_client.get(key)
        if not student_raw:
            continue
        try:
            student = json.loads(student_raw)
            emb = student.get("embedding")
            if not emb:
                continue
            score = sum(a * b for a, b in zip(job_emb, emb))
            matches.append({
                "name": f"{student.get('first_name', '')} {student.get('last_name', '')}",
                "email": student.get("email"),
                "score": score,
            })
        except Exception:
            continue

    matches.sort(key=lambda x: x["score"], reverse=True)
    return {"matches": matches[:5]}
