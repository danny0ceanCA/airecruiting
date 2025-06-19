from datetime import datetime, timedelta
import json
import csv
import os
import uuid
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from jose import jwt, JWTError
from dotenv import load_dotenv
import bcrypt
from openai import OpenAI
import redis

# Load environment variables
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
redis_url = os.getenv("REDIS_URL")

if not redis_url:
    raise RuntimeError("Missing REDIS_URL in .env")

# Redis connection
redis_client = redis.Redis.from_url(redis_url, decode_responses=True)

JWT_SECRET = "secret"
ALGORITHM = "HS256"

app = FastAPI()

# Simple request logging for debugging
@app.middleware("http")
async def log_requests(request, call_next):
    print(f"Incoming {request.method} {request.url}")
    response = await call_next(request)
    print(f"Response status: {response.status_code}")
    return response

@app.get("/routes")
def list_routes():
    return [route.path for route in app.routes]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- User Utilities ----- #

def init_default_admin():
    key = "user:admin@example.com"
    if not redis_client.exists(key):
        hashed = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode()
        redis_client.set(
            key,
            json.dumps(
                {
                    "first_name": "Admin",
                    "last_name": "User",
                    "school": "Admin School",
                    "password": hashed,
                    "role": "admin",
                    "approved": True,
                    "rejected": False,
                }
            ),
        )
        print("Default admin user created")

@app.on_event("startup")
def on_startup():
    # Verify Redis connection and seed the default admin
    try:
        redis_client.ping()
        print("Redis connection established")
    except Exception as e:
        print(f"Redis connection failed: {e}")
        raise
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
    job_code: Optional[str] = None
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
    key = f"user:{req.email}"
    if redis_client.exists(key):
        raise HTTPException(status_code=400, detail="User already exists")

    hashed = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    redis_client.set(
        key,
        json.dumps(
            {
                "first_name": req.first_name,
                "last_name": req.last_name,
                "school": req.school,
                "password": hashed,
                "role": "user",
                "approved": False,
                "rejected": False,
            }
        ),
    )
    return {"message": "Registration submitted. Awaiting admin approval"}

@app.post("/login")
def login(req: LoginRequest):
    print(f"Login attempt for {req.email}")
    key = f"user:{req.email}"
    raw = redis_client.get(key)
    print(f"User found: {bool(raw)}")
    if not raw:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = json.loads(raw)
    stored_pw = user.get("password", "").encode()
    if bcrypt.checkpw(req.password.encode(), stored_pw):
        print("Password match")
    else:
        print("Password mismatch")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("approved"):
        raise HTTPException(status_code=403, detail="User not approved")

    payload = {
        "sub": req.email,
        "role": user["role"],
        "exp": datetime.utcnow() + timedelta(hours=1),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)
    print(f"Login successful for {req.email}")
    return {"token": token}

