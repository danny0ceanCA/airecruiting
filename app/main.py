from datetime import datetime, timedelta
import json
import csv
import os
import uuid
from typing import Optional
import smtplib
from email.message import EmailMessage
from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Header,
    Request,
    UploadFile,
    File,
)
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator, model_validator
from jose import jwt, JWTError
from dotenv import load_dotenv
import bcrypt
for _p in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
    os.environ.pop(_p, None)
import httpx
from openai import OpenAI
import redis
from backend.app.schemas.resume import ResumeRequest
from backend.app.schemas.description import DescriptionRequest
from backend.app.services.resume import generate_resume_text
from backend.app.services.description import generate_description_text
from backend.app.school_codes import SCHOOL_CODE_MAP


def init_default_school_codes():
    """Ensure Redis contains the default school codes with current labels."""
    for code, label in SCHOOL_CODE_MAP.items():
        key = f"school_code:{code}"
        existing = redis_client.get(key)
        if existing != label:
            redis_client.set(key, label)


def get_school_label(code: str) -> str | None:
    """Return label for a school code from redis or defaults."""
    label = redis_client.get(f"school_code:{code}")
    if label:
        return label
    return SCHOOL_CODE_MAP.get(code)


def all_school_codes() -> dict[str, str]:
    """Return mapping of all known school codes."""
    codes = {}
    for key in redis_client.scan_iter("school_code:*"):
        val = redis_client.get(key)
        if val is not None:
            c = key.split("school_code:", 1)[1]
            codes[c] = val
    for c, l in SCHOOL_CODE_MAP.items():
        codes.setdefault(c, l)
    return codes

# Load environment variables
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), http_client=httpx.Client())
redis_url = os.getenv("REDIS_URL")

# Email configuration
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")

if not redis_url:
    raise RuntimeError("Missing REDIS_URL in .env")

# Redis connection
redis_client = redis.Redis.from_url(redis_url, decode_responses=True)

# Key used to store activity log entries
ACTIVITY_LOG_KEY = "activity_logs"

def send_email(recipient: str, subject: str, body: str) -> None:
    """Send an email if SMTP configuration is available."""
    if not SMTP_HOST or not EMAIL_SENDER:
        print(f"[email] Skipping email to {recipient}; SMTP not configured")
        return
    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_SENDER
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            if SMTP_USER and SMTP_PASSWORD:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
        print(f"[email] Sent notification to {recipient}")
    except Exception as e:
        print(f"[email] Failed to send email to {recipient}: {e}")

def get_driving_distance_miles(orig_lat: float, orig_lng: float, dest_lat: float, dest_lng: float) -> float:
    """Return driving distance in miles between two coordinates using Google Distance Matrix."""
    key = os.getenv("GOOGLE_KEY")
    if not key:
        raise RuntimeError("Missing GOOGLE_KEY")
    params = {
        "origins": f"{orig_lat},{orig_lng}",
        "destinations": f"{dest_lat},{dest_lng}",
        "units": "imperial",
        "key": key,
    }
    resp = httpx.get("https://maps.googleapis.com/maps/api/distancematrix/json", params=params)
    data = resp.json()
    value_meters = data["rows"][0]["elements"][0]["distance"]["value"]
    return value_meters / 1609.34

JWT_SECRET = "secret"
ALGORITHM = "HS256"

app = FastAPI()

# Simple request logging and activity tracking
@app.middleware("http")
async def log_requests(request, call_next):
    print(f"Incoming {request.method} {request.url}")
    user = None
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        token = auth.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
            user = payload.get("sub")
        except JWTError:
            user = "invalid_token"

    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "method": request.method,
        "path": request.url.path,
        "user": user,
    }
    try:
        redis_client.rpush(ACTIVITY_LOG_KEY, json.dumps(log_entry))
    except Exception as e:
        print(f"Failed to store activity log: {e}")

    response = await call_next(request)
    print(f"Response status: {response.status_code}")
    return response

@app.get("/routes")
def list_routes():
    return [route.path for route in app.routes]

