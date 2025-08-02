# Air Recruiting Full-Stack App

This repository contains a basic full-stack application with a FastAPI backend and a React frontend.

## Backend

The backend uses [FastAPI](https://fastapi.tiangolo.com/). The entry point is `app/main.py`.
Run it with:

```bash
uvicorn app.main:app --reload
```

### Background workers

Matching jobs are processed asynchronously using [RQ](https://python-rq.org/).
Start a worker alongside the API server:

```bash
python worker.py
```

`/match` and `/rematches/{job_code}` enqueue work for these workers.

## Frontend

The frontend was bootstrapped with Create React App and lives in the `frontend` folder. Install dependencies and start the development server with:

```bash
cd frontend
npm install
npm start
```

## Tests

Tests use `pytest`. Run them with:

```bash
pytest
```

## Environment Variables

Create a `.env` file with these example values:

```
REACT_APP_API_URL=http://127.0.0.1:8000
REACT_APP_GOOGLE_KEY=frontend_key
GOOGLE_KEY=backend_key
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=username
SMTP_PASSWORD=secret
EMAIL_SENDER=noreply@example.com
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=admin123
SITE_BASE_URL=https://yourdomain.com
```

`SITE_BASE_URL` is used when building links in notification emails. It **must**
point to the publicly reachable FastAPI backend (for example,
`https://your-api.com`). If this value is set to the React frontend's address or
left blank, the links in emails will lead to missing pages.

## Registration Codes

Career services staff and recruiters must supply an institutional code when registering.
Codes can be requested from the `/request-code` page or by contacting
`support@talentmatch-ai.com`. Applicants do not need a code and may
register directly.

## Students Endpoint

Authenticated users can submit student information using `POST /students`.
Required fields now include location and travel distance:
`first_name`, `last_name`, `email`, `phone`, `education_level`, `skills`
(list of strings), `experience_summary`, `interests`, `city`, `state`, `lat`,
`lng`, and `max_travel` (in miles). The endpoint combines these details,
generates an OpenAI embedding and stores the result in Redis keyed by the
email address.

## Admin User Management

Administrators can manage user accounts. Use `DELETE /admin/users/{email}` to
remove a user from the system.

## Assignment and Rejection Workflow

Recruiters can assign a candidate to a job via `POST /assign`. Provide the
`job_code`, the student's email, and optionally a `note`. The student will be
added to the job's `assigned_students` list and, if provided, the note will be
stored under `student_notes[email]`.

If an assigned candidate is no longer interested, use `POST /reject-assigned`.
Include the `job_code`, the student's email, and an optional `note`. The student
will be removed from `assigned_students`, added to `rejected_students`, and any
note will be recorded in `student_notes[email]`.

Job objects created with `/jobs` now include `rejected_students` and
`student_notes` fields by default. Student listing endpoints (`/students/all`,
`/students/by-school`, and `/students/me`) return jobs with a status of either
`assigned` or `rejected` and include the stored note, so notes are visible for
both assigned and rejected students.

## Driving distance caching

Driving distance lookups use Google's Distance Matrix API. Results are cached in
Redis for 24 hours to minimize API requests.

## Nursing News

The `/nursing-news` endpoint retrieves articles from several nursing-focused RSS
feeds. Results are cached for one hour to improve performance. RSS requests use
a browser-like `User-Agent` header to avoid being blocked by some feed
providers.

## Metrics

Match jobs record queue and processing time in Redis. The `/metrics` endpoint exposes `total_match_queue_time` and `total_match_process_time` along with existing counters.

## Resume Previews

The `/generate-resume` endpoint accepts an optional `preview` flag. When `true`,
the generated resume includes placeholder contact information and does not
require the student to be listed in `assigned_students` for the job.
