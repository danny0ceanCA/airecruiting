# Air Recruiting Full-Stack App

This repository contains a basic full-stack application with a FastAPI backend and a React frontend.

## Backend

The backend uses [FastAPI](https://fastapi.tiangolo.com/). The entry point is `app/main.py`.
Run it with:

```bash
uvicorn app.main:app --reload
```

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

## Nursing News

The `/nursing-news` endpoint retrieves articles from several nursing-focused RSS
feeds. Results are cached for one hour to improve performance. RSS requests use
a browser-like `User-Agent` header to avoid being blocked by some feed
providers.
