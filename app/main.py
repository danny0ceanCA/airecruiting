from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import auth, admin, students, jobs, matching, notes

JWT_SECRET = "secret"
ALGORITHM = "HS256"
redis_client = None

def init_default_admin():
    """Placeholder for initializing a default admin user."""
    pass

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="", tags=["auth"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(students.router, prefix="/students", tags=["students"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(matching.router, prefix="/matching", tags=["matching"])
app.include_router(notes.router, prefix="/notes", tags=["notes"])