# Add CORS middleware BEFORE defining routes
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "https://airecruiting-frontend.onrender.com",
        "https://talentmatch-frontend-nacw.onrender.com",
        "https://talentmatch-ai.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional: Preflight catch-all
@app.options("/{rest_of_path:path}")
async def preflight_handler(rest_of_path: str):
    return {}

@app.get("/school-codes")
def school_codes():
    """Return available institutional codes."""
    codes = [{"code": c, "label": l} for c, l in all_school_codes().items()]
    return {"codes": codes}


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
                    "institutional_code": "Admin School",
                    "password": hashed,
                    "active": True,
                    "role": "admin",
                    "approved": True,
                    "rejected": False,
                }
            ),
        )
        print("Default admin user created")
    init_default_school_codes()

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
    init_default_school_codes()
    keys = redis_client.keys("match_results:*")
    print(f"🔎 Found {len(keys)} saved match sets at startup.")

# -------- Models -------- #
class RegisterRequest(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    institutional_code: str = Field(alias="school_code")
    password: str

    model_config = ConfigDict(populate_by_name=True)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class ApproveRequest(BaseModel):
    email: EmailStr
    role: str  # "career" or "recruiter"

class RejectRequest(BaseModel):
    email: EmailStr

class UpdateUserRequest(BaseModel):
    role: str | None = None
    institutional_code: str | None = Field(default=None, alias="school_code")
    active: bool | None = None

class StudentRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    phone: str
    education_level: str
    skills: list[str]
    experience_summary: str
    interests: str
    city: str
    state: str
    lat: float
    lng: float
    max_travel: float

    @field_validator("max_travel")
    @classmethod
    def check_travel(cls, v):
        if v <= 0:
            raise ValueError("max_travel must be positive")
        return v

class JobRequest(BaseModel):
    job_title: str
    job_description: str
    desired_skills: list[str]
    job_code: Optional[str] = None
    source: str
    min_pay: float
    max_pay: float
    city: str
    state: str
    lat: float
    lng: float

    @field_validator("min_pay", "max_pay")
    @classmethod
    def check_positive(cls, v):
        if v <= 0:
            raise ValueError("Pay must be positive")
        return v

    @model_validator(mode="after")
    def validate_range(self):
        if self.min_pay > self.max_pay:
            raise ValueError("Minimum pay cannot exceed maximum pay")
        return self

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

    label = get_school_label(req.institutional_code)
    if not label:
        raise HTTPException(
            status_code=400,
            detail="Invalid school code. Please contact your administrator.",
        )

    hashed = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    redis_client.set(
        key,
        json.dumps(
            {
                "first_name": req.first_name,
                "last_name": req.last_name,
                "institutional_code": req.institutional_code,
                "school_label": label,
                "password": hashed,
                "active": True,
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
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="User deactivated")

    payload = {
        "sub": req.email,
        "role": user["role"],
        "exp": datetime.utcnow() + timedelta(hours=1),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)
    print(f"Login successful for {req.email}")
    try:
        redis_client.rpush(
            ACTIVITY_LOG_KEY,
            json.dumps(
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "user": req.email,
                    "action": "login",
                }
            ),
        )
    except Exception as e:
        print(f"Failed to store login log: {e}")
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
    user["role"] = req.role
    redis_client.set(key, json.dumps(user))
    return {"message": f"{req.email} approved as {req.role}"}

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


@app.get("/admin/users")
def list_users(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    users = []
    for key in redis_client.scan_iter("user:*"):
        raw = redis_client.get(key)
        if not raw:
            continue
        data = json.loads(raw)
        email = key.split("user:", 1)[1]
        data.pop("password", None)
        users.append({"email": email, **data})
    return {"users": users}


@app.put("/admin/users/{email}")
def update_user(email: str, req: UpdateUserRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"user:{email}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="User not found")
    user = json.loads(raw)
    if req.role is not None:
        user["role"] = req.role
    if req.institutional_code is not None:
        label = get_school_label(req.institutional_code)
        if not label:
            raise HTTPException(status_code=400, detail="Invalid school code")
        user["institutional_code"] = req.institutional_code
        user["school_label"] = label
    if req.active is not None:
        user["active"] = req.active
    redis_client.set(key, json.dumps(user))
    return {"message": "User updated"}


@app.delete("/admin/users/{email}")
def delete_user(email: str, current_user: dict = Depends(get_current_user)):
    """Delete a user account."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")

    key = f"user:{email}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="User not found")

    redis_client.delete(key)
    return {"message": f"Deleted {email}"}


class SchoolCodeRequest(BaseModel):
    code: str
    label: str

class UpdateSchoolCodeRequest(BaseModel):
    label: str


@app.post("/admin/school-codes")
def add_school_code(
    req: SchoolCodeRequest, current_user: dict = Depends(get_current_user)
):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"school_code:{req.code}"
    if redis_client.exists(key):
        raise HTTPException(status_code=400, detail="Code already exists")
    redis_client.set(key, req.label)
    return {"message": "School code added"}


@app.put("/admin/school-codes/{code}")
def update_school_code(
    code: str, req: UpdateSchoolCodeRequest, current_user: dict = Depends(get_current_user)
):
    """Update the label for an existing school code."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"school_code:{code}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Code not found")
    redis_client.set(key, req.label)
    return {"message": "School code updated"}


@app.delete("/admin/school-codes/{code}")
def delete_school_code(code: str, current_user: dict = Depends(get_current_user)):
    """Delete a school code."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"school_code:{code}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Code not found")
    redis_client.delete(key)
    return {"message": "School code deleted"}

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
            city=form.get("city"),
            state=form.get("state"),
            lat=float(form.get("lat")),
            lng=float(form.get("lng")),
            max_travel=float(form.get("max_travel")),
        )
    else:
        body = await request.json()
        student_data = StudentRequest(**body)

    if current_user.get("role") == "applicant" and student_data.email != current_user.get("sub"):
        raise HTTPException(status_code=403, detail="Applicants can only create their own profile")

    if redis_client.exists(f"student:{student_data.email}"):
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

    profile_json = None
    if resume_text:
        try:
            instructions = (
                "Extract a student profile from the following resume text. "
                "Return JSON with these fields: first_name, last_name, email, phone, "
                "education_level, skills (as a list), experience_summary, and interests (as a list)."
            )
            completion = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": f"{instructions}\n\n{resume_text}"}],
                temperature=0.0,
            )
            profile_json = json.loads(completion.choices[0].message.content)
        except Exception:
            profile_json = None

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

    user_key = f"user:{current_user.get('sub')}"
    user_raw = redis_client.get(user_key)
    institutional_code = None
    school_label = None
    if user_raw:
        try:
            user_data = json.loads(user_raw)
            institutional_code = user_data.get("institutional_code")
            school_label = user_data.get("school_label")
        except Exception:
            institutional_code = None
            school_label = None

    data = student_data.model_dump()
    data["embedding"] = embedding
    if institutional_code is not None:
        data["institutional_code"] = institutional_code
    if school_label is not None:
        data["school_label"] = school_label
    redis_client.set(f"student:{student_data.email}", json.dumps(data))

    if profile_json is not None:
        return {"message": "Resume parsed by GPT successfully.", "profile": profile_json}
    else:
        return {"message": "Student profile submitted without GPT parsing."}


@app.put("/students/{email}")
def update_student(
    email: str, updated: StudentRequest, current_user: dict = Depends(get_current_user)
):
    key = f"student:{email}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Student not found")

    if current_user.get("role") == "applicant" and email != current_user.get("sub"):
        raise HTTPException(status_code=403, detail="Applicants can only edit their own profile")

    try:
        existing = json.loads(raw)
    except Exception:
        existing = {}

    combined = " ".join([
        ", ".join(updated.skills),
        updated.experience_summary,
        updated.interests,
    ])
    try:
        resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
        embedding = resp.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")

    data = updated.model_dump()
    data["email"] = email
    data["embedding"] = embedding
    inst_code = existing.get("institutional_code") or existing.get("school_code")
    school_label = existing.get("school_label")
    if inst_code is not None:
        data["institutional_code"] = inst_code
    if school_label is not None:
        data["school_label"] = school_label
    if "school_code" in existing:
        data["school_code"] = existing.get("school_code")

    redis_client.set(key, json.dumps(data))
    return {"message": "Student updated successfully"}

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
                city=row["city"],
                state=row["state"],
                lat=float(row["lat"]),
                lng=float(row["lng"]),
                max_travel=float(row["max_travel"]),
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

    if "min_pay" in updated or "max_pay" in updated:
        min_pay = float(updated.get("min_pay", job.get("min_pay", 0)))
        max_pay = float(updated.get("max_pay", job.get("max_pay", 0)))
        if min_pay <= 0 or max_pay <= 0 or min_pay > max_pay:
            raise HTTPException(status_code=400, detail="Invalid pay range")
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

    poster_code = None
    poster_raw = redis_client.get(f"user:{job.get('posted_by')}")
    if poster_raw:
        try:
            p_data = json.loads(poster_raw)
            poster_code = p_data.get("institutional_code") or p_data.get("school_code")
        except Exception:
            poster_code = None

    combined = job.get("job_description", "") + " " + ", ".join(job.get("desired_skills", []))
    try:
        resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
        job_emb = resp.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")

    matches = []
    for key in redis_client.scan_iter("student:*"):
        student_raw = redis_client.get(key)
        if not student_raw:
            continue
        try:
            student = json.loads(student_raw)
            emb = student.get("embedding")
            if not emb:
                continue

            student_user_raw = redis_client.get(f"user:{student.get('email')}")
            if student_user_raw and poster_code:
                try:
                    su = json.loads(student_user_raw)
                    stu_code = su.get("institutional_code") or su.get("school_code")
                    if su.get("role") == "applicant" and stu_code != poster_code:
                        continue
                except Exception:
                    pass
            dist = get_driving_distance_miles(
                student.get("lat"),
                student.get("lng"),
                job.get("lat"),
                job.get("lng"),
            )
            if dist > float(student.get("max_travel", 0)):
                continue
            score = sum(a * b for a, b in zip(job_emb, emb))
            matches.append({
                "name": f"{student.get('first_name', '')} {student.get('last_name', '')}",
                "email": student.get("email"),
                "score": score,
                "distance_miles": round(dist, 1),
            })
        except Exception:
            continue

    # Include applicant user records with a matching institutional code when no
    # student profile exists for them
    for ukey in redis_client.scan_iter("user:*"):
        u_raw = redis_client.get(ukey)
        if not u_raw:
            continue
        try:
            udata = json.loads(u_raw)
        except Exception:
            continue
        if udata.get("role") != "applicant" or not poster_code:
            continue
        ucode = udata.get("institutional_code") or udata.get("school_code")
        if ucode != poster_code:
            continue
        email = ukey.split("user:", 1)[1]
        if redis_client.exists(f"student:{email}"):
            continue
        matches.append(
            {
                "name": f"{udata.get('first_name', '')} {udata.get('last_name', '')}",
                "email": email,
                "score": 0.0,
                "distance_miles": None,
            }
        )

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

    for m in top_matches:
        send_email(
            m["email"],
            f"New Job Match: {job.get('job_title')}",
            (
                f"Hello {m['name']},\n\n"
                f"You have been matched with the job '{job.get('job_title')}'. "
                "Log in to view details."
            ),
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


@app.delete("/jobs/{job_code}")
def delete_job(job_code: str, token_data: dict = Depends(get_current_user)):
    if token_data.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    job_key = f"job:{job_code}"
    match_key = f"match_results:{job_code}"

    if not redis_client.exists(job_key):
        raise HTTPException(status_code=404, detail="Job not found")

    redis_client.delete(job_key)
    redis_client.delete(match_key)

    return {"message": f"Job {job_code} deleted successfully"}


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
        if (
            skey.startswith("user:")
            or skey.startswith("job:")
            or skey.startswith("metrics:")
            or skey.startswith("school_code:")
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
    if token_data.get("role") not in {"admin", "career"}:
        raise HTTPException(status_code=403, detail="Not authorized to place students")
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


@app.post("/generate-description")
def generate_description(req: DescriptionRequest, current_user: dict = Depends(get_current_user)):
    """Generate a short job description tailored to a student."""
    print(f"\U0001F4DD Generating description for {req.student_email} - {req.job_code}")
    desc_key = f"description:{req.job_code}:{req.student_email}"
    existing = redis_client.get(desc_key)
    if existing:
        print("\U0001F4DD Description already exists")
        return {"status": "exists", "description": existing}

    job_raw = redis_client.get(f"job:{req.job_code}")
    student_raw = redis_client.get(f"student:{req.student_email}")
    if not job_raw or not student_raw:
        raise HTTPException(status_code=404, detail="Job or student not found")

    job = json.loads(job_raw)
    student = json.loads(student_raw)

    generated_desc = generate_description_text(client, student, job)
    redis_client.set(desc_key, generated_desc)
    print("\u2705 Description stored")
    return {"status": "success", "description": generated_desc}


@app.post("/generate-job-description")
def generate_job_description(req: ResumeRequest, current_user: dict = Depends(get_current_user)):
    job_code = req.job_code
    student_email = req.student_email
    key = f"job_description:{job_code}:{student_email}"
    html_key = f"jobdesc:{job_code}:{student_email}"
    existing = redis_client.get(key)
    if existing:
        redis_client.set(html_key, existing)
        return {"status": "exists"}

    job_raw = redis_client.get(f"job:{job_code}")
    student_raw = redis_client.get(f"student:{student_email}")
    if not job_raw or not student_raw:
        raise HTTPException(status_code=404, detail="Job or student not found")

    job = json.loads(job_raw)
    student = json.loads(student_raw)

    prompt = f"""
You are generating a job description document for internal career services staff. The purpose is to describe what the student will likely be expected to perform based on their background and the job assignment.

Use the student profile and job information below to:

- Write a **professional summary** of the student's fit for the role with extensive and relevant details
- Describe **key responsibilities** they might undertake as noted in the job description
- List **areas of strength** with plenty of details to reinforce existing experience and how it connects with the job description and potential **areas for growth** with plenty of insightful and targeted recommendations for training that will improve the probability of success
- Mention **school affiliation** and any relevant compliance or readiness info

Format this as a printable HTML document titled "TalentMatch AI", styled professionally but without producing binary output.

Student Info:
Name: {student.get('first_name')} {student.get('last_name')}
Email: {student.get('email')}
Skills: {', '.join(student.get('skills', []))}
Experience Summary: {student.get('experience_summary')}
Interests: {student.get('interests')}

Job Info:
Title: {job.get('job_title')}
Source: {job.get('source')}
Description: {job.get('job_description')}
Desired Skills: {', '.join(job.get('desired_skills', []))}

Output only valid HTML.
"""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
    )

    raw_content = resp.choices[0].message.content.strip()

    # Clean up Markdown-style ```html block
    if raw_content.startswith("```html"):
        raw_content = raw_content.replace("```html", "", 1).strip()
    if raw_content.endswith("```"):
        raw_content = raw_content.rsplit("```", 1)[0].strip()

    # Wrap in HTML layout
    full_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>TalentMatch AI – Job Description</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      margin: 2rem;
      line-height: 1.6;
    }}
    h2 {{
      color: #1a1a1a;
      border-bottom: 2px solid #eee;
      padding-bottom: 0.3rem;
    }}
    .section {{
      margin-bottom: 1.5rem;
    }}
  </style>
</head>
<body>
{raw_content}
</body>
</html>
"""

    redis_client.set(key, full_html)
    redis_client.set(html_key, full_html)
    return {"status": "success"}


@app.get("/job-description/{job_code}/{student_email}")
def get_job_description(job_code: str, student_email: str, current_user: dict = Depends(get_current_user)):
    key = f"job_description:{job_code}:{student_email}"
    description = redis_client.get(key)
    if not description:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "success", "description": description}


@app.get("/job-description-html/{job_code}/{student_email}")
def get_job_description_html(job_code: str, student_email: str, current_user: dict = Depends(get_current_user)):
    key = f"jobdesc:{job_code}:{student_email}"
    html = redis_client.get(key)
    if not html:
        raise HTTPException(status_code=404, detail="Job description not found")
    return HTMLResponse(content=html, status_code=200)


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


@app.delete("/admin/delete-student/{email}")
def delete_student(email: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")

    student_key = f"student:{email}"
    if not redis_client.exists(student_key):
        raise HTTPException(status_code=404, detail="Student not found")

    # Delete student profile
    redis_client.delete(student_key)

    # Clean up from job assignments/placements
    for job_key in redis_client.scan_iter("job:*"):
        raw = redis_client.get(job_key)
        if not raw:
            continue
        try:
            job = json.loads(raw)
        except Exception:
            continue

        assigned = job.get("assigned_students", [])
        placed = job.get("placed_students", [])

        updated = False
        if email in assigned:
            job["assigned_students"] = [e for e in assigned if e != email]
            updated = True
        if email in placed:
            job["placed_students"] = [e for e in placed if e != email]
            updated = True

        if updated:
            redis_client.set(job_key, json.dumps(job))

    # Remove resume if it exists
    for key in redis_client.scan_iter(f"resume:*:{email}"):
        redis_client.delete(key)

    # Remove job descriptions if any
    for key in redis_client.scan_iter(f"job_description:*:{email}"):
        redis_client.delete(key)

    # (Optional) Clean match results if student appears
    for match_key in redis_client.scan_iter("match_results:*"):
        raw = redis_client.get(match_key)
        if not raw:
            continue
        try:
            matches = json.loads(raw)
            new_matches = [m for m in matches if m.get("email") != email]
            if len(new_matches) != len(matches):
                redis_client.set(match_key, json.dumps(new_matches))
        except Exception:
            continue

    return {"message": f"Student {email} and related data deleted successfully"}

@app.get("/students/all")
def get_all_students(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")

    # Gather all job data once
    all_jobs = []
    for job_key in redis_client.scan_iter("job:*"):
        job_raw = redis_client.get(job_key)
        if not job_raw:
            continue
        try:
            job = json.loads(job_raw)
        except Exception:
            continue
        all_jobs.append(job)

    students = []
    for key in redis_client.scan_iter("student:*"):
        raw = redis_client.get(key)
        if not raw:
            continue
        try:
            student = json.loads(raw)
        except Exception:
            continue

        email = student.get("email")
        info = {
            "first_name": student.get("first_name"),
            "last_name": student.get("last_name"),
            "email": email,
            "phone": student.get("phone"),
            "education_level": student.get("education_level"),
            "skills": student.get("skills"),
            "experience_summary": student.get("experience_summary"),
            "interests": student.get("interests"),
            "institutional_code": student.get("institutional_code"),  # ✅ Added
            "assigned_jobs": [],
            "placed_jobs": 0,
            "assigned_job_code": None,
        }

        # Add optional match data
        info["assigned_jobs"] = [
            {
                "job_code": job.get("job_code"),
                "job_title": job.get("job_title"),
                "source": job.get("source"),
                "min_pay": job.get("min_pay"),
                "max_pay": job.get("max_pay"),
                "job_description": job.get("job_description"),
            }
            for job in all_jobs
            if email in job.get("assigned_students", [])
        ]
        info["placed_jobs"] = sum(
            1 for job in all_jobs if email in job.get("placed_students", [])
        )
        if info["assigned_jobs"]:
            info["assigned_job_code"] = info["assigned_jobs"][0]["job_code"]

        students.append(info)

    return {"students": students}

@app.get("/students/by-school")
def students_by_school(current_user: dict = Depends(get_current_user)):
    """Return all student profiles belonging to the current user's school."""
    user_key = f"user:{current_user.get('sub')}"
    raw_user = redis_client.get(user_key)
    if not raw_user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        user = json.loads(raw_user)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupted user data")

    institutional_code = user.get("institutional_code")

    # Gather all job data once
    all_jobs = []
    for job_key in redis_client.scan_iter("job:*"):
        job_raw = redis_client.get(job_key)
        if not job_raw:
            continue
        try:
            job = json.loads(job_raw)
        except Exception:
            continue
        all_jobs.append(job)

    students = []

    for key in redis_client.scan_iter("student:*"):
        raw = redis_client.get(key)
        if not raw:
            continue
        try:
            student = json.loads(raw)
        except Exception:
            continue

        if student.get("institutional_code") != institutional_code:
            continue

        email = student.get("email")
        info = {
            "first_name": student.get("first_name"),
            "last_name": student.get("last_name"),
            "email": email,
            "phone": student.get("phone"),
            "education_level": student.get("education_level"),
            "skills": student.get("skills"),
            "experience_summary": student.get("experience_summary"),
            "interests": student.get("interests"),
            "assigned_jobs": [],
            "placed_jobs": 0,
            "assigned_job_code": None,
        }

        # Add assigned/placed jobs info
        info["assigned_jobs"] = [
            {
                "job_code": job.get("job_code"),
                "job_title": job.get("job_title"),
                "source": job.get("source"),
                "min_pay": job.get("min_pay"),
                "max_pay": job.get("max_pay"),
                "job_description": job.get("job_description"),
            }
            for job in all_jobs
            if email in job.get("assigned_students", [])
        ]
        info["placed_jobs"] = sum(
            1 for job in all_jobs if email in job.get("placed_students", [])
        )
        if info["assigned_jobs"]:
            info["assigned_job_code"] = info["assigned_jobs"][0]["job_code"]

        students.append(info)

    return {"students": students}


@app.get("/students/me")
def student_me(current_user: dict = Depends(get_current_user)):
    """Return the logged-in applicant's student profile."""
    email = current_user.get("sub")
    key = f"student:{email}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Profile not found")

    try:
        student = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupted profile data")

    # gather related job info
    assigned_jobs = []
    placed = 0
    for job_key in redis_client.scan_iter("job:*"):
        job_raw = redis_client.get(job_key)
        if not job_raw:
            continue
        try:
            job = json.loads(job_raw)
        except Exception:
            continue
        if email in job.get("assigned_students", []):
            assigned_jobs.append({
                "job_code": job.get("job_code"),
                "job_title": job.get("job_title"),
                "source": job.get("source"),
                "min_pay": job.get("min_pay"),
                "max_pay": job.get("max_pay"),
                "job_description": job.get("job_description"),
            })
        if email in job.get("placed_students", []):
            placed += 1

    info = {
        **{k: student.get(k) for k in [
            "first_name",
            "last_name",
            "email",
            "phone",
            "education_level",
            "skills",
            "experience_summary",
            "interests",
            "institutional_code",
        ]},
        "assigned_jobs": assigned_jobs,
        "placed_jobs": placed,
        "assigned_job_code": assigned_jobs[0]["job_code"] if assigned_jobs else None,
    }
    return info

@app.get("/dev/check-admin")
def check_admin():
    raw = redis_client.get("user:admin@example.com")
    if not raw:
        return {"exists": False}
    return json.loads(raw)


@app.get("/activity-log")
def activity_log(limit: int = 100, current_user: dict = Depends(get_current_user)):
    """Return recent activity log entries."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")

    try:
        raw_entries = redis_client.lrange(ACTIVITY_LOG_KEY, -limit, -1) or []
        entries = [json.loads(e) for e in raw_entries if e]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read activity log: {e}")

    return {"entries": entries}
