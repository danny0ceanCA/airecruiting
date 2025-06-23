from datetime import datetime, timedelta
import json
import csv
import os
import uuid
from typing import Optional
from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Header,
    Request,
    UploadFile,
    File,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from jose import jwt, JWTError
from dotenv import load_dotenv
import bcrypt
from openai import OpenAI
import redis
from backend.app.schemas.resume import ResumeRequest
from backend.app.services.resume import generate_resume_text

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
    keys = redis_client.keys("match_results:*")
    print(f"🔎 Found {len(keys)} saved match sets at startup.")

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
async def create_student(request: Request, current_user: dict = Depends(get_current_user)):
    content_type = request.headers.get("content-type", "")
    resume_file: UploadFile | None = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        resume_file = form.get("resume")
        skills_field = form.get("skills", "")
        student_data = StudentRequest(
            first_name=form.get("first_name"),
            last_name=form.get("last_name"),
            email=form.get("email"),
            phone=form.get("phone"),
            education_level=form.get("education_level"),
            skills=[s.strip() for s in skills_field.split(",") if s.strip()],
            experience_summary=form.get("experience_summary"),
            interests=form.get("interests"),
        )
    else:
        body = await request.json()
        student_data = StudentRequest(**body)

    if redis_client.exists(student_data.email):
        raise HTTPException(status_code=400, detail="Student already exists")

    resume_text = ""
    if resume_file is not None:
        ext = os.path.splitext(resume_file.filename or "")[1].lower()
        try:
            if ext == ".pdf":
                import pdfplumber

                with pdfplumber.open(resume_file.file) as pdf:
                    pages = [page.extract_text() or "" for page in pdf.pages]
                resume_text = "\n".join(pages)
            elif ext in {".docx", ".doc"}:
                from docx import Document

                document = Document(resume_file.file)
                resume_text = "\n".join(p.text for p in document.paragraphs)
            elif ext:
                raise HTTPException(status_code=400, detail="Unsupported resume type")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse resume: {e}")

    combined = " ".join([
        ", ".join(student_data.skills),
        student_data.experience_summary,
        student_data.interests,
    ])
    try:
        resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
        embedding = resp.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")

    data = student_data.model_dump()
    data["embedding"] = embedding
    redis_client.set(f"student:{student_data.email}", json.dumps(data))

    message = "Student stored" if resume_file is not None else "Student profile submitted without resume."
    return {"message": message, "resume_text": resume_text}

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


@app.put("/jobs/{job_code}")
def update_job(job_code: str, updated: dict, token_data: dict = Depends(get_current_user)):
    key = f"job:{job_code}"
    raw = redis_client.get(key)

    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    job = json.loads(raw)

    if token_data.get("role") != "admin" and token_data.get("sub") != job.get("posted_by"):
        raise HTTPException(status_code=403, detail="Not authorized to edit this job")

    job.update(updated)
    redis_client.set(key, json.dumps(job))
    print(f"✏️ Updated job {job_code}")
    return {"message": "Job updated"}

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

    assigned = set(job.get("assigned_students", []))
    placed = set(job.get("placed_students", []))
    for m in top_matches:
        if m["email"] in placed:
            m["status"] = "placed"
        elif m["email"] in assigned:
            m["status"] = "assigned"
        else:
            m["status"] = None

    redis_client.set(
        f"match_results:{req.job_code}", json.dumps(top_matches)
    )
    print(
        f"✅ Stored {len(top_matches)} matches for job {req.job_code}"
    )

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


