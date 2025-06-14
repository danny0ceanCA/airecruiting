from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from jose import jwt, JWTError
import bcrypt

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
