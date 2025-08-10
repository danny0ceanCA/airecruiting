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
# Point the frontend to the API server. Use 127.0.0.1 if localhost doesn't resolve.
REACT_APP_API_URL=http://localhost:8000
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
`first_name`, `last_name`, `email`, `phone`, `license`, `skills`
(list of strings), `experience_summary`, `interests`, `city`, `state`, `lat`,
`lng`, and `max_travel` (in miles). The endpoint combines these details,
generates an OpenAI embedding and stores the result in Redis keyed by the
email address.

## Admin User Management

Administrators can manage user accounts. Use `DELETE /admin/users/{email}` to
remove a user from the system.

For testing purposes, administrators may manually trigger the weekly summary
email with `POST /admin/test-weekly-summary`. The admin interface includes a
"Send Weekly Summary Email" button under the **Tests** tab that calls this
endpoint.

## Assignment and Rejection Workflow

Recruiters can assign a candidate to a job via `POST /assign`. Provide the
`job_code`, the student's email, and optionally a `note`. The student will be
added to the job's `assigned_students` list and, if provided, the note will be
stored under `student_notes[email]` as a note object containing the text, the
author's email, and an ISO timestamp.

If an assigned candidate is no longer interested, use `POST /reject-assigned`.
Include the `job_code`, the student's email, and an optional `note`. The student
will be removed from `assigned_students`, added to `rejected_students`, and any
note will be appended to the `student_notes[email]` list with its author and
timestamp.

Job objects created with `/jobs` now include `rejected_students` and
`student_notes` fields by default. Student listing endpoints (`/students/all`,
`/students/by-school`, and `/students/me`) return jobs with a status of either
`assigned` or `rejected` and include all stored notes, so notes are visible for
both assigned and rejected students.

### Student Notes

Use `POST /student-note` with a `job_code`, the `student_email`, and a `note` to
record comments for a candidate. Recruiters may add notes only for jobs they
created **and** students they have assigned to those jobs. Administrators may
add notes for any job and are the only role permitted to edit or delete
existing notes. Each note is stored as an object containing the text, the
author's email, and an ISO timestamp. The endpoint does not change assignment
status and returns the updated list of notes.

Example recruiter request:

```json
{
  "job_code": "job123",
  "student_email": "alice@example.com",
  "note": "Left a voicemail"
}
```

Example admin edit request (`PUT /student-note`):

```json
{
  "job_code": "job123",
  "student_email": "alice@example.com",
  "index": 0,
  "note": "Spoke with candidate"
}
```

Example response:

```json
{
  "email": "alice@example.com",
  "notes": [
    {
      "text": "Left a voicemail",
      "author": "recruiter@example.com",
      "timestamp": "2024-05-01T12:34:56.000000"
    }
  ]
}
```

Student listing endpoints return this expanded structure. A typical job entry
may look like:

```json
{
  "job_code": "job123",
  "status": "assigned",
  "student_notes": {
    "alice@example.com": [
      {
        "text": "Left a voicemail",
        "author": "recruiter@example.com",
        "timestamp": "2024-05-01T12:34:56.000000"
      }
    ]
  }
}
```

In the job‑matching UI, each row in the match tables now has a **Comment**
control. Recruiters can open an inline text area to add or edit notes, which are
displayed for candidates in any status. Career services staff can also view a
complete history of notes for a student through a new notes history modal on the
career services interface.

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

## Backfilling Institutional Codes

Some legacy records may still use the `school_code` field instead of the
preferred `institutional_code`. A one-time script is provided to copy any
missing `institutional_code` values from `school_code` for both user and student
records stored in Redis.

Run the script with:

```bash
export REDIS_URL=redis://localhost:6379/0  # or your instance
python scripts/backfill_codes.py
```

The script scans all `user:*` and `student:*` keys and updates records where
`institutional_code` is absent but `school_code` exists.

## Scheduling Weekly Summaries

Run the scheduler script to enqueue weekly summary jobs:

```bash
export REDIS_URL=redis://localhost:6379/0  # adjust as needed
python scripts/schedule_weekly_summary.py
```

This configures the `weekly_summary_worker` to run every Monday at 08:00 server time. The script may be invoked at deploy time or via cron.

Career staff receive individual activity summaries, while any admin users are emailed a site-wide summary covering all career staff activity.
