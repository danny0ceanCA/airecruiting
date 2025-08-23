"""Application entry point.

This module initialises the :class:`FastAPI` application, configures
middleware, and exposes several utility objects (JWT settings, the Redis
client, and ``init_default_admin``) used throughout the tests.  Authentication
routes are defined in :mod:`app.routes.auth` and included here.
"""

from __future__ import annotations

import json

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


load_dotenv()

# ---------------------------------------------------------------------------
# Global settings used by the auth routes and tests
# ---------------------------------------------------------------------------

JWT_SECRET = "secret"
ALGORITHM = "HS256"
redis_client = None  # replaced by tests with a dummy implementation


def init_default_admin() -> None:
    """Ensure a default administrator account exists in Redis."""

    if redis_client is None:
        return

    key = "user:admin@example.com"
    if not redis_client.exists(key):
        admin = {
            "email": "admin@example.com",
            "first_name": "Admin",
            "last_name": "User",
            "password": "admin123",
            "role": "admin",
            "approved": True,
            "rejected": False,
        }
        redis_client.set(key, json.dumps(admin))


# ---------------------------------------------------------------------------
# FastAPI application setup
# ---------------------------------------------------------------------------

app = FastAPI()


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "Hello, World"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from app.routes import auth, admin, students, jobs, matching, notes


app.include_router(auth.router)
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(students.router, prefix="/students", tags=["students"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(matching.router, prefix="/matching", tags=["matching"])
app.include_router(notes.router, prefix="/notes", tags=["notes"])

