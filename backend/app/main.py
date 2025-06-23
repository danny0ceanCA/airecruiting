from app.main import *  # re-export everything from the main application

from fastapi import Depends
import json


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

    school_code = user.get("school_code")

    # Build quick lookup for assigned and placed job counts
    assigned_counts: dict[str, int] = {}
    placed_counts: dict[str, int] = {}
    for job_key in redis_client.scan_iter("job:*"):
        job_raw = redis_client.get(job_key)
        if not job_raw:
            continue
        try:
            job = json.loads(job_raw)
        except Exception:
            continue
        for email in job.get("assigned_students", []):
            assigned_counts[email] = assigned_counts.get(email, 0) + 1
        for email in job.get("placed_students", []):
            placed_counts[email] = placed_counts.get(email, 0) + 1

    students = []
    for key in redis_client.scan_iter("student:*"):
        raw = redis_client.get(key)
        if not raw:
            continue
        try:
            student = json.loads(raw)
        except Exception:
            continue

        if student.get("school_code") != school_code:
            continue

        email = student.get("email")
        info = {
            "first_name": student.get("first_name"),
            "last_name": student.get("last_name"),
            "email": email,
            "education_level": student.get("education_level"),
        }

        if email in assigned_counts:
            info["assigned_jobs"] = assigned_counts[email]
        if email in placed_counts:
            info["placed_jobs"] = placed_counts[email]

        students.append(info)

    return {"students": students}