@app.get("/match/{job_code}")
def get_match_results(job_code: str, current_user: dict = Depends(get_current_user)):
    key = f"match_results:{job_code}"
    results_json = redis_client.get(key)

    if results_json is None:
        print(f"⚠️ No match results found for job {job_code}")
        return {"matches": []}

    try:
        matches = json.loads(results_json)
        print(f"📦 Returning {len(matches)} stored matches for job {job_code}")

        job_raw = redis_client.get(f"job:{job_code}")
        if not job_raw:
            raise HTTPException(status_code=404, detail="Job not found")

        job = json.loads(job_raw)
        assigned = set(job.get("assigned_students", []))
        placed = set(job.get("placed_students", []))

        for m in matches:
            if m["email"] in placed:
                m["status"] = "placed"
            elif m["email"] in assigned:
                m["status"] = "assigned"
            else:
                m["status"] = None

        return {"matches": matches}
    except Exception as e:
        print(f"❌ Failed to load match results for {job_code}: {e}")
        return {"matches": []}


@app.get("/has-match/{job_code}")
def has_match_data(job_code: str):
    exists = redis_client.exists(f"match_results:{job_code}")
    return {"has_match": bool(exists)}

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
def place_student(data: dict, token_data: dict = Depends(get_current_user)):
    job_code = data["job_code"]
    student_email = data["student_email"]
    key = f"job:{job_code}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    job = json.loads(raw)
    job.setdefault("placed_students", [])
    job.setdefault("assigned_students", [])

    if student_email not in job["placed_students"]:
        job["placed_students"].append(student_email)
    if student_email in job["assigned_students"]:
        job["assigned_students"].remove(student_email)

    redis_client.set(key, json.dumps(job))
    return {"message": f"Placed {student_email}"}

@app.post("/assign")
def assign_student(data: dict, token_data: dict = Depends(get_current_user)):
    job_code = data["job_code"]
    student_email = data["student_email"]
    key = f"job:{job_code}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")

    job = json.loads(raw)
    job.setdefault("assigned_students", [])
    if student_email not in job["assigned_students"]:
        job["assigned_students"].append(student_email)

    redis_client.set(key, json.dumps(job))
    return {"message": f"Assigned {student_email}"}


@app.post("/generate-resume")
def generate_resume(req: ResumeRequest, current_user: dict = Depends(get_current_user)):
    """
    Generates a text resume using OpenAI and stores it in Redis.
    Does not regenerate if it already exists.
    """
    print(f"\U0001F4C4 Generating resume for {req.student_email} - {req.job_code}")
    resume_key = f"resume:{req.job_code}:{req.student_email}"
    existing = redis_client.get(resume_key)
    if existing:
        print(f"\U0001F4C4 Resume already exists for {req.student_email} - {req.job_code}")
        return {"status": "exists"}

    job_raw = redis_client.get(f"job:{req.job_code}")
    student_raw = redis_client.get(f"student:{req.student_email}")
    if not job_raw or not student_raw:
        print("\u274C Job or student not found")
        raise HTTPException(status_code=404, detail="Job or student not found")

    job = json.loads(job_raw)
    student = json.loads(student_raw)

    generated_resume = generate_resume_text(client, student, job)

    redis_client.set(resume_key, generated_resume)
    print(f"\u2705 Resume saved for {req.student_email} - {req.job_code}")
    return {"status": "success", "message": "Resume stored in Redis"}


@app.get("/resume/{job_code}/{student_email}")
def get_resume(job_code: str, student_email: str, current_user: dict = Depends(get_current_user)):
    key = f"resume:{job_code}:{student_email}"
    print(f"\U0001F4E5 Download request for resume: {job_code} - {student_email}")
    resume = redis_client.get(key)

    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    print("\u2705 Resume found and returned as plain text")
    return {
        "status": "success",
        "job_code": job_code,
        "student_email": student_email,
        "resume": resume if isinstance(resume, str) else resume.decode("utf-8"),
    }






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


@app.delete("/admin/reset-jobs")
def reset_jobs(current_user: dict = Depends(get_current_user)):
    """Delete all job postings and their stored match results."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")

    deleted = 0
    for key in list(redis_client.scan_iter("job:*")):
        redis_client.delete(key)
        deleted += 1
    for key in list(redis_client.scan_iter("match_results:*")):
        redis_client.delete(key)

    return {"message": f"Deleted {deleted} jobs and match data"}