@app.post("/approve")
def approve(req: ApproveRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"user:{req.email}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="User not found")
    user = json.loads(raw)
    user["approved"] = True
    redis_client.set(key, json.dumps(user))
    return {"message": f"{req.email} approved"}

@app.post("/reject")
def reject(req: RejectRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"user:{req.email}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="User not found")
    user = json.loads(raw)
    user["rejected"] = True
    redis_client.set(key, json.dumps(user))
    return {"message": f"{req.email} rejected"}

@app.get("/pending-users")
def pending_users(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    pending = []
    for key in redis_client.scan_iter("user:*"):
        raw = redis_client.get(key)
        if not raw:
            continue
        info = json.loads(raw)
        if info.get("approved") or info.get("rejected"):
            continue
        email = key.split("user:", 1)[1]
        pending.append({"email": email, **{k: v for k, v in info.items() if k != "password"}})
    return pending

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
        resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
        embedding = resp.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")

    data = student.model_dump()
    data["embedding"] = embedding
    redis_client.set(f"student:{student.email}", json.dumps(data))
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
            resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
            embedding = resp.data[0].embedding
        except Exception:
            continue

        data = student.model_dump()
        data["embedding"] = embedding
        redis_client.set(f"student:{student.email}", json.dumps(data))

        count += 1

    return {"message": f"Processed {count} students", "count": count}

@app.post("/jobs")
def create_job(job: JobRequest, current_user: dict = Depends(get_current_user)):
    generated_code = str(uuid.uuid4())[:8]
    key = f"job:{generated_code}"
    # Ensure the generated job code does not collide with an existing key
    while redis_client.exists(key):
        generated_code = str(uuid.uuid4())[:8]
        key = f"job:{generated_code}"

    data = job.model_dump()
    data["job_code"] = generated_code
    data["posted_by"] = current_user.get("sub")
    data["timestamp"] = datetime.now().isoformat()
    data.setdefault("assigned_students", [])
    data.setdefault("placed_students", [])

    redis_client.set(key, json.dumps(data))
    print(f"Stored job at {key}: {data}")
    return {"message": "Job stored", "job_code": generated_code}

@app.post("/match")
def match_job(req: JobCodeRequest, current_user: dict = Depends(get_current_user)):
    key = f"job:{req.job_code}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")
    job = json.loads(raw)

    combined = job.get("job_description", "") + " " + ", ".join(job.get("desired_skills", []))
    try:
        resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
        job_emb = resp.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")

    matches = []
    for key in redis_client.scan_iter("*"):
        if str(key).startswith("job:") or str(key).startswith("user:"):
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
    top_matches = matches[:5]

    # Metrics tracking
    try:
        avg_score = (
            sum(m["score"] for m in matches) / len(matches)
            if matches
            else 0.0
        )
        redis_client.incr("metrics:total_matches")
        redis_client.incrbyfloat("metrics:total_match_score", avg_score)
        redis_client.set(
            "metrics:last_match_timestamp", datetime.now().isoformat()
        )
    except Exception:
        pass

    return {"matches": top_matches}

@app.get("/jobs")
def list_jobs(current_user: dict = Depends(get_current_user)):
    jobs = []
    for key in redis_client.scan_iter("job:*"):
        job_data = redis_client.get(key)
        if job_data:
            job = json.loads(job_data)
            job.setdefault("assigned_students", [])
            job.setdefault("placed_students", [])
            jobs.append(job)
    print(f"Returning {len(jobs)} jobs from Redis")
    return {"jobs": jobs}


@app.get("/metrics")
def get_metrics(current_user: dict = Depends(get_current_user)):
    """Return various application metrics."""
    total_users = 0
    approved = 0
    rejected = 0
    pending = 0
    for key in redis_client.scan_iter("user:*"):
        raw = redis_client.get(key)
        if not raw:
            continue
        total_users += 1
        info = json.loads(raw)
        if info.get("approved"):
            approved += 1
        elif info.get("rejected"):
            rejected += 1
        else:
            pending += 1

    students = 0
    for key in redis_client.scan_iter("*"):
        skey = str(key)
        if skey.startswith("user:") or skey.startswith("job:") or skey.startswith(
            "metrics:"
        ):
            continue
        if redis_client.get(key):
            students += 1

    jobs = 0
    for key in redis_client.scan_iter("job:*"):
        if redis_client.get(key):
            jobs += 1

    (
        total_matches,
        total_match_score,
        total_placements,
        total_rematches,
        sum_time_to_place,
    ) = [
        redis_client.get(k)
        for k in [
            "metrics:total_matches",
            "metrics:total_match_score",
            "metrics:total_placements",
            "metrics:total_rematches",
            "metrics:sum_time_to_place",
        ]
    ]
    total_matches = int(total_matches or 0)
    total_match_score = float(total_match_score or 0.0)
    total_placements = int(total_placements or 0)
    total_rematches = int(total_rematches or 0)
    sum_time_to_place = float(sum_time_to_place or 0.0)

    avg_match_score = (
        total_match_score / total_matches if total_matches else None
    )
    latest_match_timestamp = redis_client.get("metrics:last_match_timestamp")

    placement_rate = (
        total_placements / students if students else 0
    )
    avg_time_to_place = (
        sum_time_to_place / total_placements if total_placements else 0.0
    )
    avg_time_to_place = round(avg_time_to_place, 1)
    rematch_rate = (
        total_rematches / total_placements if total_placements else 0
    )

    license_counts: dict[str, int] = {}
    license_keys = list(redis_client.scan_iter("metrics:licensed:*"))
    if license_keys:
        values = redis_client.mget(license_keys)
        for k, v in zip(license_keys, values):
            lic = k.split("metrics:licensed:", 1)[1]
            license_counts[lic] = int(v or 0)

    return {
        "total_users": total_users,
        "approved_users": approved,
        "rejected_users": rejected,
        "pending_registrations": pending,
        "total_student_profiles": students,
        "total_jobs_posted": jobs,
        "total_matches": total_matches,
        "average_match_score": avg_match_score,
        "latest_match_timestamp": latest_match_timestamp,
        "placement_rate": placement_rate,
        "avg_time_to_placement_days": avg_time_to_place,
        "license_breakdown": license_counts,
        "rematch_rate": rematch_rate,
    }


class PlacementRequest(BaseModel):
    student_email: EmailStr
    job_code: str


@app.post("/place")
def place_student(
    req: PlacementRequest, current_user: dict = Depends(get_current_user)
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")

    student_key = f"student:{req.student_email}"
    job_key = f"job:{req.job_code}"

    if not redis_client.exists(student_key):
        raise HTTPException(status_code=404, detail="Student not found")
    if not redis_client.exists(job_key):
        raise HTTPException(status_code=404, detail="Job not found")

    student_raw = redis_client.get(student_key)
    student = json.loads(student_raw) if student_raw else {}

    student["placed"] = True

    history = student.get("placement_history", [])
    entry = {"job_code": req.job_code, "placed_at": datetime.now().isoformat()}
    history.append(entry)
    student["placement_history"] = history

    placement_count = int(student.get("placement_count", 0)) + 1
    student["placement_count"] = placement_count

    redis_client.set(student_key, json.dumps(student))

    redis_client.incr("metrics:total_placements")
    if placement_count > 1:
        redis_client.incr("metrics:total_rematches")

    created_at = student.get("created_at")
    if created_at:
        try:
            created_dt = datetime.fromisoformat(created_at)
            days = (datetime.now() - created_dt).total_seconds() / 86400
            redis_client.incrbyfloat("metrics:sum_time_to_place", days)
        except Exception:
            pass

    license_type = student.get("license_type")
    if license_type:
        redis_client.incr(f"metrics:licensed:{license_type}")

    return {"message": "Placement recorded", "rematch": placement_count > 1}


@app.post("/assign")
async def assign_student(payload: dict, current_user: dict = Depends(get_current_user)):
    print("✅ /assign route was called")

    student_email = payload.get("student_email")
    job_code = payload.get("job_code")
    print("Assigning student_email:", student_email)
    print("Assigning job_code:", job_code)

    # ✅ Now uses consistent Redis key prefix
    student_key = f"student:{student_email}"
    job_key = f"job:{job_code}"

    print("Checking Redis for:")
    print(" -", student_key, "exists?", redis_client.exists(student_key))
    print(" -", job_key, "exists?", redis_client.exists(job_key))

    if not redis_client.exists(student_key):
        raise HTTPException(status_code=404, detail="Student not found")
    if not redis_client.exists(job_key):
        raise HTTPException(status_code=404, detail="Job not found")

    student_data = json.loads(redis_client.get(student_key))
    student_data.setdefault("assignment_history", [])
    student_data.setdefault("placement_count", 0)
    student_data.setdefault("status_by_job", {})

    if student_data["status_by_job"].get(job_code) in ("assigned", "placed"):
        return {"success": True, "message": "Already assigned"}

    student_data["assignment_history"].append({
        "job_code": job_code,
        "assigned_at": datetime.utcnow().isoformat()
    })
    student_data["status_by_job"][job_code] = "assigned"
    redis_client.set(student_key, json.dumps(student_data))

    job_data = json.loads(redis_client.get(job_key))
    job_data.setdefault("assigned_students", [])
    if student_email not in job_data["assigned_students"]:
        job_data["assigned_students"].append(student_email)
    redis_client.set(job_key, json.dumps(job_data))

    redis_client.incr("metrics:total_assignments")

    return {"success": True}

print("✅ FastAPI has registered /assign")



@app.get("/placements/{student_email}")
def get_placements(
    student_email: str, current_user: dict = Depends(get_current_user)
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")

    key = f"student:{student_email}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Student not found")

    raw = redis_client.get(key)
    student = json.loads(raw) if raw else {}
    return student.get("placement_history", [])
